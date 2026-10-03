"""Local Chan-inspired candidates, with explicit data/risk/execution stages."""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout)

from chan_strategy import analyze_chan
from local_strategy_runtime import completed_bars, order_quantity, quote_freshness_error


def describe_evidence(evidence):
    if not isinstance(evidence, dict) or not evidence:
        return ""
    parts = []
    if evidence.get("classification"):
        parts.append({"trend": "趋势背驰", "range": "盘整背驰"}.get(evidence["classification"], "背驰观察")
                     + "（日线笔级代理）")
    for key, title in (("center_band", "中枢重叠区间"), ("center_range", "中枢完整波动"),
                       ("previous_center_range", "前一中枢波动"), ("entry_dates", "进入笔日期"), ("exit_dates", "离开笔日期")):
        value = evidence.get(key)
        if isinstance(value, (tuple, list)) and value:
            parts.append(title + "：" + " 至 ".join(f"{v:.3f}" if isinstance(v, (int, float)) else str(v) for v in value))
    if evidence.get("area_ratio") is not None:
        parts.append(f"离开 / 进入笔 MACD 同向柱面积：{evidence['area_ratio']:.1%}")
    for key, title in (("base_date", "转折底日期"), ("base_price", "转折底价"), ("rebound_date", "反弹顶日期"),
                       ("anchor_date", "一类点极值日"), ("anchor_confirmed_date", "一类点确认日"), ("anchor_price", "一类点价格")):
        if evidence.get(key) is not None:
            parts.append(f"{title}：{evidence[key]}")
    if evidence.get("confirmation"):
        parts.append("右侧日 K 已收盘；次级别走势完成尚未验证")
    return "；".join(parts)


