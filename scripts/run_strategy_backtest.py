"""Replay cached daily bars and produce auditable JSON and a Chinese HTML report."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import html
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from strategy_backtest import run_backtest
from scripts.fetch_backtest_data import DEFAULT_SYMBOLS

MODE_LABELS = {"third_buy": "仅三买", "second_third": "二买 + 三买", "first_second_third": "一买 + 二买 + 三买"}
REASONS = {
    "no_volume": "当日无成交量，委托继续等待",
    "insufficient_cash_for_requested_quantity": "资金不足填写股数，保留原股数等待",
    "insufficient_sellable_quantity_t_plus_1": "可卖股数不足或 A 股 T+1，继续等待",
    "limit_not_reached": "未到委托限价，继续等待",
    "max_active_orders_per_symbol": "同股活动委托已达 3 笔",
    "no_next_session_in_dataset": "数据到期末，尚无下一根 K 线；委托仍有效",
    "no_unreserved_position_to_exit": "没有未冻结的策略持仓可卖",
    "reference_not_confirmation_close": "信号参考价不是确认收盘价",
    "signal_not_confirmed_on_current_bar": "确认日期与当前回放日期不符",
    "invalid_signal": "信号方向无效",
    "structure_stop": "持仓结构失效退出",
    "structure_stop_at_close": "日内新成交持仓在收盘确认结构失效",
    "stop_deferred_by_cn_t_plus_1": "先前已触发结构止损，待可卖后退出",
    "first_buy": "一买代理", "second_buy": "二买代理", "third_buy": "三买代理",
    "first_sell": "一卖代理", "second_sell": "二卖代理", "third_sell": "三卖代理",
    "range_divergence_sell": "盘整背驰退出", "filled": "已成交", "order_submitted": "委托已派发",
    "entry_order": "买入委托", "exit_order": "卖出委托", "buy": "买入成交", "sell": "卖出成交",
    "wait": "等待成交", "blocked": "未派发", "defer_exit": "退出等待", "ACTIVE": "活动中", "FILLED": "已成交",
}


def label(value):
    value = str(value or "—")
    if value.startswith("active_waiting: "):
        return "活动委托：" + label(value.removeprefix("active_waiting: "))
    return REASONS.get(value, value)


def h(value):
    return html.escape(str(value if value is not None else "—"))


def number(value, digits=2):
    return "—" if value is None else f"{value:,.{digits}f}"


def table(headers, rows):
    return "<div class='scroll'><table><thead><tr>" + "".join(f"<th>{h(item)}</th>" for item in headers) + "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{h(item)}</td>" for item in row) + "</tr>" for row in rows) + "</tbody></table></div>"


def render_report(manifest, results, destination: Path, start: str) -> None:
    now = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    pieces = ["""<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>AIStockSim 3.3 日线策略回测</title><style>
