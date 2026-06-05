# filename: StockTradingSim.py
# python -m PyInstaller -F -w .\StockTradingSim.py --name StockTradingSim --icon .\StockWidget.ico --add-data ".\StockWidget.ico;."
import datetime as dt
import json
import os
import re
import sys
import winreg
from dataclasses import dataclass
from typing import Any

import requests
import StockWidget as LegacyStockWidget
from PySide6.QtCore import Qt, QTimer
from PySide6.QtCore import QSize
from PySide6.QtGui import QAction, QColor, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "StockTradingSim"
APP_VERSION = "1.0.0"
CONFIG_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "portfolio.json")
CODEX_ORDER_FILE = os.path.join(CONFIG_DIR, "codex_orders.json")
TRADING_CALENDAR_FILE = os.path.join(CONFIG_DIR, "trading_calendar.json")
COMPACT_CONFIG_FILE = os.path.join(CONFIG_DIR, "compact_config.json")
ICON_FILE = "StockWidget.ico"
DEFAULT_HK_BOARD_LOTS = {
    "hk00700": 100,
    "hk00941": 500,
    "hk01810": 200,
    "hk09988": 100,
}
REFRESH_INTERVAL_OPTIONS = [1, 2, 3, 5, 10, 15, 30, 60]
DEFAULT_TRADING_CALENDAR = {
    "version": "2026.1",
    "markets": {
        "cn": {
            "name": "A 股",
            "closed_dates": [
                "2026-01-01", "2026-01-02", "2026-01-03",
                "2026-02-15", "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20", "2026-02-21", "2026-02-22", "2026-02-23",
                "2026-04-04", "2026-04-05", "2026-04-06",
                "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
                "2026-06-19",
                "2026-09-25",
                "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05", "2026-10-06", "2026-10-07",
            ],
            "half_days": [],
        },
        "hk": {
            "name": "港股",
            "closed_dates": [
                "2026-01-01",
                "2026-02-17", "2026-02-18", "2026-02-19",
                "2026-04-03", "2026-04-06", "2026-04-07",
                "2026-05-01", "2026-05-25",
                "2026-06-19",
                "2026-07-01",
                "2026-10-01", "2026-10-19",
                "2026-12-25",
            ],
            "half_days": ["2026-02-16", "2026-12-24", "2026-12-31"],
        },
    },
}


def resource_path(rel_path: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel_path)


def ensure_config_dir() -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)


def load_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: str, data: Any) -> None:
    ensure_config_dir()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_compact_config() -> dict[str, Any]:
    cfg = load_json(COMPACT_CONFIG_FILE, {})
    return cfg if isinstance(cfg, dict) else {}


def save_compact_config_file(cfg: dict[str, Any]) -> None:
    save_json(COMPACT_CONFIG_FILE, cfg)


def load_trading_calendar() -> dict[str, Any]:
    calendar = load_json(TRADING_CALENDAR_FILE, None)
    if not isinstance(calendar, dict) or not isinstance(calendar.get("markets"), dict):
        calendar = DEFAULT_TRADING_CALENDAR
        save_json(TRADING_CALENDAR_FILE, calendar)
        return calendar
    changed = False
    for market, default_value in DEFAULT_TRADING_CALENDAR["markets"].items():
        if market not in calendar["markets"]:
            calendar["markets"][market] = default_value
            changed = True
    if changed:
        save_json(TRADING_CALENDAR_FILE, calendar)
    return calendar


def today_str() -> str:
    return dt.date.today().isoformat()


def now_str() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def money(value: float, currency: str = "CNY") -> str:
    prefix = "HK$" if currency == "HKD" else "¥"
    return f"{prefix}{value:,.2f}"


def pct(value: float) -> str:
    return f"{value:+.2f}%"


def normalize_code(raw: str) -> str | None:
    s = (raw or "").strip().lower()
    s = re.sub(r"\s+", "", s)
    if not s:
        return None
    if re.fullmatch(r"hk\d{5}", s):
        return s
    if re.fullmatch(r"\d{5}", s):
        return "hk" + s
    if re.fullmatch(r"(sh|sz|bj)\d{6}", s):
        return s
    if re.fullmatch(r"\d{6}", s):
        if s.startswith(("6", "90", "5")):
            return "sh" + s
        if s.startswith(("0", "1", "2", "3")):
            return "sz" + s
        if s.startswith(("4", "8")):
            return "bj" + s
    return None


def market_name(code: str) -> str:
    if code.startswith("hk"):
        return "港股"
    if code.startswith("sh688"):
        return "科创板"
    if code.startswith("bj"):
        return "北交所"
    return "A 股"


def market_key(code: str) -> str:
    return "hk" if code.startswith("hk") else "cn"


def trading_time_error(code: str, when: dt.datetime | None = None) -> str | None:
    current = when or dt.datetime.now()
    key = market_key(code)
    calendar = load_trading_calendar()
    market_calendar = (calendar.get("markets") or {}).get(key) or {}
    date_text = current.date().isoformat()
    if date_text in set(market_calendar.get("closed_dates") or []):
        return f"{market_name(code)}今天休市，不能模拟买卖。"
    if current.weekday() >= 5:
        return f"{market_name(code)}周末休市，不能模拟买卖。"
    t = current.time()
    if code.startswith("hk"):
        if date_text in set(market_calendar.get("half_days") or []):
            sessions = ((dt.time(9, 30), dt.time(12, 0)),)
            label = "港股半日市交易时间为 09:30-12:00"
        else:
            sessions = (
                (dt.time(9, 30), dt.time(12, 0)),
                (dt.time(13, 0), dt.time(16, 0)),
            )
            label = "港股交易时间为 09:30-12:00、13:00-16:00"
    else:
        sessions = (
            (dt.time(9, 30), dt.time(11, 30)),
            (dt.time(13, 0), dt.time(15, 0)),
        )
        label = "A 股交易时间为 09:30-11:30、13:00-15:00"
    if any(start <= t <= end for start, end in sessions):
        return None
    return f"当前不在{market_name(code)}交易时间内，不能模拟买卖。{label}。"


def default_board_lot(code: str) -> int:
    if code.startswith("hk"):
        return DEFAULT_HK_BOARD_LOTS.get(code, 100)
    return 100


def buy_quantity_rule(code: str, board_lot: int) -> tuple[int, int, str]:
    if code.startswith("sh688"):
        return 200, 100, "科创板最低 200 股，之后按 100 股递增"
    if code.startswith("hk"):
        return board_lot, board_lot, f"港股按每手 {board_lot} 股买入"
    return board_lot, board_lot, f"{market_name(code)}按每手 {board_lot} 股买入"


@dataclass
class Quote:
    code: str
    name: str
    price: float
    change: float
    change_pct: float
    time_label: str
    source: str
    currency: str


class QuoteService:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})

    def fetch(self, codes: list[str]) -> dict[str, Quote]:
        requested = []
        for code in codes:
            norm = normalize_code(code)
            if norm and norm not in requested:
                requested.append(norm)
        if not requested:
            return {}

        quotes: dict[str, Quote] = {}
        self._fetch_hk_eastmoney([c for c in requested if c.startswith("hk")], quotes)
        missing = [c for c in requested if c not in quotes]
        self._fetch_sina(missing, quotes)
        return quotes

    def _fetch_hk_eastmoney(self, hk_codes: list[str], out: dict[str, Quote]) -> None:
        if not hk_codes:
            return
        try:
            secids = ",".join("116." + c[2:] for c in hk_codes)
            fields = "f12,f14,f2,f3,f4,f124"
            resp = self.session.get(
                "https://push2.eastmoney.com/api/qt/ulist.np/get",
                params={"fltt": "2", "secids": secids, "fields": fields},
                timeout=4,
            )
            payload = resp.json()
            for item in (((payload or {}).get("data") or {}).get("diff") or []):
                code = "hk" + str(item.get("f12", "")).zfill(5)
                price = self._to_float(item.get("f2"))
                if price <= 0:
                    continue
                ts = int(item.get("f124") or 0)
                time_label = dt.datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts > 0 else "-"
                out[code] = Quote(
                    code=code,
                    name=str(item.get("f14") or code),
                    price=price,
                    change=self._to_float(item.get("f4")),
                    change_pct=self._to_float(item.get("f3")),
                    time_label=time_label,
                    source="东方财富",
                    currency="HKD",
                )
        except Exception:
            return

    def _fetch_sina(self, codes: list[str], out: dict[str, Quote]) -> None:
        if not codes:
            return
        labels = ",".join("rt_" + c if c.startswith("hk") else c for c in codes)
        try:
            resp = self.session.get(
                "https://hq.sinajs.cn/list=" + labels,
                headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"},
                timeout=4,
            )
            resp.encoding = "gbk"
            for line in resp.text.splitlines():
                if '="' not in line:
                    continue
                code = line.split('="', 1)[0].split("_")[-1]
                if code.startswith("rt_"):
                    code = code[3:]
                parts = line.split('="', 1)[1].rstrip('";').split(",")
                if code.startswith("hk"):
                    quote = self._parse_sina_hk(code, parts)
                else:
                    quote = self._parse_sina_cn(code, parts)
                if quote and quote.price > 0:
                    out[quote.code] = quote
        except Exception:
            return

    def _parse_sina_hk(self, code: str, parts: list[str]) -> Quote | None:
        if len(parts) < 19:
            return None
        name = parts[1] or parts[0] or code
        price = self._to_float(parts[6]) or self._to_float(parts[3])
        prev = self._to_float(parts[3])
        change = self._to_float(parts[7])
        change_pct = self._to_float(parts[8])
        if change == 0 and price and prev:
            change = price - prev
        if change_pct == 0 and price and prev:
            change_pct = (price / prev - 1) * 100
        return Quote(code, name, price, change, change_pct, parts[18] or "-", "新浪HK", "HKD")

    def _parse_sina_cn(self, code: str, parts: list[str]) -> Quote | None:
        if len(parts) < 32:
            return None
        name = parts[0] or code
        price = self._to_float(parts[3]) or self._to_float(parts[2])
        prev = self._to_float(parts[2])
        change = price - prev if price and prev else 0.0
        change_pct = (price / prev - 1) * 100 if price and prev else 0.0
        return Quote(code, name, price, change, change_pct, parts[31] or "-", "新浪", "CNY")

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            if value in (None, "", "-"):
                return 0.0
            return float(value)
        except Exception:
            return 0.0