class LocalStrategyPanel(QGroupBox):
    def __init__(self, window):
        super().__init__("缠论日线笔结构 · 实验策略", window)
        self.host = window
        self.rows = []
        self._analysis_cache = {}
        self._refreshing = False
        layout = QVBoxLayout(self)
        hint = QLabel("包含处理 → 分型 → 严格笔 → 笔中枢代理 → 回试确认。仅使用已收盘日K；"
                      "一、二、三类买卖点均为笔结构近似，尚未实现递归线段中枢和多级别联立。无需 AI API。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        controls = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItem("仅三买代理", "third_buy")
        self.mode.addItem("二买 + 三买代理", "second_third")
        self.mode.addItem("一买 + 二买 + 三买代理", "first_second_third")
        selected = window.store.strategy_config().get("local_mode", "first_second_third")
        self.mode.setCurrentIndex(max(0, self.mode.findData(selected)))
        self.mode.currentIndexChanged.connect(self._save_settings)
        controls.addWidget(self.mode)
        self.automatic = QCheckBox("自动提交本地模拟委托")
        self.automatic.setChecked(bool(window.store.strategy_config().get("local_auto_submit", False)))
        self.automatic.toggled.connect(self._save_settings)
        controls.addWidget(self.automatic)
        controls.addStretch(1)
        submit = QPushButton("提交选中模拟委托")
        submit.clicked.connect(self.submit_selected)
        controls.addWidget(submit)
        layout.addLayout(controls)
        self.state = QLabel()
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["代码 / 名称", "已收盘日K", "结构信号", "确认日", "失效位", "数量", "阶段", "说明"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        for col, width in enumerate((158, 132, 160, 105, 90, 65, 140, 420)):
            self.table.setColumnWidth(col, width)
        self.table.setMinimumHeight(310)
        self.table.verticalHeader().setDefaultSectionSize(44)
        layout.addWidget(self.table)
        self.detail = QLabel("选择股票查看完整的结构与执行说明。")
        self.detail.setWordWrap(True)
        self.detail.setMinimumHeight(44)
        layout.addWidget(self.detail)
        self.table.itemSelectionChanged.connect(self.show_selected_detail)
        quantity_row = QHBoxLayout()
        self.quantity_label = QLabel("选中股票的每笔买入股数：")
        quantity_row.addWidget(self.quantity_label)
        self.quantity_input = QSpinBox()
        self.quantity_input.setRange(1, 2147483647)
        self.quantity_input.setEnabled(False)
        self.quantity_input.valueChanged.connect(self._save_quantity)
        quantity_row.addWidget(self.quantity_input)
        quantity_note = QLabel("默认一个最小申报单位，可修改；手工提交、自动提交和回测共用此数量。")
        quantity_note.setWordWrap(True)
        quantity_row.addWidget(quantity_note, 1)
        layout.addLayout(quantity_row)
        self.backtest_hint = QLabel("回测使用相同信号函数和上方每笔股数：确认后最早下一交易日成交，允许加仓，未成交单持续等待。"
                                    "日线无法还原日内成交队列，结果不等同当前账户。")
        self.backtest_hint.setWordWrap(True)
        layout.addWidget(self.backtest_hint)
        backtest_row = QHBoxLayout()
        self.run_button = QPushButton("用已缓存日K回测当前自选")
        self.run_button.clicked.connect(self.start_backtest)
        backtest_row.addWidget(self.run_button)
        self.open_button = QPushButton("打开最近回测报告")
        self.open_button.clicked.connect(self.open_backtest)
        backtest_row.addWidget(self.open_button)
        backtest_row.addStretch(1)
        layout.addLayout(backtest_row)
        self.worker = None

    def _save_settings(self, *_args):
        cfg = self.host.store.strategy_config()
        cfg["local_mode"] = self.mode.currentData()
        cfg["local_auto_submit"] = self.automatic.isChecked()
        self.host.store.save()
        self.refresh_rows()

    def _calendar(self):
        from StockTradingSim import load_trading_calendar
        return load_trading_calendar()

    def _save_quantity(self, value):
        index = self.table.currentRow()
        if self._refreshing or not 0 <= index < len(self.rows):
            return
        code = self.rows[index]["code"]
        self.host.store.strategy_config().setdefault("local_order_quantities", {})[code] = value
        self.host.store.save()
        self.refresh_rows()

    def _candidate(self, code, now, calendar):
        from StockTradingSim import is_tradable_security, trading_time_error
        host = self.host
        quote = host.quote_cache.get(code)
        rows, data_warnings = completed_bars(host.daily_kline_dicts(code), code, now, calendar)
        mode = self.mode.currentData()
        key = (mode, tuple((b["date"], b["open"], b["high"], b["low"], b["close"]) for b in rows))
        cached = self._analysis_cache.get(code)
        if not cached or cached[0] != key:
            try:
                analysis = analyze_chan(rows, mode=mode)
            except (ValueError, TypeError, KeyError) as exc:
                analysis = {"signal": "wait", "status": "invalid_data", "reason": f"结构数据异常：{exc}"}
            self._analysis_cache[code] = (key, analysis)
        analysis = self._analysis_cache[code][1]
        item = {k: v for k, v in analysis.items() if k not in ("structures", "signal_history")}
        structures = analysis.get("structures") or {}
        item["structure_summary"] = {
            "fractals": len(structures.get("fractals", [])), "strokes": len(structures.get("strokes", [])),
            "centers": len(structures.get("centers", [])), "segments": len(structures.get("segments", [])),
            "pending": (structures.get("segment_pending") or {}).get("reason") or "等待锁定笔及标准特征序列分型确认。",
        }
        # A historical confirmation remains available for an explicit submission.
        # Newer signals replace it; elapsed trading days do not expire it.
        if analysis.get("signal_history"):
            item.update(analysis["signal_history"][-1])
        item.update(code=code, name=quote.name if quote else code, bars=len(rows),
                    last_bar=rows[-1]["date"] if rows else "", quantity=0,
                    stage="等待结构", eligible=False, blocks=[], data_warnings=data_warnings)
        if not is_tradable_security(code):
            item.update(stage="指数仅观察", reason="指数用于市场参考，不能提交买卖")
            return item
        local_lots = [lot for lot in host.store.data.get("lots", [])
                      if lot.get("code") == code and int(lot.get("qty") or 0) > 0 and lot.get("local_signal_id")]
        stop = max((float(lot.get("structure_stop") or 0) for lot in local_lots), default=0.0)
        # Protective exits apply only to positions entered by this local engine.
        if local_lots and quote and stop and (quote.price <= stop or any(lot.get("stop_triggered") for lot in local_lots)):
            item.update(signal="sell", pattern="结构失效退出", stop_price=stop,
                        signal_id="stop:" + ":".join(str(lot.get("id") or lot.get("buy_time") or lot["local_signal_id"]) for lot in local_lots),
                        confirmed_date=now.date().isoformat(), reason="现价跌破持仓结构失效位")
        elif item.get("signal") == "sell" and not local_lots:
            item.update(stage="卖点仅观察", reason="该股票没有本地策略持仓，保留卖点供参考")
            return item
        if item.get("signal") not in ("buy", "sell"):
            recent = next((order for order in reversed(host.store.data.get("pending_orders", []))
                           if order.get("code") == code and order.get("local_signal_id")), None)
            if recent:
                item["stage"] = {"ACTIVE": "已有委托等待成交", "FILLED": "已有成交 / 等待新结构",
                                 "FAILED": "原委托失败", "EXPIRED": "原委托已到期", "CANCELLED": "原委托已撤销"}.get(recent.get("status"), "等待新结构")
                item["reason"] = str(item.get("reason") or "") + "；最近委托：" + str(recent.get("wait_reason") or recent.get("error") or recent.get("reason") or "")
            if data_warnings:
                item["reason"] = "；".join(data_warnings + [str(item.get("reason", ""))])
            if len(rows) < 60:
                item["reason"] = f"仅{len(rows)}根日K；" + str(item.get("reason", ""))
            return item
        signal_id = code + ":" + str(item.get("signal_id") or "")
        item["local_signal_id"] = signal_id
        blocks = item["blocks"]
        if not host.store.is_strategy_enabled("chan_daily"):
            blocks.append("本地缠论策略已在设置中停用")
        if not quote:
            blocks.append("无实时报价，先刷新行情")
        else:
            stale = quote_freshness_error(quote, now)
            if stale:
                blocks.append(stale)
        action = item["signal"]
        if item.get("pattern") != "结构失效退出":
            confirmation = str(item.get("confirmed_date") or "")
            if not confirmation:
                blocks.append("结构尚未给出确认日期")
            elif confirmation > now.date().isoformat():
                blocks.append("结构确认日在未来，不能使用未来信号")
            elif confirmation == now.date().isoformat():
                blocks.append("等待确认后的下一交易日，不能在确认日成交")
        if action == "buy":
            if quote:
                price = float(quote.price)
                item["limit_price"] = round(price, 3 if code.startswith("hk") else 2)
                minimum, step, _ = host.store.order_rule(code)
                item["quantity"] = order_quantity(host.store.strategy_config(), code, minimum)
                if item["quantity"] < minimum or item["quantity"] % step:
                    blocks.append(f"买入数量须至少{minimum}股，并按{step}股递增，请修改每笔股数")
                if item["quantity"] * item["limit_price"] > host.store.available_cash() + 1e-8:
                    blocks.append("可用资金不足填写的股数，请调整股数或释放冻结资金")
        else:
            local_qty = sum(int(lot.get("qty") or 0) for lot in local_lots
                            if code.startswith("hk") or str(lot.get("buy_date", now.date().isoformat())) < now.date().isoformat())
            reserved_local = sum(int(o.get("qty") or 0) for o in host.store.active_pending_orders()
                                 if o.get("code") == code and o.get("action") == "SELL" and o.get("local_signal_id"))
            item["quantity"] = max(0, min(local_qty - reserved_local, host.store.available_sell_qty(code)))
            if item["quantity"] <= 0:
                blocks.append("本地持仓暂无可卖数量（A股T+1或已冻结）")
            if quote:
                item["limit_price"] = round(float(quote.price), 3 if code.startswith("hk") else 2)
        time_error = trading_time_error(code, now)
        if time_error:
            blocks.append(time_error)
        if quote and item["quantity"]:
            blocks.extend(host.risk_violations_for_order(action, quote, item["quantity"], item["limit_price"]))
        item["eligible"] = not blocks
        item["stage"] = "待提交模拟委托" if not blocks else "已确认 / 执行受限"
        if not blocks:
            item["reason"] = str(item.get("reason") or "") + ("；可按填写股数提交，允许加仓和手工重投" if action == "buy" else "；仅卖出本地策略来源的可卖持仓")
        if blocks:
            item["reason"] = "；".join(dict.fromkeys(blocks))
        return item

    def refresh_rows(self):
        previous = self.table.currentRow()
        selected = self.rows[previous]["code"] if 0 <= previous < len(self.rows) else ""
        self._refreshing = True
        calendar = self._calendar()
        now = dt.datetime.now()
        self.rows = [self._candidate(code, now, calendar) for code in self.host.strategy_code_universe()]
        self.table.setRowCount(len(self.rows))
        for i, row in enumerate(self.rows):
            stop = float(row.get("stop_price") or 0)
            values = [row["code"] + "\n" + row["name"], f"{row['bars']}根 / {row['last_bar']}",
                      {"none": "等待确认", "proxy_1buy": "一买代理", "proxy_3buy": "三买代理", "proxy_2buy": "二买代理", "proxy_1sell": "一卖代理", "proxy_2sell": "二卖代理", "proxy_3sell": "三卖代理", "proxy_range_sell": "盘整背驰退出", "range_divergence_sell": "盘整背驰退出"}.get(row.get("pattern"), str(row.get("pattern") or "等待确认")), str(row.get("confirmed_date") or "—"),
                      f"{stop:.3f}" if stop else "—", str(row["quantity"] or "—"), row["stage"], str(row.get("reason") or "")]
            for j, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value + ("\n" + str(row.get("reason") or "") if j != 7 else ""))
                cell.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                self.table.setItem(i, j, cell)
        if selected:
            selected_index = next((i for i, row in enumerate(self.rows) if row["code"] == selected), -1)
            if selected_index >= 0:
                self.table.selectRow(selected_index)
        self._refreshing = False
        ready = sum(bool(r["eligible"]) for r in self.rows)
        state = "自动提交模拟委托已开启（仅运行软件且行情有效时工作）" if self.automatic.isChecked() else "自动提交已关闭；买卖点及结构止损均只提示，需选中后提交"
        self.state.setText(f"{state}。当前可提交 {ready} 条。仅同股活动委托上限3；已用信号可再次手工提交。"
                           "自动模式每个新确认事件派发一次，刷新行情不会循环下单；委托无每日过期限制。")
        self.show_selected_detail()

    def show_selected_detail(self):
        if self._refreshing:
            return
        index = self.table.currentRow()
        if 0 <= index < len(self.rows):
            row = self.rows[index]
            evidence = row.get("evidence") or row.get("context")
            evidence_text = "\n结构依据：" + describe_evidence(evidence) if evidence else ""
            structure = row.get("structure_summary", {})
            structure_text = (f"\n结构进度：分型 {structure.get('fractals', 0)}，笔 {structure.get('strokes', 0)}，笔中枢 {structure.get('centers', 0)}，"
                              f"已确认线段子集 {structure.get('segments', 0)}。仅含标准特征序列无缺口完成情形，尚未递归联立；"
                              f"未完成线段：{structure.get('pending', '待形成')}")
            self.detail.setText(f"{row['code']} · {row['stage']}：{row.get('reason') or ''}" + evidence_text + structure_text)
            minimum, step, _ = self.host.store.order_rule(row["code"])
            self.quantity_input.blockSignals(True)
            self.quantity_input.setSingleStep(step)
            self.quantity_input.setValue(order_quantity(self.host.store.strategy_config(), row["code"], minimum))
            self.quantity_input.setEnabled(row["stage"] != "指数仅观察")
            self.quantity_input.blockSignals(False)
            self.quantity_label.setText(f"{row['code']} 每笔买入股数：")
        else:
            self.detail.setText("选择股票查看完整的结构与执行说明。")
            self.quantity_input.setEnabled(False)

    def context(self):
        self.refresh_rows()
        return {"model": "chan_daily_stroke_proxy_v2", "mode": self.mode.currentData(),
                "auto_submit": self.automatic.isChecked(), "candidates": self.rows,
                "order_quantities": self.host.store.strategy_config().get("local_order_quantities", {}),
                "scope": "日线笔结构近似，不是完整递归缠论；CAN SLIM评分不作为结构买点的必要条件"}

    def _submit(self, row, *, automatic=False):
        if not row.get("eligible"):
            return False
        metadata = dict(local_signal_id=row["local_signal_id"], structure_stop=row.get("stop_price"),
                        signal_confirmed_at=row.get("confirmed_date"), local_model="chan_daily_stroke_proxy_v2",
                        local_submission_kind="automatic" if automatic else "manual")
        if automatic:
            metadata["local_auto_event_id"] = self.mode.currentData() + ":" + row["local_signal_id"]
        self.host.store.add_pending_order(row["signal"], self.host.quote_cache[row["code"]],
            row["quantity"], row["limit_price"], "本地策略", str(row.get("pattern") or "") + "；" + str(row.get("reason") or ""),
            metadata=metadata)
        return True

    def submit_selected(self):
        index = self.table.currentRow()
        code = self.rows[index]["code"] if 0 <= index < len(self.rows) else ""
        self.refresh_rows()
        row = next((item for item in self.rows if item["code"] == code), None)
        if not row:
            self.host.status.setText("请先选中一只股票。")
            return
        if not row["eligible"]:
            self.host.status.setText(row["stage"] + "：" + str(row.get("reason") or ""))
            return
        try:
            self._submit(row)
            self.host.try_execute_pending_orders()
            self.host.render_all()
            self.refresh_rows()
        except ValueError as exc:
            self.host.status.setText(f"本地候选未提交：{exc}")

    def on_quotes_refreshed(self):
        from StockTradingSim import trading_time_error
        # A stop hit while CN shares are T+1-locked remains an exit instruction,
        # even if the quote recovers before those shares become sellable.
        changed = False
        now = dt.datetime.now()
        for lot in self.host.store.data.get("lots", []):
            code = str(lot.get("code") or "")
            quote = self.host.quote_cache.get(code)
            stop = float(lot.get("structure_stop") or 0)
            if (lot.get("local_signal_id") and not lot.get("stop_triggered") and quote and stop > 0
                    and quote.price <= stop and not quote_freshness_error(quote, now)
                    and not trading_time_error(code, now)):
                lot["stop_triggered"] = True
                changed = True
        if changed:
            self.host.store.save()
        self.refresh_rows()
        if not self.automatic.isChecked() or not self.host.strategy_enabled("chan_daily"):
            return
        for code in [row["code"] for row in self.rows if row["eligible"]]:
            # Re-evaluate cash/reservations after every submission.
            row = self._candidate(code, dt.datetime.now(), self._calendar())
            # Transport idempotency applies only to automatic dispatch. It is not
            # an eligibility check: the same signal remains manually repeatable.
            dispatches = self.host.store.strategy_config().setdefault("local_auto_dispatches", {})
            dispatch_key = self.mode.currentData() + ":" + code
            signal_key = row.get("local_signal_id")
            event_key = self.mode.currentData() + ":" + str(signal_key)
            handled = self.host.store.strategy_config().setdefault("local_auto_events", {})
            # The order itself is persisted atomically with this identity; an
            # interruption before saving the extra index must not duplicate it.
            recorded = any(o.get("local_auto_event_id") == event_key
                           for o in self.host.store.data.get("pending_orders", []))
            if handled.get(event_key) or recorded or dispatches.get(dispatch_key) == signal_key:
                continue
            try:
                if self._submit(row, automatic=True):
                    handled[event_key] = dt.datetime.now().isoformat(timespec="seconds")
                    self.host.store.save()
                    self.host.try_execute_pending_orders()
            except ValueError as exc:
                self.host.status.setText(f"{code} 本地候选未提交：{exc}")
        self.refresh_rows()

    def start_backtest(self):
        from StockTradingSim import runtime_dir
        from strategy_backtest_ui import BacktestWorker
        if self.worker and self.worker.isRunning():
            return
        calendar = self._calendar()
        dataset = {code: completed_bars(self.host.daily_kline_dicts(code), code, dt.datetime.now(), calendar)[0]
                   for code in self.host.strategy_code_universe() if not code.startswith(("sh000", "sz399"))}
        quantities = {code: order_quantity(self.host.store.strategy_config(), code, self.host.store.order_rule(code)[0])
                      for code in dataset}
        lot_rules = {code: self.host.store.order_rule(code)[:2] for code in dataset}
        self.worker = BacktestWorker(dataset, self.mode.currentData(), Path(runtime_dir()) / "reports" / "backtest", self,
                                     order_quantities=quantities, lot_rules=lot_rules)
        self.worker.progress.connect(self.backtest_hint.setText)
        self.worker.completed.connect(self._backtest_done)
        self.worker.finished.connect(lambda: self.run_button.setEnabled(True))
        self.run_button.setEnabled(False)
        self.worker.start()

    def _backtest_done(self, path, error):
        if error:
            self.backtest_hint.setText("回测未完成：" + error)
        else:
            self.host.store.strategy_config()["last_backtest_report"] = path
            self.host.store.save()
            self.backtest_hint.setText("回测已完成：" + path + "。当前账户未产生任何回测委托。")

    def open_backtest(self):
        from StockTradingSim import runtime_dir
        path = self.host.store.strategy_config().get("last_backtest_report")
        if not path:
            path = str(Path(runtime_dir()) / "reports" / "strategy-review.html")
        if os.path.isfile(path):
            os.startfile(path)
        else:
            self.backtest_hint.setText("暂无回测报告，请先刷新历史日K并运行回测。")