:root{color-scheme:light}body{font:15px/1.7 'Microsoft YaHei',sans-serif;background:#f3f5f8;color:#172337;margin:0}main{max-width:1440px;margin:auto;padding:32px}h1{font-size:28px}h2{margin-top:32px}.card,details{background:white;border:1px solid #dce2eb;border-radius:10px;padding:20px;margin:16px 0}.note{background:#fff6de;border-left:4px solid #e9ad31;padding:16px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid #e3e7ee;padding:9px 10px;text-align:left;white-space:nowrap}th{background:#eef2f7}summary{cursor:pointer;font-weight:bold}small{color:#52627b}svg{width:100%;height:220px;background:#fbfcff;border:1px solid #e5eaf1}.wrap{white-space:normal} @media print{body{background:white}main{padding:0}}</style><main>
<h1>AIStockSim 3.3 · 日线笔结构代理策略回测</h1>
<p>逐日重放确认事件，展示信号 → 委托 → 等待或成交。持仓后可以继续买入，股数明确填写，未成交委托持续有效。</p>"""]
    pieces.append(f"<p><small>生成：{h(now)} · 请求起始：{h(start)} · 数据：{h(manifest.get('data_provider', '本地日 K 缓存'))}</small></p>")
    pieces.append("<div class='note'>这是独立研究账本，不会操作当前模拟账户。每个股票使用独立的当地货币账户，收益不能相加。前复权日 K 无法重建真实成交队列或历史公司行动。</div>")
    pieces.append("""<div class='card'><h2>本次执行口径</h2><ul>
<li>策略只接收截至当日收盘的历史前缀；确认信号最早在下一根日 K 执行。先处理已有委托，再评估当日收盘的新信号。</li>
<li>每笔使用下表列出的明确股数，不按仓位比例或风险预算缩小；已有持仓允许加买。同股买卖活动委托合计最多 3 笔。</li>
<li>新委托在首个可执行日的开盘价确定限价，后续保持该限价。停牌、限价未触及或资金不足时等待，并逐日记录原因，不自动过期；不新增追涨幅度或入场止损位拒买条件。</li>
<li>买入按完整股数及成本检查现金。研究账本允许资金不足的意向单持续排队；软件实时提交时仍须有足额可用资金，所以两者不是历史账户逐笔复刻。</li>
<li>所有买卖点按信号方向执行，一卖、二卖、三卖和盘整背驰退出均可卖出策略持仓。持仓结构止损继续生效；A 股执行 T+1，港股可当日卖出。</li>
<li>日内高低点顺序未知：日内卖出所得不用于当日另一笔日内买入；刚在日内限价成交的批次只以该日收盘判定止损，避免使用买入前的最低价。跨日委托按先提交先处理。</li>
<li>成本为单边 15 / 30 bp 简化假设。基准在区间首次有成交量日，按同一填写股数一次买入持有；资金不足则保留现金，期末不强行平仓。</li>
<li>一、二、三买卖点均为日线笔结构近似；尚未实现递归线段中枢和多级别联立。CAN SLIM 是另一个体系，不是“缠”的英文名。</li></ul></div>""")
    data_rows = []
    for code, item in manifest.get("symbols", {}).items():
        quality = item.get("quality", {})
        notes = []
        if quality.get("short_history_under_250_bars"):
            notes.append("不足 250 根")
        if quality.get("invalid_rows"):
            notes.append(f"无效 {len(quality['invalid_rows'])} 根；保留最后异常后的连续段")
        data_rows.append([code, item.get("name", code), item.get("bars", "—"), item.get("first_date", "—"),
                          item.get("last_date", "—"), item.get("error") or "；".join(notes) or "通过 OHLC 与日期校验"])
    pieces.append("<h2>数据范围</h2>" + table(["代码", "当前名称", "日 K 数", "最早", "最晚", "数据说明"], data_rows))
    summary_rows = []
    for result in results:
        count, metric = result["counters"], result["metrics"]
        summary_rows.append([result["code"], MODE_LABELS.get(result["mode"], result["mode"]), result["assumptions"]["order_quantity"],
                             result["assumptions"]["one_way_cost_bps"], count["buy_signals"], count["sell_signals"], count["entries"],
                             count["closed_trades"], count["open_positions"], count["active_orders"], number(metric["return_pct"]) + "%",
                             number(result["benchmark"]["return_pct"]) + "%", number(metric["max_drawdown_pct"]) + "%"])
    pieces.append("<h2>结果与成本敏感性</h2>" + table(["代码", "模式", "每笔股数", "成本 bp", "买信号", "卖信号", "买入成交", "平仓批次", "持仓批次", "等待委托", "账户收益", "同股数买持基准", "最大回撤"], summary_rows))
    pieces.append("<p>收益以各结果 JSON 中的 initial_cash 为分母，保留现金；平仓按买入批次统计，同一次卖出可包含多个批次。零成交仍保留信号和委托明细。</p>")
    for result in results:
        title = f"{result['code']} · {MODE_LABELS.get(result['mode'], result['mode'])} · 单边 {result['assumptions']['one_way_cost_bps']:g} bp"
        pieces.append(f"<details><summary>{h(title)}</summary>")
        curve = result["equity_curve"]
        if len(curve) > 1:
            values = [point[key] for point in curve for key in ("equity", "benchmark_equity")]
            bottom, top = min(values), max(values)
            def line(key):
                return " ".join(f"{20 + i / (len(curve) - 1) * 960:.2f},{190 - (point[key] - bottom) / max(top - bottom, 1) * 160:.2f}" for i, point in enumerate(curve))
            pieces.append(f"<p><small>蓝：策略；灰：同股数一次买持。{h(curve[0]['date'])} 至 {h(curve[-1]['date'])}；纵轴 {number(bottom)} 至 {number(top)}。</small></p><svg viewBox='0 0 1000 220' role='img' aria-label='策略与基准净值'><polyline fill='none' stroke='#9ba8b9' stroke-width='2' points='{line('benchmark_equity')}'/><polyline fill='none' stroke='#1a64cb' stroke-width='2.5' points='{line('equity')}'/></svg>")
        pieces.append("<h3>确认信号</h3>" + table(["确认日", "方向 / 类型", "信号编号", "关联委托", "处理", "结构依据"],
            [[item.get("confirmed_date"), label(item.get("kind") or item.get("signal")), item.get("signal_id"), item.get("order_id"),
              label(item.get("disposition")), json.dumps(item.get("evidence") or item.get("context") or {}, ensure_ascii=False)] for item in result["signals"]]))
        pieces.append("<h3>全部委托及未成交原因</h3>" + table(["委托编号", "信号编号", "派发日", "方向", "股数", "固定限价", "状态", "成交日", "成交价", "当前等待原因"],
            [[item["id"], item["signal_id"], item["created_date"], label(item["action"]), item["quantity"], number(item["limit_price"], 3),
              label(item["status"]), item.get("fill_date"), number(item.get("fill_price"), 3), label(item.get("wait_reason"))] for item in result["orders"]]))
        pieces.append("<h3>逐日执行事件</h3>" + table(["日期", "阶段", "委托编号", "信号编号", "数量", "价格", "原因"],
            [[item["date"], label(item["action"]), item.get("order_id"), item.get("signal_id"), item.get("quantity"),
              number(item.get("price"), 3), label(item.get("reason"))] for item in result["events"]]))
        pieces.append("<h3>已平仓批次</h3>" + table(["买入日", "卖出日", "股数", "买入价", "卖出价", "扣成本盈亏", "退出原因"],
            [[item["entry_date"], item["exit_date"], item["quantity"], number(item["entry_price"], 3), number(item["exit_price"], 3), number(item["pnl"]), label(item["exit_reason"])] for item in result["trades"]]))
        pieces.append("<h3>期末持仓批次</h3>" + table(["买入日", "买入委托", "股数", "买入价", "末日收盘", "未实现盈亏", "结构失效位"],
            [[item["entry_date"], item["id"], item["quantity"], number(item["entry_price"], 3), number(item["last_close"], 3), number(item["unrealized_pnl"]), number(item["stop_price"], 3)] for item in result["open_lots"]]))
        pieces.append("<h3>逐日结构状态</h3>" + table(["状态", "日数"], result["analysis_status_counts"].items()) + "</details>")
    pieces.append("<h2>解释边界</h2><div class='card'>自选样本存在事后选样偏差；短历史和少量成交不能证明策略有效。未完整重建历史 ST、IPO 涨跌停、封单排队、市场冲击、停牌期限、汇率及逐时点公司行动。前复权价格依赖当前调整因子。日 K 路径假设可能影响同日多单和止损结果，研究回测不等同实时报价模拟成交。</div></main></html>")
    destination.write_text("\n".join(pieces), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=PROJECT / "build" / "backtest-data")
    parser.add_argument("--output", type=Path, default=PROJECT / "build" / "backtest-results")
    parser.add_argument("--start", default="2024-10-01")
    parser.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS)
    parser.add_argument("--costs", nargs="+", type=float, default=[15, 30])
    parser.add_argument("--modes", nargs="+", choices=list(MODE_LABELS), default=list(MODE_LABELS))
    parser.add_argument("--order-quantity", type=int, help="Every buy uses these exact shares; omitted means one symbol-specific minimum lot")
    args = parser.parse_args()
    from chan_strategy import analyze_chan
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((args.data / "manifest.json").read_text(encoding="utf-8"))
    results = []
    for code in args.symbols:
        payload = json.loads((args.data / f"{code}.json").read_text(encoding="utf-8"))
        for mode in args.modes:
            cache = {}
            def cached_signal(prefix, mode=mode):
                key = (len(prefix), mode)
                if key not in cache:
                    response = analyze_chan(prefix, mode=mode)
                    cache[key] = {name: value for name, value in response.items() if name not in ("structures", "signal_history")}
                return cache[key]
            for cost in args.costs:
                print(f"Running {code} {mode} {cost:g}bp", flush=True)
                result = run_backtest(payload["klines"], code, mode=mode, start=args.start, cost_bps=cost,
                                      signal_fn=cached_signal, order_quantity=args.order_quantity)
                result["data_metadata"] = payload["metadata"]
                results.append(result)
                (args.output / f"{code}-{mode}-{cost:g}bp.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"  signals={result['counters']['buy_signals']} entries={result['counters']['entries']} active={result['counters']['active_orders']} return={result['metrics']['return_pct']:.2f}%", flush=True)
    summaries = [{key: value for key, value in result.items() if key not in ("equity_curve", "trades", "signals", "orders", "events", "data_metadata")} for result in results]
    (args.output / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    render_report(manifest, results, args.output / "策略回测报告.html", args.start)
    print(f"Report: {args.output / '策略回测报告.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