class PortfolioStore:
    def __init__(self) -> None:
        self.data = self._default()
        self.load()

    def _default(self) -> dict[str, Any]:
        return {
            "version": APP_VERSION,
            "cash": 500000.0,
            "initial_cash": 500000.0,
            "watchlist": ["sh000001", "hk01810"],
            "refresh_seconds": 3,
            "board_lots": DEFAULT_HK_BOARD_LOTS.copy(),
            "lots": [],
            "trades": [],
            "pending_orders": [],
            "position_history": [],
            "ai": {
                "api_base": "https://api.openai.com/v1",
                "api_key": "",
                "model": "gpt-4.1-mini",
                "auto_execute": False,
            },
        }

    def load(self) -> None:
        self.data = load_json(CONFIG_FILE, self._default())
        for key, value in self._default().items():
            self.data.setdefault(key, value)

    def save(self) -> None:
        self.data["version"] = APP_VERSION
        save_json(CONFIG_FILE, self.data)

    @property
    def refresh_seconds(self) -> int:
        try:
            seconds = int(self.data.get("refresh_seconds") or 3)
        except Exception:
            seconds = 3
        if seconds not in REFRESH_INTERVAL_OPTIONS:
            seconds = 3
        return seconds

    def set_refresh_seconds(self, seconds: int) -> None:
        if seconds not in REFRESH_INTERVAL_OPTIONS:
            seconds = 3
        self.data["refresh_seconds"] = seconds
        self.save()

    @property
    def cash(self) -> float:
        return float(self.data.get("cash", 0.0))

    def set_cash(self, value: float) -> None:
        self.data["cash"] = round(float(value), 2)

    @property
    def watchlist(self) -> list[str]:
        return list(self.data.get("watchlist") or [])

    def add_watch(self, code: str) -> bool:
        norm = normalize_code(code)
        if not norm:
            return False
        items = self.watchlist
        if norm not in items:
            items.append(norm)
            self.data["watchlist"] = items
            self.save()
        return True

    def remove_watch(self, code: str) -> None:
        self.data["watchlist"] = [c for c in self.watchlist if c != code]
        self.save()

    def board_lot(self, code: str) -> int:
        if not code.startswith("hk"):
            return 100
        lots = self.data.setdefault("board_lots", {})
        try:
            value = int(lots.get(code) or 0)
        except Exception:
            value = 0
        if value <= 0:
            value = default_board_lot(code)
            lots[code] = value
            self.save()
        return value

    def order_rule(self, code: str) -> tuple[int, int, str]:
        return buy_quantity_rule(code, self.board_lot(code))

    def validate_buy_quantity(self, code: str, qty: int) -> None:
        min_qty, step, label = self.order_rule(code)
        if qty < min_qty:
            raise ValueError(f"{label}；当前数量低于最低买入数量 {min_qty} 股")
        if step > 1 and qty % step != 0:
            raise ValueError(f"{label}；当前数量必须是 {step} 的整数倍")

    def validate_trade_quantity(self, code: str, qty: int) -> None:
        min_qty, step, label = self.order_rule(code)
        if qty < min_qty:
            raise ValueError(f"{label}；当前数量低于最低交易数量 {min_qty} 股")
        if step > 1 and qty % step != 0:
            raise ValueError(f"{label}；当前数量必须是 {step} 的整数倍")

    def reserved_cash(self) -> float:
        total = 0.0
        for order in self.active_pending_orders():
            if str(order.get("action") or "").upper() != "BUY":
                continue
            total += float(order.get("limit_price") or 0) * int(order.get("qty") or 0)
        return round(total, 2)

    def available_cash(self) -> float:
        return max(0.0, round(self.cash - self.reserved_cash(), 2))

    def reserved_sell_qty(self, code: str) -> int:
        total = 0
        for order in self.active_pending_orders():
            if str(order.get("action") or "").upper() != "SELL":
                continue
            if str(order.get("code") or "") == code:
                total += int(order.get("qty") or 0)
        return total

    def available_sell_qty(self, code: str) -> int:
        pos = self.positions().get(code) or {}
        return max(0, int(pos.get("available") or 0) - self.reserved_sell_qty(code))

    def reset(self, initial_cash: float) -> None:
        self.data["cash"] = round(float(initial_cash), 2)
        self.data["initial_cash"] = round(float(initial_cash), 2)
        self.data["lots"] = []
        self.data["trades"] = []
        self.data["pending_orders"] = []
        self.data["position_history"] = []
        self.save()

    def add_pending_order(self, action: str, quote: Quote, qty: int, limit_price: float, operator: str, reason: str = "") -> dict[str, Any]:
        action_name = action.upper()
        qty = int(qty)
        limit_price = float(limit_price)
        if action_name == "BUY":
            self.validate_buy_quantity(quote.code, qty)
            required = round(limit_price * qty, 2)
            available = self.available_cash()
            if required > available + 1e-6:
                raise ValueError(f"可用资金不足；该买入委托需冻结 {money(required, quote.currency)}，当前剩余可用资金 {money(available)}")
        elif action_name == "SELL":
            self.validate_trade_quantity(quote.code, qty)
            available_qty = self.available_sell_qty(quote.code)
            if qty > available_qty:
                raise ValueError(f"可卖数量不足；当前剩余可卖 {available_qty} 股")
        order = {
            "id": now_str() + f"-{len(self.data.get('pending_orders') or []):04d}",
            "created_at": now_str(),
            "operator": operator,
            "action": action_name,
            "code": quote.code,
            "name": quote.name,
            "qty": qty,
            "limit_price": round(limit_price, 4),
            "last_price": round(float(quote.price), 4),
            "currency": quote.currency,
            "status": "ACTIVE",
            "reason": reason,
        }
        self.data.setdefault("pending_orders", []).append(order)
        self.save()
        return order

    def active_pending_orders(self) -> list[dict[str, Any]]:
        return [o for o in self.data.get("pending_orders") or [] if o.get("status") == "ACTIVE"]

    def cancel_pending_order(self, order_id: str) -> bool:
        for order in self.data.get("pending_orders") or []:
            if order.get("id") == order_id and order.get("status") == "ACTIVE":
                order["status"] = "CANCELLED"
                order["cancelled_at"] = now_str()
                self.save()
                return True
        return False

    def buy(self, quote: Quote, qty: int, operator: str = "用户", reason: str = "") -> dict[str, Any]:
        if qty <= 0:
            raise ValueError("数量必须大于 0")
        self.validate_buy_quantity(quote.code, qty)
        cost = quote.price * qty
        if cost > self.cash + 1e-6:
            raise ValueError("可用资金不足")
        self.set_cash(self.cash - cost)
        self.data.setdefault("lots", []).append(
            {
                "code": quote.code,
                "name": quote.name,
                "qty": int(qty),
                "buy_price": quote.price,
                "actual_price": quote.price,
                "breakeven_price": quote.price,
                "buy_date": today_str(),
                "buy_time": now_str(),
                "currency": quote.currency,
            }
        )
        trade = {
            "time": now_str(),
            "operator": operator,
            "action": "BUY",
            "code": quote.code,
            "name": quote.name,
            "qty": int(qty),
            "price": quote.price,
            "amount": cost,
            "profit": 0.0,
            "reason": reason,
        }
        self.data.setdefault("trades", []).append(trade)
        self.save()
        return trade

    def sell(self, quote: Quote, qty: int, operator: str = "用户", reason: str = "") -> dict[str, Any]:
        if qty <= 0:
            raise ValueError("数量必须大于 0")
        remaining = qty
        proceeds = 0.0
        profit = 0.0
        for lot in self.data.get("lots", []):
            if remaining <= 0:
                break
            if lot.get("code") != quote.code:
                continue
            if str(lot.get("buy_date", today_str())) >= today_str():
                continue
            available = int(lot.get("qty") or 0)
            if available <= 0:
                continue
            use_qty = min(available, remaining)
            lot["qty"] = available - use_qty
            remaining -= use_qty
            proceeds += quote.price * use_qty
            breakeven_price = float(lot.get("breakeven_price") or lot.get("buy_price") or 0)
            profit += (quote.price - breakeven_price) * use_qty
        if remaining > 0:
            raise ValueError("可卖数量不足；同日买入的股票按 T+1 规则不可卖出")
        self.data["lots"] = [lot for lot in self.data.get("lots", []) if int(lot.get("qty") or 0) > 0]
        self.set_cash(self.cash + proceeds)
        trade = {
            "time": now_str(),
            "operator": operator,
            "action": "SELL",
            "code": quote.code,
            "name": quote.name,
            "qty": int(qty),
            "price": quote.price,
            "amount": proceeds,
            "profit": profit,
            "reason": reason,
        }
        self.data.setdefault("trades", []).append(trade)
        self.save()
        return trade

    def positions(self) -> dict[str, dict[str, Any]]:
        pos: dict[str, dict[str, Any]] = {}
        for lot in self.data.get("lots", []):
            code = lot.get("code")
            qty = int(lot.get("qty") or 0)
            if not code or qty <= 0:
                continue
            item = pos.setdefault(
                code,
                {
                    "code": code,
                    "name": lot.get("name") or code,
                    "qty": 0,
                    "available": 0,
                    "cost_amount": 0.0,
                    "actual_cost_amount": 0.0,
                    "actual_cost_complete": True,
                    "currency": lot.get("currency") or "CNY",
                },
            )
            item["qty"] += qty
            breakeven_price = float(lot.get("breakeven_price") or lot.get("buy_price") or 0)
            item["cost_amount"] += breakeven_price * qty
            actual_price = lot.get("actual_price")
            if actual_price in (None, ""):
                item["actual_cost_complete"] = False
            else:
                item["actual_cost_amount"] += float(actual_price) * qty
            if str(lot.get("buy_date", today_str())) < today_str():
                item["available"] += qty
        for item in pos.values():
            item["avg_cost"] = item["cost_amount"] / item["qty"] if item["qty"] else 0.0
            item["breakeven_cost"] = item["avg_cost"]
            if item.get("actual_cost_complete"):
                item["actual_avg_cost"] = item["actual_cost_amount"] / item["qty"] if item["qty"] else 0.0
            else:
                item["actual_avg_cost"] = None
        return pos

    def record_position_history(self, rows: list[dict[str, Any]]) -> None:
        history = list(self.data.get("position_history") or [])
        by_key = {(str(item.get("date")), str(item.get("code"))): item for item in history}
        changed = False
        for row in rows:
            key = (str(row.get("date")), str(row.get("code")))
            old = by_key.get(key)
            if old != row:
                by_key[key] = row
                changed = True
        if changed:
            merged = sorted(by_key.values(), key=lambda x: (str(x.get("date")), str(x.get("code"))))
            self.data["position_history"] = merged[-1000:]
            self.save()


class InitialCapitalDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("重置模拟账户")
        layout = QVBoxLayout(self)
        self.combo = QComboBox()
        self.combo.addItems(["50 万", "100 万", "自定义"])
        self.custom = QDoubleSpinBox()
        self.custom.setRange(1000, 100000000)
        self.custom.setDecimals(2)
        self.custom.setSingleStep(10000)
        self.custom.setValue(500000)
        form = QFormLayout()
        form.addRow("初始资金", self.combo)
        form.addRow("自定义金额", self.custom)
        layout.addLayout(form)
        hint = QLabel("重置会清空当前持仓和交易记录。")
        hint.setStyleSheet("color: #8a5a00;")
        layout.addWidget(hint)
        buttons = QHBoxLayout()
        ok = QPushButton("确认重置")
        cancel = QPushButton("取消")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def value(self) -> float:
        text = self.combo.currentText()
        if text.startswith("50"):
            return 500000.0
        if text.startswith("100"):
            return 1000000.0
        return float(self.custom.value())


class LimitOrderDialog(QDialog):
    def __init__(self, action: str, quote: Quote, qty: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("限价委托")
        action_text = "买入" if action.lower() == "buy" else "卖出"
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("方向", QLabel(action_text))
        form.addRow("代码", QLabel(quote.code))
        form.addRow("名称", QLabel(quote.name))
        form.addRow("数量", QLabel(str(qty)))
        form.addRow("现价", QLabel(f"{quote.price:.3f}"))
        self.price_spin = QDoubleSpinBox()
        self.price_spin.setRange(0.001, 1000000)
        self.price_spin.setDecimals(3)
        self.price_spin.setSingleStep(0.01)
        self.price_spin.setValue(float(quote.price))
        form.addRow("委托价", self.price_spin)
        layout.addLayout(form)
        hint_text = "买入：实时价小于等于委托价时成交。" if action.lower() == "buy" else "卖出：实时价大于等于委托价时成交。"
        hint = QLabel(hint_text)
        hint.setStyleSheet("color: #666;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QHBoxLayout()
        ok = QPushButton("提交委托")
        cancel = QPushButton("取消")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def limit_price(self) -> float:
        return float(self.price_spin.value())


class MainSettingsDialog(LegacyStockWidget.SettingsDialog):
    def __init__(self, owner: "MainWindow", compact: "LegacyCompactWindow") -> None:
        self.owner = owner
        super().__init__(compact, owner, app=owner)
        self.setWindowTitle("设置")

        if self.tabs.count() > 0:
            self.tabs.removeTab(0)
        self._remove_legacy_interval_group()
        self._move_general_tab_first()
        self._insert_refresh_group_into_general()
        self._rename_global_hotkey_label()

        self.tabs.setTabText(0, "常规")
        self.tabs.setTabText(1, "盯盘显示")
        self.tabs.setTabText(2, "盯盘外观")
        self.tab_sizes = {
            0: QSize(520, 430),
            1: QSize(500, 450),
            2: QSize(420, 390),
        }
        self.tabs.setCurrentIndex(0)
        self._apply_tab_size(0)

    def _remove_legacy_interval_group(self) -> None:
        try:
            self.cmb_interval.currentIndexChanged.disconnect()
        except Exception:
            pass
        interval_group = self.cmb_interval.parentWidget()
        if interval_group is None:
            return
        parent_widget = interval_group.parentWidget()
        parent_layout = parent_widget.layout() if parent_widget is not None else None
        if parent_layout is not None:
            parent_layout.removeWidget(interval_group)
        interval_group.hide()
        interval_group.setParent(None)
        interval_group.deleteLater()

    def _move_general_tab_first(self) -> None:
        if self.tabs.count() < 3:
            return
        general_tab = self.tabs.widget(2)
        self.tabs.removeTab(2)
        self.tabs.insertTab(0, general_tab, "常规")

    def _insert_refresh_group_into_general(self) -> None:
        general_tab = self.tabs.widget(0)
        layout = general_tab.layout() if general_tab is not None else None
        if layout is None:
            return
        refresh_box = QGroupBox("行情刷新")
        refresh_layout = QVBoxLayout(refresh_box)
        refresh_layout.setContentsMargins(10, 14, 10, 10)
        row = QHBoxLayout()
        self.global_interval_combo = QComboBox()
        self.global_interval_combo.setFixedWidth(140)
        for seconds in REFRESH_INTERVAL_OPTIONS:
            self.global_interval_combo.addItem(f"{seconds} 秒", userData=seconds)
        idx = self.global_interval_combo.findData(self.owner.store.refresh_seconds)
        self.global_interval_combo.setCurrentIndex(idx if idx >= 0 else 2)
        self.global_interval_combo.currentIndexChanged.connect(self._on_global_interval_changed)
        row.addWidget(QLabel("自动刷新间隔："))
        row.addWidget(self.global_interval_combo)
        row.addStretch(1)
        refresh_layout.addLayout(row)
        hint = QLabel("“立即刷新行情”只会手动拉取一次最新行情；自动刷新按这里的间隔持续运行。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666;")
        refresh_layout.addWidget(hint)
        layout.insertWidget(1, refresh_box)

    def _rename_global_hotkey_label(self) -> None:
        for label in self.findChildren(QLabel):
            if label.text() == "隐藏/显示浮窗：":
                label.setText("显示/隐藏当前界面：")
                break

    def _on_global_interval_changed(self, _idx: int) -> None:
        seconds = self.global_interval_combo.currentData()
        if isinstance(seconds, int):
            self.owner.set_refresh_interval(seconds)


class LegacyCompactWindow(LegacyStockWidget.FloatLabel):
    def __init__(self, owner: "MainWindow", cfg: dict[str, Any]) -> None:
        self.owner = owner
        super().__init__(cfg)
        try:
            self.hotkey_triggered.disconnect(self.toggle_win)
        except Exception:
            pass
        self.hotkey_triggered.connect(self.owner.toggle_active_panel_visibility)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        back = QAction("返回主界面", menu)
        back.triggered.connect(self.owner.exit_compact_mode)
        menu.addAction(back)
        menu.addSeparator()

        sub_cols = QMenu("显示指标", menu)
        for name in self.ALL_HEADERS:
            if name == "卖一":
                continue
            if name == "买一":
                act = QAction("买一/卖一", sub_cols, checkable=True)
                act.setChecked(self.header_is_visible("买一"))
                act.toggled.connect(lambda checked, n="买一": self.set_flag(n, checked))
                sub_cols.addAction(act)
                continue
            act = QAction(name, sub_cols, checkable=True)
            act.setChecked(self.header_is_visible(name))
            act.toggled.connect(lambda checked, n=name: self.set_flag(n, checked))
            sub_cols.addAction(act)
        menu.addMenu(sub_cols)

        act_header = QAction("显示表头", menu, checkable=True)
        act_header.setChecked(self.header_visible)
        act_header.toggled.connect(self.set_header_visible)
        menu.addAction(act_header)

        act_grid = QAction("显示网格", menu, checkable=True)
        act_grid.setChecked(self.grid_visible)
        act_grid.toggled.connect(self.set_grid_visible)
        menu.addAction(act_grid)

        act_color = QAction("默认红涨绿跌", menu, checkable=True)
        act_color.setChecked(self.default_color)
        act_color.toggled.connect(self.set_default_color)
        menu.addAction(act_color)

        menu.addSeparator()
        settings = QAction("设置...", menu)
        settings.triggered.connect(self.owner.open_main_settings)
        menu.addAction(settings)

        menu.addSeparator()
        quit_action = QAction("退出软件", menu)
        quit_action.triggered.connect(self.owner.quit_app)
        menu.addAction(quit_action)
        menu.exec(event.globalPos())

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if getattr(self.owner, "_compact_mode_active", False) and not getattr(self.owner, "_closing", False):
            self.owner.show_main_after_compact_hidden()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"StockTradingSim 模拟炒股 {APP_VERSION}")
        self.setMinimumSize(760, 520)
        self.store = PortfolioStore()
        self.quotes = QuoteService()
        self.quote_cache: dict[str, Quote] = {}
        self.compact_window: LegacyCompactWindow | None = None
        self._settings_dialog = None
        self._compact_mode_active = False
        self._suppress_compact_restore = False
        self._tray_menu_open = False
        self._compact_timer_was_active = False
        self._compact_top_timer_was_active = False
        self._closing = False
        self._app_icon_choice = load_compact_config().get("app_icon")

        self._build_ui()
        self._build_tray()
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown_compact)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.refresh_quotes(auto=True))
        self.timer.start(self.store.refresh_seconds * 1000)
        self.refresh_quotes(auto=True)
        QTimer.singleShot(800, self.preload_compact_window)

    def _build_ui(self) -> None:
        root = QWidget()
        main = QVBoxLayout(root)
        self.status = QLabel("")
        self.status.setStyleSheet("font-size: 13px; color: #555;")
        main.addWidget(self._account_panel())

        tabs = QTabWidget()
        tabs.addTab(self._market_tab(), "行情与下单")
        tabs.addTab(self._position_tab(), "持仓")
        tabs.addTab(self._position_analysis_tab(), "持仓分析")
        tabs.addTab(self._trade_tab(), "交易记录")
        tabs.addTab(self._ai_tab(), "AI 接入")
        main.addWidget(tabs, 1)
        main.addWidget(self.status)
        self.setCentralWidget(root)

        self._style()

    def _account_panel(self) -> QWidget:
        box = QGroupBox("模拟账户")
        layout = QGridLayout(box)
        self.cash_label = QLabel()
        self.equity_label = QLabel()
        self.profit_label = QLabel()
        self.date_label = QLabel()
        reset = QPushButton("设置初始资金")
        settings = QPushButton("设置")
        refresh = QPushButton("立即刷新行情")
        compact = QPushButton("盯盘模式")
        reset.clicked.connect(self.reset_account)
        settings.clicked.connect(self.open_main_settings)
        refresh.clicked.connect(lambda: self.refresh_quotes(auto=False))
        compact.clicked.connect(self.enter_compact_mode)
        layout.addWidget(QLabel("可用资金"), 0, 0)
        layout.addWidget(self.cash_label, 0, 1)
        layout.addWidget(QLabel("总资产"), 0, 2)
        layout.addWidget(self.equity_label, 0, 3)
        layout.addWidget(QLabel("累计收益"), 0, 4)
        layout.addWidget(self.profit_label, 0, 5)
        layout.addWidget(QLabel("交易日"), 1, 0)
        layout.addWidget(self.date_label, 1, 1)
        layout.addWidget(settings, 1, 2)
        layout.addWidget(reset, 1, 3)
        layout.addWidget(refresh, 1, 4)
        layout.addWidget(compact, 1, 5)
        return box

    def _market_tab(self) -> QWidget:
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        tab.setWidget(content)
        controls = QHBoxLayout()
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("输入代码：600000 / sh688270 / hk01810")
        add_btn = QPushButton("加入自选")
        remove_btn = QPushButton("移除选中")
        add_btn.clicked.connect(self.add_watch)
        remove_btn.clicked.connect(self.remove_selected_watch)
        controls.addWidget(self.code_input, 1)
        controls.addWidget(add_btn)
        controls.addWidget(remove_btn)
        layout.addLayout(controls)

        self.market_table = QTableWidget(0, 8)
        self.market_table.setHorizontalHeaderLabels(["代码", "名称", "最新价", "涨跌幅", "时间", "来源", "币种", "每手"])
        self.market_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.market_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.market_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.market_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.market_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.market_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.market_table.itemSelectionChanged.connect(self.update_order_rule)
        self.market_table.verticalHeader().setDefaultSectionSize(34)
        self.market_table.setMinimumHeight(34 * 5 + self.market_table.horizontalHeader().height() + 18)
        layout.addWidget(self.market_table, 3)

        order_box = QGroupBox("虚拟下单")
        order = QHBoxLayout(order_box)
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 100000000)
        self.qty_spin.setSingleStep(100)
        self.qty_spin.setValue(100)
        self.order_rule_label = QLabel("选择股票后显示交易数量规则")
        buy_btn = QPushButton("买入")
        sell_btn = QPushButton("卖出")
        buy_btn.clicked.connect(lambda: self.place_order("buy"))
        sell_btn.clicked.connect(lambda: self.place_order("sell"))
        order.addWidget(QLabel("数量"))
        order.addWidget(self.qty_spin)
        order.addWidget(buy_btn)
        order.addWidget(sell_btn)
        order.addWidget(self.order_rule_label)
        order.addStretch(1)
        layout.addWidget(order_box)

        pending_box = QGroupBox("未成交委托")
        pending_layout = QVBoxLayout(pending_box)
        pending_controls = QHBoxLayout()
        cancel_pending = QPushButton("取消选中委托")
        cancel_pending.clicked.connect(self.cancel_selected_pending_order)
        pending_controls.addStretch(1)
        pending_controls.addWidget(cancel_pending)
        pending_layout.addLayout(pending_controls)
        self.pending_table = QTableWidget(0, 9)
        self.pending_table.setHorizontalHeaderLabels(
            ["提交时间", "方向", "代码", "名称", "数量", "委托价", "现价", "状态", "触发条件"]
        )
        self.pending_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.pending_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.pending_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.pending_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.pending_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.pending_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        pending_layout.addWidget(self.pending_table)
        pending_box.setMinimumHeight(150)
        layout.addWidget(pending_box, 1)
        return tab

    def _position_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        controls = QHBoxLayout()
        self.position_qty_spin = QSpinBox()
        self.position_qty_spin.setRange(1, 100000000)
        self.position_qty_spin.setSingleStep(100)
        self.position_qty_spin.setValue(100)
        add_btn = QPushButton("加仓")
        reduce_btn = QPushButton("减仓")
        close_btn = QPushButton("清仓可卖")
        add_btn.clicked.connect(lambda: self.place_position_order("buy"))
        reduce_btn.clicked.connect(lambda: self.place_position_order("sell"))
        close_btn.clicked.connect(self.close_selected_position)
        controls.addWidget(QLabel("数量"))
        controls.addWidget(self.position_qty_spin)
        controls.addWidget(add_btn)
        controls.addWidget(reduce_btn)
        controls.addWidget(close_btn)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.position_table = QTableWidget(0, 10)
        self.position_table.setHorizontalHeaderLabels(
            ["代码", "名称", "持仓", "可卖", "交易均价", "回本价", "现价", "市值", "回本盈亏", "回本率"]
        )
        self.position_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.position_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.position_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.position_table.itemSelectionChanged.connect(self.update_position_order_rule)
        layout.addWidget(self.position_table)
        return tab

    def _position_analysis_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.position_summary_label = QLabel("")
        self.position_summary_label.setStyleSheet("font-size: 13px; color: #555;")
        layout.addWidget(self.position_summary_label)

        analysis_box = QGroupBox("当前持仓复盘")
        analysis_layout = QVBoxLayout(analysis_box)
        self.position_analysis_table = QTableWidget(0, 13)
        self.position_analysis_table.setHorizontalHeaderLabels(
            ["代码", "名称", "持仓天数", "持仓", "交易均价", "回本价", "现价", "回本盈亏", "已实现", "总收益", "回本率", "买入次数", "卖出次数"]
        )
        self.position_analysis_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.position_analysis_table.setEditTriggers(QTableWidget.NoEditTriggers)
        analysis_layout.addWidget(self.position_analysis_table)
        layout.addWidget(analysis_box, 1)

        history_box = QGroupBox("每日持仓快照")
        history_layout = QVBoxLayout(history_box)
        self.position_history_table = QTableWidget(0, 11)
        self.position_history_table.setHorizontalHeaderLabels(
            ["日期", "时间", "代码", "名称", "持仓", "交易均价", "回本价", "现价", "市值", "回本盈亏", "回本率"]
        )
        self.position_history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.position_history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        history_layout.addWidget(self.position_history_table)
        layout.addWidget(history_box, 1)
        return tab

    def _trade_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.trade_table = QTableWidget(0, 9)
        self.trade_table.setHorizontalHeaderLabels(
            ["时间", "操作者", "方向", "代码", "名称", "数量", "价格", "金额", "收益/原因"]
        )
        self.trade_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.trade_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.trade_table)
        return tab

    def _ai_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form_box = QGroupBox("OpenAI-compatible API")
        form = QFormLayout(form_box)
        ai = self.store.data.get("ai") or {}
        self.ai_base = QLineEdit(ai.get("api_base") or "https://api.openai.com/v1")
        self.ai_key = QLineEdit(ai.get("api_key") or "")
        self.ai_key.setEchoMode(QLineEdit.Password)
        self.ai_model = QLineEdit(ai.get("model") or "gpt-4.1-mini")
        self.ai_auto = QCheckBox("允许 AI 建议确认后自动执行")
        self.ai_auto.setChecked(bool(ai.get("auto_execute")))
        form.addRow("API Base", self.ai_base)
        form.addRow("API Key", self.ai_key)
        form.addRow("模型", self.ai_model)
        form.addRow("", self.ai_auto)
        layout.addWidget(form_box)

        buttons = QHBoxLayout()
        save_ai = QPushButton("保存 AI 配置")
        ask_ai = QPushButton("让 AI 给出操作建议")
        execute_ai = QPushButton("执行下方 JSON 指令")
        load_codex = QPushButton("加载 Codex 本地指令")
        save_ai.clicked.connect(self.save_ai_config)
        ask_ai.clicked.connect(self.ask_ai)
        execute_ai.clicked.connect(lambda: self.execute_ai_orders(self.ai_output.toPlainText(), "AI"))
        load_codex.clicked.connect(self.load_codex_orders)
        buttons.addWidget(save_ai)
        buttons.addWidget(ask_ai)
        buttons.addWidget(execute_ai)
        buttons.addWidget(load_codex)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.ai_output = QPlainTextEdit()
        self.ai_output.setPlaceholderText(
            'AI/Codex 指令 JSON 示例：\n'
            '[{"action":"buy","code":"hk01810","qty":200,"limit_price":28.0,"reason":"回调到目标价后模拟买入"}]\n\n'
            f"Codex 本地指令文件：{CODEX_ORDER_FILE}"
        )
        layout.addWidget(self.ai_output, 1)
        return tab

    def _build_tray(self) -> None:
        icon = self.resolve_app_icon(getattr(self, "_app_icon_choice", None))
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        menu = self.menuBar().addMenu("程序")
        self.tray_menu = QMenu(self)

        self.action_show_main = QAction("显示主界面", self)
        self.action_compact = QAction("进入盯盘模式", self)
        self.action_settings = QAction("设置...", self)
        self.action_refresh = QAction("立即刷新行情", self)
        self.action_quit = QAction("退出", self)
        self.action_show_main.triggered.connect(self.show_main_window)
        self.action_compact.triggered.connect(self.show_compact_window)
        self.action_settings.triggered.connect(self.open_main_settings)
        self.action_refresh.triggered.connect(lambda: self.refresh_quotes(auto=False))
        self.action_quit.triggered.connect(self.quit_app)

        menu.addAction(self.action_show_main)
        menu.addAction(self.action_compact)
        menu.addAction(self.action_settings)
        menu.addAction(self.action_refresh)
        menu.addSeparator()
        menu.addAction(self.action_quit)

        self.tray_menu.addAction(self.action_show_main)
        self.tray_menu.addAction(self.action_compact)
        self.tray_menu.addAction(self.action_settings)
        self.tray_menu.addAction(self.action_refresh)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(self.action_quit)

        self.tray.activated.connect(self.on_tray_activated)
        self.tray_menu.aboutToShow.connect(self.prepare_tray_menu)
        self.tray_menu.aboutToHide.connect(self.resume_compact_timers_after_menu)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.show()
        self.update_tray_actions()

    def _style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background: #f7f8fa; }
            QGroupBox { font-weight: 600; border: 1px solid #d6dae0; border-radius: 6px; margin-top: 12px; padding: 10px; background: #ffffff; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QTableWidget { background: #ffffff; border: 1px solid #d6dae0; gridline-color: #edf0f3; }
            QPushButton { padding: 6px 12px; border: 1px solid #b8c0cc; border-radius: 5px; background: #ffffff; }
            QPushButton:hover { background: #f0f4f8; }
            QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QComboBox { padding: 5px; border: 1px solid #b8c0cc; border-radius: 4px; background: #ffffff; }
            """
        )

    def compact_is_visible(self) -> bool:
        return self.compact_window is not None and self.compact_window.isVisible()

    def any_panel_visible(self) -> bool:
        return self.isVisible() or self.compact_is_visible()

    def update_tray_actions(self) -> None:
        if not hasattr(self, "action_show_main"):
            return
        self.action_show_main.setText("显示主界面")
        self.action_show_main.setEnabled(True)
        self.action_compact.setText("进入盯盘模式")
        self.action_compact.setEnabled(True)

    def resolve_app_icon(self, choice) -> QIcon:
        if not choice or choice == "default":
            path = resource_path(ICON_FILE)
            if os.path.exists(path):
                return QIcon(path)
            return self.style().standardIcon(QStyle.SP_ComputerIcon)
        if isinstance(choice, str) and choice.startswith("std:"):
            key = choice.split(":", 1)[1]
            mapping = {
                "computer": QStyle.SP_ComputerIcon,
                "network": QStyle.SP_DriveNetIcon,
                "folder": QStyle.SP_DirIcon,
                "file": QStyle.SP_FileIcon,
                "trash": QStyle.SP_TrashIcon,
                "desktop": QStyle.SP_DesktopIcon,
            }
            return self.style().standardIcon(mapping.get(key, QStyle.SP_ComputerIcon))
        try:
            if os.path.exists(choice):
                return QIcon(choice)
        except Exception:
            pass
        return self.style().standardIcon(QStyle.SP_ComputerIcon)

    def set_app_icon(self, choice) -> None:
        self._app_icon_choice = choice
        icon = self.resolve_app_icon(choice)
        app = QApplication.instance()
        if app is not None:
            app.setWindowIcon(icon)
        self.setWindowIcon(icon)
        if self.compact_window is not None:
            self.compact_window.setWindowIcon(icon)
        if hasattr(self, "tray") and self.tray is not None:
            self.tray.setIcon(icon)

    def set_start_on_boot(self, enabled: bool) -> None:
        try:
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            name = APP_NAME
            if enabled:
                if getattr(sys, "frozen", False):
                    cmd = f'"{sys.executable}"'
                else:
                    cmd = f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}"'
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                        winreg.DeleteValue(key, name)
                except OSError:
                    pass
        except Exception:
            pass

    def save_now(self) -> None:
        self.save_compact_config(refresh_quotes=False)

    def open_main_settings(self) -> None:
        self.ensure_compact_window()
        if self._settings_dialog is not None and self._settings_dialog.isVisible():
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        self._settings_dialog = MainSettingsDialog(self, self.compact_window)
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    def set_refresh_interval(self, seconds: int) -> None:
        self.store.set_refresh_seconds(seconds)
        self.timer.setInterval(seconds * 1000)
        if self.compact_window is not None:
            self.compact_window.set_refresh_interval(seconds)
        self.status.setText(f"自动刷新间隔已设置为 {seconds} 秒")

    def prepare_tray_menu(self) -> None:
        self.pause_compact_timers_for_menu()
        self.update_tray_actions()

    def pause_compact_timers_for_menu(self) -> None:
        self._tray_menu_open = True
        self._compact_timer_was_active = False
        self._compact_top_timer_was_active = False
        if self.compact_window is None:
            return
        try:
            self._compact_timer_was_active = bool(self.compact_window.timer and self.compact_window.timer.isActive())
            self._compact_top_timer_was_active = bool(self.compact_window._keep_top_timer and self.compact_window._keep_top_timer.isActive())
            if self._compact_timer_was_active:
                self.compact_window.timer.stop()
            if self._compact_top_timer_was_active:
                self.compact_window._keep_top_timer.stop()
        except Exception:
            pass

    def resume_compact_timers_after_menu(self) -> None:
        self._tray_menu_open = False
        if self._closing or self.compact_window is None or not self.compact_window.isVisible():
            return
        try:
            if self._compact_timer_was_active and self.compact_window.timer and not self.compact_window.timer.isActive():
                self.compact_window.timer.start()
            if self._compact_top_timer_was_active and self.compact_window._keep_top_timer and not self.compact_window._keep_top_timer.isActive():
                self.compact_window._keep_top_timer.start()
        except Exception:
            pass

    def on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.toggle_active_panel_visibility()

    def toggle_active_panel_visibility(self) -> None:
        if self._compact_mode_active:
            self.toggle_compact_panel_visibility()
        else:
            self.toggle_main_panel_visibility()

    def toggle_main_panel_visibility(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show_main_window()
        self.update_tray_actions()

    def toggle_compact_panel_visibility(self) -> None:
        if not self._compact_mode_active:
            return
        self.ensure_compact_window()
        if self.compact_window.isVisible():
            self._suppress_compact_restore = True
            self.compact_window.hide()
            self._suppress_compact_restore = False
        else:
            self.sync_compact_watchlist(show_all=True)
            self.compact_window.show()
            self.compact_window.raise_()
            self.hide()
        self.update_tray_actions()

    def show_main_window(self) -> None:
        self._compact_mode_active = False
        if self.compact_window is not None:
            self.compact_window.hide()
        self.show()
        self.raise_()
        self.activateWindow()
        self.update_tray_actions()

    def show_compact_window(self) -> None:
        self.enter_compact_mode()

    def selected_market_code(self) -> str | None:
        row = self.market_table.currentRow()
        if row < 0:
            return None
        item = self.market_table.item(row, 0)
        return item.text() if item else None

    def selected_position_code(self) -> str | None:
        row = self.position_table.currentRow()
        if row < 0:
            return None
        item = self.position_table.item(row, 0)
        return item.text() if item else None

    def _apply_quantity_rule(self, code: str | None, spin: QSpinBox) -> str:
        norm = normalize_code(code or "")
        if not norm:
            spin.setMinimum(1)
            spin.setSingleStep(100)
            return "选择股票后显示交易数量规则"
        min_qty, step, label = self.store.order_rule(norm)
        spin.setMinimum(min_qty)
        spin.setSingleStep(step)
        if spin.value() < min_qty:
            spin.setValue(min_qty)
        elif step > 1 and spin.value() % step != 0:
            spin.setValue(((spin.value() // step) + 1) * step)
        return label

    def update_order_rule(self) -> None:
        label = self._apply_quantity_rule(self.selected_market_code(), self.qty_spin)
        self.order_rule_label.setText(label)

    def update_position_order_rule(self) -> None:
        self._apply_quantity_rule(self.selected_position_code(), self.position_qty_spin)

    def enter_compact_mode(self) -> None:
        created = self.ensure_compact_window()
        if not created:
            self.sync_compact_watchlist(show_all=True)
        self._compact_mode_active = True
        self.compact_window.show()
        self.compact_window.raise_()
        self.hide()
        self.update_tray_actions()

    def preload_compact_window(self) -> None:
        if self._closing or self.compact_window is not None:
            return
        try:
            self.ensure_compact_window()
            if self.compact_window is not None:
                self.compact_window.hide()
                self.compact_window.timer.stop()
                self.compact_window._keep_top_timer.stop()
        except Exception:
            pass

    def ensure_compact_window(self) -> bool:
        if self.compact_window is None:
            cfg = load_compact_config()
            cfg["codes"] = self.store.watchlist
            cfg["refresh_seconds"] = self.store.refresh_seconds
            cfg["checked_codes"] = [c for c in cfg.get("checked_codes", self.store.watchlist) if c in self.store.watchlist]
            if not cfg["checked_codes"]:
                cfg["checked_codes"] = self.store.watchlist
            cfg.setdefault("price_visible", True)
            cfg.setdefault("change_pct_visible", True)
            self.compact_window = LegacyCompactWindow(self, cfg)
            self.compact_window.set_on_change(self.save_compact_config)
            self.compact_window.set_open_settings_callback(self.open_main_settings)
            return True
        return False

    def sync_compact_watchlist(self, show_all: bool = False) -> None:
        if self.compact_window is None:
            return
        watchlist = self.store.watchlist
        checked = watchlist if show_all else [c for c in self.compact_window.checked_codes if c in watchlist]
        if not checked:
            checked = watchlist
        if list(self.compact_window.codes) != list(watchlist):
            self.compact_window.set_codes(watchlist)
        if list(self.compact_window.checked_codes) != list(checked):
            self.compact_window.set_checked_codes(checked)

    def exit_compact_mode(self) -> None:
        self._compact_mode_active = False
        if self.compact_window is not None:
            self.compact_window.hide()
        self.show()
        self.raise_()
        self.activateWindow()
        self.update_tray_actions()

    def show_main_after_compact_hidden(self) -> None:
        if self._closing:
            return
        if self._suppress_compact_restore:
            return
        self._compact_mode_active = False
        self.show()
        self.raise_()
        self.activateWindow()
        self.update_tray_actions()

    def save_compact_config(self, refresh_quotes: bool = True) -> None:
        if self.compact_window is None:
            return
        cfg = self.compact_window.current_config()
        cfg["refresh_seconds"] = self.store.refresh_seconds
        cfg["app_icon"] = getattr(self, "_app_icon_choice", None)
        save_compact_config_file(cfg)
        codes = [normalize_code(c) for c in cfg.get("codes", [])]
        self.store.data["watchlist"] = [c for c in codes if c]
        self.store.save()
        if refresh_quotes:
            self.refresh_quotes()
        self.update_tray_actions()

    def shutdown_compact(self) -> None:
        self._closing = True
        if self.compact_window is not None:
            try:
                self.compact_window.timer.stop()
                self.compact_window._keep_top_timer.stop()
            except Exception:
                pass
            self.compact_window.hide()

    def quit_app(self) -> None:
        self._closing = True
        try:
            self.timer.stop()
        except Exception:
            pass
        try:
            self.tray.hide()
        except Exception:
            pass
        try:
            if self._settings_dialog is not None:
                self._settings_dialog.close()
        except Exception:
            pass
        self.shutdown_compact()
        self.hide()
        app = QApplication.instance()
        if app is not None:
            app.exit(0)

    def add_watch(self) -> None:
        if not self.store.add_watch(self.code_input.text()):
            QMessageBox.warning(self, "代码无效", "请输入 A 股或港股代码，例如 600000、sh688270、hk01810。")
            return
        self.code_input.clear()
        self.sync_compact_watchlist(show_all=True)
        self.refresh_quotes()

    def remove_selected_watch(self) -> None:
        code = self.selected_market_code()
        if not code:
            return
        self.store.remove_watch(code)
        self.sync_compact_watchlist(show_all=True)
        self.refresh_quotes()

    def reset_account(self) -> None:
        dialog = InitialCapitalDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.store.reset(dialog.value())
            self.refresh_quotes()

    def refresh_quotes(self, auto: bool = False) -> None:
        pending_codes = [str(order.get("code") or "") for order in self.store.active_pending_orders()]
        codes = self.store.watchlist + list(self.store.positions().keys()) + pending_codes
        try:
            fetched = self.quotes.fetch(codes)
            self.quote_cache.update(fetched)
            executed = self.try_execute_pending_orders()
            mode = "自动刷新" if auto else "手动刷新"
            suffix = f"，成交 {executed} 笔委托" if executed else ""
            self.status.setText(f"{mode}：{now_str()}，返回 {len(fetched)} 个代码{suffix}")
        except Exception as exc:
            mode = "自动刷新" if auto else "手动刷新"
            self.status.setText(f"{mode}失败：{exc}")
        self.render_all()

    def render_all(self) -> None:
        self.render_account()
        self.render_market()
        self.render_positions()
        self.render_position_analysis()
        self.render_pending_orders()
        self.render_trades()

    def render_account(self) -> None:
        positions = self.store.positions()
        market_value = 0.0
        for code, item in positions.items():
            quote = self.quote_cache.get(code)
            if quote:
                market_value += quote.price * int(item["qty"])
            else:
                market_value += float(item["cost_amount"])
        equity = self.store.cash + market_value
        initial = float(self.store.data.get("initial_cash") or 0)
        gain = equity - initial
        gain_pct = gain / initial * 100 if initial else 0.0
        reserved = self.store.reserved_cash()
        cash_text = money(self.store.available_cash())
        if reserved:
            cash_text += f"（冻结 {money(reserved)}）"
        self.cash_label.setText(cash_text)
        self.cash_label.setToolTip(f"现金余额 {money(self.store.cash)}；买入委托冻结 {money(reserved)}")
        self.equity_label.setText(money(equity))
        self.profit_label.setText(f"{money(gain)} / {pct(gain_pct)}")
        self.profit_label.setStyleSheet("color: #d21f1f;" if gain > 0 else "color: #14934a;" if gain < 0 else "")
        self.date_label.setText(today_str() + "（T+1：今日买入不可卖出）")

    def render_market(self) -> None:
        codes = self.store.watchlist
        self.market_table.setRowCount(len(codes))
        for row, code in enumerate(codes):
            quote = self.quote_cache.get(code)
            values = [
                code,
                quote.name if quote else "-",
                f"{quote.price:.3f}" if quote else "-",
                pct(quote.change_pct) if quote else "-",
                quote.time_label if quote else "-",
                quote.source if quote else "-",
                quote.currency if quote else "-",
                str(self.store.board_lot(code)),
            ]
            self._set_row(self.market_table, row, values, quote.change_pct if quote else 0.0)

    def render_pending_orders(self) -> None:
        orders = self.store.active_pending_orders()
        self.pending_table.setRowCount(len(orders))
        for row, order in enumerate(orders):
            code = str(order.get("code") or "")
            quote = self.quote_cache.get(code)
            last_price = quote.price if quote else float(order.get("last_price") or 0)
            action = str(order.get("action") or "")
            limit_price = float(order.get("limit_price") or 0)
            trigger = f"现价 <= {limit_price:.3f}" if action == "BUY" else f"现价 >= {limit_price:.3f}"
            values = [
                str(order.get("created_at") or ""),
                "买入" if action == "BUY" else "卖出",
                code,
                str(order.get("name") or ""),
                str(order.get("qty") or ""),
                f"{limit_price:.3f}",
                f"{last_price:.3f}" if last_price else "-",
                "等待成交",
                trigger,
            ]
            order_id = str(order.get("id") or "")
            self._set_row(self.pending_table, row, values, 0.0)
            for col in range(self.pending_table.columnCount()):
                item = self.pending_table.item(row, col)
                if item:
                    item.setData(Qt.UserRole, order_id)

    def render_positions(self) -> None:
        positions = list(self.store.positions().values())
        self.position_table.setRowCount(len(positions))
        history_rows: list[dict[str, Any]] = []
        for row, item in enumerate(positions):
            code = item["code"]
            quote = self.quote_cache.get(code)
            price = quote.price if quote else float(item["avg_cost"])
            qty = int(item["qty"])
            value = price * qty
            floating = value - float(item["cost_amount"])
            rate = floating / float(item["cost_amount"]) * 100 if item["cost_amount"] else 0.0
            actual_avg = item.get("actual_avg_cost")
            actual_text = f"{float(actual_avg):.3f}" if actual_avg is not None else "-"
            values = [
                code,
                item["name"],
                str(qty),
                str(item["available"]),
                actual_text,
                f"{item['breakeven_cost']:.3f}",
                f"{price:.3f}",
                money(value, item.get("currency") or "CNY"),
                money(floating, item.get("currency") or "CNY"),
                pct(rate),
            ]
            self._set_row(self.position_table, row, values, rate)
            history_rows.append(
                {
                    "date": today_str(),
                    "time": now_str(),
                    "code": code,
                    "name": item["name"],
                    "qty": qty,
                    "available": int(item["available"]),
                    "actual_avg_cost": round(float(actual_avg), 4) if actual_avg is not None else None,
                    "breakeven_cost": round(float(item["breakeven_cost"]), 4),
                    "avg_cost": round(float(item["breakeven_cost"]), 4),
                    "price": round(float(price), 4),
                    "market_value": round(float(value), 2),
                    "floating": round(float(floating), 2),
                    "return_pct": round(float(rate), 2),
                    "currency": item.get("currency") or "CNY",
                }
            )
        if history_rows:
            self.store.record_position_history(history_rows)

    def render_position_analysis(self) -> None:
        positions = self.store.positions()
        trades = self.store.data.get("trades") or []
        rows = []
        total_cost = 0.0
        total_value = 0.0
        total_floating = 0.0
        total_realized = 0.0
        for code, item in positions.items():
            quote = self.quote_cache.get(code)
            price = quote.price if quote else float(item["avg_cost"])
            qty = int(item["qty"])
            cost_amount = float(item["cost_amount"])
            value = price * qty
            floating = value - cost_amount
            realized = sum(float(t.get("profit") or 0) for t in trades if t.get("code") == code and t.get("action") == "SELL")
            total_profit = floating + realized
            return_pct = total_profit / cost_amount * 100 if cost_amount else 0.0
            code_trades = [t for t in trades if t.get("code") == code]
            buy_count = sum(1 for t in code_trades if t.get("action") == "BUY")
            sell_count = sum(1 for t in code_trades if t.get("action") == "SELL")
            first_buy = min((str(t.get("time") or "")[:10] for t in code_trades if t.get("action") == "BUY" and t.get("time")), default=today_str())
            try:
                hold_days = max(0, (dt.date.fromisoformat(today_str()) - dt.date.fromisoformat(first_buy)).days)
            except Exception:
                hold_days = 0
            rows.append(
                [
                    code,
                    str(item["name"]),
                    str(hold_days),
                    str(qty),
                    f"{float(item['actual_avg_cost']):.3f}" if item.get("actual_avg_cost") is not None else "-",
                    f"{float(item['breakeven_cost']):.3f}",
                    f"{float(price):.3f}",
                    money(floating, item.get("currency") or "CNY"),
                    money(realized, item.get("currency") or "CNY"),
                    money(total_profit, item.get("currency") or "CNY"),
                    pct(return_pct),
                    str(buy_count),
                    str(sell_count),
                    total_profit,
                ]
            )
            total_cost += cost_amount
            total_value += value
            total_floating += floating
            total_realized += realized
        total_return = (total_floating + total_realized) / total_cost * 100 if total_cost else 0.0
        self.position_summary_label.setText(
            f"持仓 {len(positions)} 只，市值 {money(total_value)}，浮盈亏 {money(total_floating)}，已实现 {money(total_realized)}，综合收益率 {pct(total_return)}"
        )
        self.position_analysis_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            sign = float(values[-1])
            self._set_row(self.position_analysis_table, row, [str(v) for v in values[:-1]], sign)

        history = list(reversed(self.store.data.get("position_history") or []))[:300]
        self.position_history_table.setRowCount(len(history))
        for row, item in enumerate(history):
            sign = float(item.get("floating") or 0)
            values = [
                str(item.get("date") or ""),
                str(item.get("time") or ""),
                str(item.get("code") or ""),
                str(item.get("name") or ""),
                str(item.get("qty") or ""),
                f"{float(item.get('actual_avg_cost')):.3f}" if item.get("actual_avg_cost") is not None else "-",
                f"{float(item.get('breakeven_cost') or item.get('avg_cost') or 0):.3f}",
                f"{float(item.get('price') or 0):.3f}",
                money(float(item.get("market_value") or 0), str(item.get("currency") or "CNY")),
                money(float(item.get("floating") or 0), str(item.get("currency") or "CNY")),
                pct(float(item.get("return_pct") or 0)),
            ]
            self._set_row(self.position_history_table, row, values, sign)

    def render_trades(self) -> None:
        trades = list(reversed(self.store.data.get("trades") or []))
        self.trade_table.setRowCount(len(trades))
        for row, trade in enumerate(trades):
            tail = money(float(trade.get("profit") or 0)) if trade.get("action") == "SELL" else str(trade.get("reason") or "")
            values = [
                trade.get("time", ""),
                trade.get("operator", ""),
                "买入" if trade.get("action") == "BUY" else "卖出",
                trade.get("code", ""),
                trade.get("name", ""),
                str(trade.get("qty", "")),
                f"{float(trade.get('price') or 0):.3f}",
                money(float(trade.get("amount") or 0)),
                tail,
            ]
            self._set_row(self.trade_table, row, values, float(trade.get("profit") or 0))

    def _set_row(self, table: QTableWidget, row: int, values: list[str], sign: float = 0.0) -> None:
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setToolTip(value)
            item.setTextAlignment(Qt.AlignCenter if col < 2 else Qt.AlignRight | Qt.AlignVCenter)
            header_item = table.horizontalHeaderItem(col)
            header = header_item.text() if header_item else ""
            signed_headers = {"涨跌幅", "浮盈亏", "收益率", "回本盈亏", "回本率", "已实现", "总收益"}
            if sign > 0 and header in signed_headers:
                item.setForeground(QColor("#d21f1f"))
            elif sign < 0 and header in signed_headers:
                item.setForeground(QColor("#14934a"))
            table.setItem(row, col, item)

    def place_order(self, action: str, code: str | None = None, qty: int | None = None, operator: str = "用户", reason: str = "") -> None:
        error = self.create_limit_order(action, code, qty, operator, reason)
        if error:
            QMessageBox.warning(self, "下单失败", error)

    def place_position_order(self, action: str) -> None:
        code = self.selected_position_code()
        if not code:
            QMessageBox.warning(self, "未选择持仓", "请先在持仓表中选择一个股票。")
            return
        error = self.create_limit_order(action, code, int(self.position_qty_spin.value()), "用户", "持仓页操作")
        if error:
            QMessageBox.warning(self, "下单失败", error)

    def close_selected_position(self) -> None:
        code = self.selected_position_code()
        if not code:
            QMessageBox.warning(self, "未选择持仓", "请先在持仓表中选择一个股票。")
            return
        pos = self.store.positions().get(code)
        available = int((pos or {}).get("available") or 0)
        if available <= 0:
            QMessageBox.warning(self, "暂无可卖", "该持仓今日没有可卖数量，可能是当天买入尚未满足 T+1。")
            return
        error = self.create_limit_order("sell", code, available, "用户", "清仓可卖")
        if error:
            QMessageBox.warning(self, "清仓失败", error)

    def create_limit_order(self, action: str, code: str | None = None, qty: int | None = None, operator: str = "用户", reason: str = "") -> str | None:
        target = normalize_code(code or self.selected_market_code() or "")
        if not target:
            return "请先在行情表中选择一个股票。"
        quote = self.quote_cache.get(target)
        if not quote:
            self.quote_cache.update(self.quotes.fetch([target]))
            quote = self.quote_cache.get(target)
        if not quote:
            return f"{target} 暂时无法取得实时价格。"
        count = int(qty or self.qty_spin.value())
        if count <= 0:
            return "数量必须大于 0"
        if action.lower() == "buy":
            try:
                self.store.validate_buy_quantity(target, count)
            except Exception as exc:
                return str(exc)
        else:
            try:
                self.store.validate_trade_quantity(target, count)
            except Exception as exc:
                return str(exc)
        dialog = LimitOrderDialog(action, quote, count, self)
        if dialog.exec() != QDialog.Accepted:
            return None
        try:
            order = self.store.add_pending_order(action, quote, count, dialog.limit_price(), operator, reason)
        except Exception as exc:
            return str(exc)
        executed = self.try_execute_pending_orders()
        self.render_all()
        if executed:
            self.status.setText(f"委托已成交：{order['code']} {order['qty']} 股")
        else:
            self.status.setText(f"已提交限价委托：{order['code']} {order['qty']} 股，委托价 {order['limit_price']:.3f}")
        return None

    def cancel_selected_pending_order(self) -> None:
        row = self.pending_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "未选择委托", "请先选择一条未成交委托。")
            return
        item = self.pending_table.item(row, 0)
        order_id = item.data(Qt.UserRole) if item else ""
        if self.store.cancel_pending_order(str(order_id)):
            self.status.setText("已取消选中委托")
            self.render_pending_orders()
        else:
            QMessageBox.warning(self, "取消失败", "该委托已成交或不存在。")

    def try_execute_pending_orders(self) -> int:
        executed = 0
        changed = False
        for order in self.store.data.get("pending_orders") or []:
            if order.get("status") != "ACTIVE":
                continue
            code = str(order.get("code") or "")
            quote = self.quote_cache.get(code)
            if not quote:
                continue
            order["last_price"] = round(float(quote.price), 4)
            action = str(order.get("action") or "").upper()
            limit_price = float(order.get("limit_price") or 0)
            triggered = quote.price <= limit_price if action == "BUY" else quote.price >= limit_price
            if not triggered:
                changed = True
                continue
            if trading_time_error(code):
                changed = True
                continue
            try:
                reason = f"限价委托触发，委托价 {limit_price:.3f}"
                if action == "BUY":
                    self.store.buy(quote, int(order.get("qty") or 0), str(order.get("operator") or "用户"), reason)
                else:
                    self.store.sell(quote, int(order.get("qty") or 0), str(order.get("operator") or "用户"), reason)
                order["status"] = "FILLED"
                order["filled_at"] = now_str()
                order["filled_price"] = round(float(quote.price), 4)
                executed += 1
                changed = True
            except Exception as exc:
                order["status"] = "FAILED"
                order["failed_at"] = now_str()
                order["error"] = str(exc)
                changed = True
        if changed:
            self.store.save()
        return executed

    def execute_order(self, action: str, code: str | None = None, qty: int | None = None, operator: str = "用户", reason: str = "") -> str | None:
        target = normalize_code(code or self.selected_market_code() or "")
        if not target:
            return "请先在行情表中选择一个股票。"
        time_error = trading_time_error(target)
        if time_error:
            return time_error
        quote = self.quote_cache.get(target)
        if not quote:
            self.quote_cache.update(self.quotes.fetch([target]))
            quote = self.quote_cache.get(target)
        if not quote:
            return f"{target} 暂时无法取得实时价格。"
        count = int(qty or self.qty_spin.value())
        try:
            if action.lower() == "buy":
                self.store.buy(quote, count, operator, reason)
            else:
                self.store.sell(quote, count, operator, reason)
        except Exception as exc:
            return str(exc)
        self.render_all()
        return None

    def save_ai_config(self) -> None:
        self.store.data["ai"] = {
            "api_base": self.ai_base.text().strip().rstrip("/"),
            "api_key": self.ai_key.text().strip(),
            "model": self.ai_model.text().strip(),
            "auto_execute": self.ai_auto.isChecked(),
        }
        self.store.save()
        self.status.setText("AI 配置已保存")

    def account_snapshot(self) -> dict[str, Any]:
        positions = self.store.positions()
        return {
            "date": today_str(),
            "cash": self.store.cash,
            "initial_cash": self.store.data.get("initial_cash"),
            "watchlist": self.store.watchlist,
            "board_lots": self.store.data.get("board_lots", {}),
            "quotes": {code: quote.__dict__ for code, quote in self.quote_cache.items()},
            "positions": positions,
            "pending_orders": self.store.active_pending_orders(),
            "rules": "模拟交易；用户和 AI/Codex 下单均为限价委托，buy/sell 指令必须包含 limit_price；买入在实时价小于等于委托价时成交，卖出在实时价大于等于委托价时成交；A股/港股均按 T+1，今日买入不可卖出；买入数量按市场每手/最低申报规则校验；暂不计算手续费、印花税、汇率。",
        }

    def ask_ai(self) -> None:
        self.save_ai_config()
        ai = self.store.data.get("ai") or {}
        if not ai.get("api_key"):
            QMessageBox.warning(self, "缺少 API Key", "请先填写 OpenAI-compatible API Key。")
            return
        prompt = (
            "你是模拟炒股软件中的交易助手。只输出 JSON 数组，不要输出 Markdown。"
            "每个元素格式为 {\"action\":\"buy|sell|hold\", \"code\":\"sh600000\", \"qty\":100, \"limit_price\":10.5, \"reason\":\"简短理由\"}。"
            "buy/sell 必须提供 limit_price；hold 可以省略 qty 和 limit_price。"
            "买入委托在实时价小于等于 limit_price 时成交，卖出委托在实时价大于等于 limit_price 时成交。"
            "只允许使用快照里的股票代码；这是虚拟交易，不构成投资建议。"
        )
        payload = {
            "model": ai.get("model") or "gpt-4.1-mini",
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(self.account_snapshot(), ensure_ascii=False)},
            ],
            "temperature": 0.2,
        }
        try:
            resp = requests.post(
                (ai.get("api_base") or "https://api.openai.com/v1").rstrip("/") + "/chat/completions",
                headers={"Authorization": "Bearer " + ai["api_key"], "Content-Type": "application/json"},
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            self.ai_output.setPlainText(content)
            if self.ai_auto.isChecked():
                self.execute_ai_orders(content, "AI")
        except Exception as exc:
            QMessageBox.warning(self, "AI 请求失败", str(exc))

    def load_codex_orders(self) -> None:
        ensure_config_dir()
        if not os.path.exists(CODEX_ORDER_FILE):
            sample_code = self.store.watchlist[0] if self.store.watchlist else "sh000001"
            quote = self.quote_cache.get(sample_code)
            sample_price = round(float(quote.price), 3) if quote else 1.0
            save_json(
                CODEX_ORDER_FILE,
                [
                    {
                        "action": "hold",
                        "code": sample_code,
                        "qty": 0,
                        "limit_price": sample_price,
                        "reason": "示例：改为 buy/sell 并设置 limit_price 后可提交模拟限价委托",
                    }
                ],
            )
        data = load_json(CODEX_ORDER_FILE, [])
        text = json.dumps(data, ensure_ascii=False, indent=2)
        self.ai_output.setPlainText(text)
        self.status.setText(f"已加载 Codex 指令：{CODEX_ORDER_FILE}")

    def execute_ai_orders(self, text: str, operator: str) -> None:
        try:
            orders = json.loads(text)
            if isinstance(orders, dict):
                orders = orders.get("orders") or []
            if not isinstance(orders, list):
                raise ValueError("JSON 必须是数组，或包含 orders 数组")
        except Exception as exc:
            QMessageBox.warning(self, "JSON 无效", str(exc))
            return

        submitted = 0
        errors: list[str] = []
        for order in orders:
            if not isinstance(order, dict):
                errors.append(f"跳过无效指令：{order}")
                continue
            action = str(order.get("action") or "hold").lower()
            if action == "hold":
                continue
            code = normalize_code(str(order.get("code") or ""))
            reason = str(order.get("reason") or "")
            try:
                qty = int(order.get("qty") or 0)
            except Exception:
                qty = 0
            try:
                limit_price = float(order.get("limit_price"))
            except Exception:
                limit_price = 0.0
            if not code or qty <= 0 or action not in ("buy", "sell") or limit_price <= 0:
                errors.append(f"跳过无效指令：{order}")
                continue
            quote = self.quote_cache.get(code)
            if not quote:
                self.quote_cache.update(self.quotes.fetch([code]))
                quote = self.quote_cache.get(code)
            if not quote:
                errors.append(f"{code}: 暂时无法取得实时价格。")
                continue
            if action == "buy":
                try:
                    self.store.validate_buy_quantity(code, qty)
                except Exception as exc:
                    errors.append(f"{code}: {exc}")
                    continue
            try:
                self.store.add_pending_order(action, quote, qty, limit_price, operator, reason)
            except Exception as exc:
                errors.append(f"{code}: {exc}")
                continue
            submitted += 1
        executed = self.try_execute_pending_orders()
        self.render_all()
        message = f"已提交 {submitted} 条 AI/Codex 限价委托"
        if executed:
            message += f"，本次撮合成交 {executed} 笔"
        if errors:
            message += "\n" + "\n".join(errors[:5])
        QMessageBox.information(self, "AI 执行结果", message)


def main() -> int:
    app = QApplication(sys.argv)
    icon_path = resource_path(ICON_FILE)
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
