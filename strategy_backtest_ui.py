"""Qt worker adapter; all computation/output happens outside the GUI thread."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from chan_strategy import analyze_chan
from scripts.fetch_backtest_data import validate
from scripts.run_strategy_backtest import render_report
from strategy_backtest import run_backtest


class BacktestWorker(QThread):
    progress = Signal(str)
    completed = Signal(str, str)

    def __init__(self, dataset: dict[str, list], mode: str, output_dir: Path, parent=None,
                 *, order_quantities: dict | None = None, lot_rules: dict | None = None):
        super().__init__(parent)
        self.dataset = dataset
        self.mode = mode
        self.output_dir = Path(output_dir)
        self.order_quantities = dict(order_quantities or {})
        self.lot_rules = dict(lot_rules or {})

    def run(self) -> None:
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            # The panel already applies the exchange-aware completed_bars
            # filter. Preserve a completed bar from today's closed session;
            # only reject future calendar dates here.
            before = datetime.now(timezone(timedelta(hours=8))).date() + timedelta(days=1)
            manifest = {"as_of_exclusive": before.isoformat(),
                        "data_provider": "应用本地日 K 缓存（源自东方财富前复权接口；未重新联网核验）", "symbols": {}}
            results = []
            for code, source in self.dataset.items():
                if self.isInterruptionRequested():
                    raise InterruptedError("回测已取消")
                raw = [asdict(row) if is_dataclass(row) else dict(row) for row in source]
                bars, quality = validate(raw, before)
                if not bars:
                    manifest["symbols"][code] = {"status": "failed", "error": "没有有效且已结束的日 K"}
                    continue
                metadata = {"symbol": code, "status": "ok", "name": code, "bars": len(bars),
                            "first_date": bars[0]["date"], "last_date": bars[-1]["date"],
                            "provider": "Application daily cache", "quality": quality,
                            "as_of_exclusive": before.isoformat()}
                manifest["symbols"][code] = metadata
                cache = {}
                def signal_fn(prefix, mode):
                    if self.isInterruptionRequested():
                        raise InterruptedError("回测已取消")
                    key = (len(prefix), mode)
                    if key not in cache:
                        response = analyze_chan(prefix, mode=mode)
                        cache[key] = {name: value for name, value in response.items() if name not in ("structures", "signal_history")}
                    return cache[key]
                for cost in (15, 30):
                    self.progress.emit(f"正在回测 {code}：单边成本 {cost} bp")
                    result = run_backtest(bars, code, mode=self.mode, start="2024-10-01", cost_bps=cost, signal_fn=signal_fn,
                                          order_quantity=self.order_quantities.get(code), lot_rule=self.lot_rules.get(code))
                    result["data_metadata"] = metadata
                    results.append(result)
                    (self.output_dir / f"{code}-{self.mode}-{cost}bp.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            if not results:
                raise ValueError("没有可用股票历史；请先刷新行情并等待日 K 缓存完成")
            (self.output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            report = self.output_dir / "策略回测报告.html"
            render_report(manifest, results, report, "2024-10-01")
            self.completed.emit(str(report.resolve()), "")
        except Exception as exc:
            self.completed.emit("", f"{type(exc).__name__}: {exc}")
