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
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "StockTradingSim"
APP_VERSION = "2.0.1"
DISPLAY_NAME = "AIStockSim - AI模拟炒股及摸鱼盯盘工具"
CONFIG_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "portfolio.json")
CODEX_ORDER_FILE = os.path.join(CONFIG_DIR, "codex_orders.json")
CODEX_SNAPSHOT_FILE = os.path.join(CONFIG_DIR, "codex_snapshot.json")
CODEX_RESULT_FILE = os.path.join(CONFIG_DIR, "codex_result.json")
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
DEFAULT_AI_PIPELINE = [
    {
        "enabled": True,
        "role": "技术面分析师",
        "inputs": "价格、涨跌幅、趋势、RSI、交易时段",
        "outputs": "技术观点、关键价位、动量风险",
    },
    {
        "enabled": True,
        "role": "资金流分析师",
        "inputs": "A 股主力资金流、涨跌幅、成交状态",
        "outputs": "资金情绪、背离提示、强弱排序",
    },
    {
        "enabled": True,
        "role": "新闻/情绪分析师",
        "inputs": "预留新闻、公告、行业事件、用户补充信息",
        "outputs": "催化剂、舆情风险、需人工确认事项",
    },
    {
        "enabled": True,
        "role": "风险经理",
        "inputs": "仓位、现金、冻结资金、T+1、每手规则、风控配置",
        "outputs": "风险结论、拦截原因、减仓或观望条件",
    },
    {
        "enabled": True,
        "role": "组合经理",
        "inputs": "各角色结论、账户目标、候选订单、回撤",
        "outputs": "组合建议、再平衡建议、候选 JSON 指令",
    },
]
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


def runtime_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


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


def normalize_order_side(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    if s in ("buy", "b"):
        return "BUY"
    if s in ("sell", "s"):
        return "SELL"
    return ""


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


@dataclass
class MoneyFlow:
    code: str
    name: str
    date: str
    main_net: float
    super_large_net: float
    large_net: float
    medium_net: float
    small_net: float
    main_pct: float
    close: float
    change_pct: float
    source: str


def eastmoney_secid(code: str) -> str | None:
    norm = normalize_code(code)
    if not norm or norm.startswith("hk"):
        return None
    market = "1" if norm.startswith("sh") else "0"
    return market + "." + norm[-6:]


def compact_amount(value: float) -> str:
    sign = "-" if value < 0 else ""
    amount = abs(float(value))
    if amount >= 100000000:
        return f"{sign}{amount / 100000000:.2f}亿"
    if amount >= 10000:
        return f"{sign}{amount / 10000:.0f}万"
    return f"{sign}{amount:.0f}"


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

    def fetch_money_flows(self, codes: list[str]) -> dict[str, MoneyFlow]:
        flows: dict[str, MoneyFlow] = {}
        requested: list[str] = []
        for code in codes:
            norm = normalize_code(code)
            if norm and not norm.startswith("hk") and norm not in requested:
                requested.append(norm)
        for code in requested:
            flow = self._fetch_money_flow(code)
            if flow:
                flows[code] = flow
        return flows

    def _fetch_money_flow(self, code: str) -> MoneyFlow | None:
        secid = eastmoney_secid(code)
        if not secid:
            return None
        try:
            resp = self.session.get(
                "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
                params={
                    "secid": secid,
                    "klt": "101",
                    "lmt": "1",
                    "fields1": "f1,f2,f3,f7",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63",
                    "ut": "b2884a393a59ad64002292a3e90d46a5",
                },
                timeout=4,
            )
            payload = resp.json()
            data = (payload or {}).get("data") or {}
            klines = data.get("klines") or []
            if not klines:
                return None
            parts = str(klines[-1]).split(",")
            if len(parts) < 13:
                return None
            return MoneyFlow(
                code=normalize_code(code) or code,
                name=str(data.get("name") or code),
                date=parts[0],
                main_net=self._to_float(parts[1]),
                super_large_net=self._to_float(parts[2]),
                large_net=self._to_float(parts[3]),
                medium_net=self._to_float(parts[4]),
                small_net=self._to_float(parts[5]),
                main_pct=self._to_float(parts[6]),
                close=self._to_float(parts[11]),
                change_pct=self._to_float(parts[12]),
                source="东方财富资金流",
            )
        except Exception:
            return None

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


class EquityCurveWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.points: list[tuple[str, float, float]] = []
        self.setMinimumHeight(150)

    def set_curve(self, rows: list[dict[str, Any]]) -> None:
        self.points = []
        for item in rows[-80:]:
            try:
                equity = float(item.get("equity") or 0)
                gain = float(item.get("gain") or 0)
            except Exception:
                continue
            if equity > 0:
                self.points.append((str(item.get("time") or ""), equity, gain))
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(12, 10, -12, -12)
        painter.setPen(QPen(QColor("#d8dde6"), 1))
        painter.drawRect(rect)
        if len(self.points) < 2:
            painter.setPen(QColor("#7a8492"))
            painter.drawText(rect, Qt.AlignCenter, "暂无足够账户曲线数据")
            return

        values = [point[1] for point in self.points]
        lo = min(values)
        hi = max(values)
        span = hi - lo if hi > lo else max(1.0, hi * 0.01)
        left = rect.left() + 12
        right = rect.right() - 12
        top = rect.top() + 16
        bottom = rect.bottom() - 24
        width = max(1, right - left)
        height = max(1, bottom - top)

        painter.setPen(QPen(QColor("#edf0f4"), 1))
        for idx in range(1, 4):
            y = top + height * idx / 4
            painter.drawLine(left, int(y), right, int(y))

        path_points: list[tuple[int, int]] = []
        for index, (_stamp, equity, _gain) in enumerate(self.points):
            x = left + int(width * index / max(1, len(self.points) - 1))
            y = bottom - int((equity - lo) / span * height)
            path_points.append((x, y))

        painter.setPen(QPen(QColor("#2f80ed"), 2))
        for start, end in zip(path_points, path_points[1:]):
            painter.drawLine(start[0], start[1], end[0], end[1])

        latest = self.points[-1]
        painter.setPen(QColor("#303946"))
        painter.drawText(rect.adjusted(10, 4, -10, 0), Qt.AlignTop | Qt.AlignLeft, f"最新总资产 {money(latest[1])}")
        painter.setPen(QColor("#d21f1f") if latest[2] > 0 else QColor("#14934a") if latest[2] < 0 else QColor("#596273"))
        painter.drawText(rect.adjusted(10, 4, -10, 0), Qt.AlignTop | Qt.AlignRight, f"累计收益 {money(latest[2])}")


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
            "account_history": [],
            "ai_logs": [],
            "agent_reports": [],
            "agent_chat": [],
            "risk": {
                "enabled": True,
                "block_st_buy": True,
                "max_position_pct": 65.0,
                "max_single_buy_pct": 25.0,
                "max_pending_per_code": 3,
            },
            "ai": {
                "api_base": "https://api.openai.com/v1",
                "api_key": "",
                "model": "gpt-4.1-mini",
                "auto_execute": False,
            },
            "ai_pipeline": {
                "max_retries": 2,
                "agents": [agent.copy() for agent in DEFAULT_AI_PIPELINE],
            },
        }

    def load(self) -> None:
        defaults = self._default()
        self.data = load_json(CONFIG_FILE, defaults)
        for key, value in defaults.items():
            if isinstance(value, dict):
                current = self.data.setdefault(key, {})
                if not isinstance(current, dict):
                    self.data[key] = value.copy()
                    continue
                for sub_key, sub_value in value.items():
                    current.setdefault(sub_key, sub_value)
            else:
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

    def risk_config(self) -> dict[str, Any]:
        defaults = self._default()["risk"]
        cfg = self.data.setdefault("risk", {})
        if not isinstance(cfg, dict):
            cfg = defaults.copy()
            self.data["risk"] = cfg
        for key, value in defaults.items():
            cfg.setdefault(key, value)
        return cfg

    def set_risk_config(self, cfg: dict[str, Any]) -> None:
        current = self.risk_config()
        current.update(cfg)
        self.save()

    def append_ai_log(self, entry: dict[str, Any], limit: int = 500) -> None:
        logs = self.data.setdefault("ai_logs", [])
        if not isinstance(logs, list):
            logs = []
            self.data["ai_logs"] = logs
        item = {
            "id": now_str() + f"-{len(logs):04d}",
            "time": now_str(),
            **entry,
        }
        logs.append(item)
        self.data["ai_logs"] = logs[-limit:]
        self.save()

    def clear_ai_logs(self) -> None:
        self.data["ai_logs"] = []
        self.save()

    def append_agent_report(self, report: dict[str, Any], limit: int = 200) -> None:
        reports = self.data.setdefault("agent_reports", [])
        if not isinstance(reports, list):
            reports = []
            self.data["agent_reports"] = reports
        reports.append(report)
        self.data["agent_reports"] = reports[-limit:]
        self.save()

    def latest_agent_report(self) -> dict[str, Any] | None:
        reports = self.data.get("agent_reports") or []
        if not isinstance(reports, list) or not reports:
            return None
        latest = reports[-1]
        return latest if isinstance(latest, dict) else None

    def append_agent_chat(self, role: str, content: str, limit: int = 200) -> None:
        chat = self.data.setdefault("agent_chat", [])
        if not isinstance(chat, list):
            chat = []
            self.data["agent_chat"] = chat
        chat.append({"time": now_str(), "role": role, "content": content})
        self.data["agent_chat"] = chat[-limit:]
        self.save()

    def clear_agent_chat(self) -> None:
        self.data["agent_chat"] = []
        self.save()

    def ai_pipeline_config(self) -> dict[str, Any]:
        defaults = self._default()["ai_pipeline"]
        cfg = self.data.setdefault("ai_pipeline", {})
        if not isinstance(cfg, dict):
            cfg = defaults.copy()
            self.data["ai_pipeline"] = cfg
        try:
            cfg["max_retries"] = max(0, min(5, int(cfg.get("max_retries", defaults["max_retries"]))))
        except Exception:
            cfg["max_retries"] = defaults["max_retries"]
        agents = cfg.get("agents")
        if not isinstance(agents, list) or not agents:
            cfg["agents"] = [agent.copy() for agent in DEFAULT_AI_PIPELINE]
        else:
            normalized = []
            for agent in agents:
                if not isinstance(agent, dict):
                    continue
                normalized.append(
                    {
                        "enabled": bool(agent.get("enabled", True)),
                        "role": str(agent.get("role") or "AI 代理"),
                        "inputs": str(agent.get("inputs") or agent.get("input") or ""),
                        "outputs": str(agent.get("outputs") or agent.get("output") or ""),
                    }
                )
            cfg["agents"] = normalized or [agent.copy() for agent in DEFAULT_AI_PIPELINE]
        return cfg

    def set_ai_pipeline_config(self, cfg: dict[str, Any]) -> None:
        self.data["ai_pipeline"] = cfg
        self.ai_pipeline_config()
        self.save()

    def reset_ai_pipeline_config(self) -> None:
        self.data["ai_pipeline"] = self._default()["ai_pipeline"]
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
        self.data["account_history"] = []
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

    def resolve_active_pending_order(self, order_id: str = "", code: str = "", action: str = "") -> tuple[dict[str, Any] | None, str | None]:
        order_id = str(order_id or "").strip()
        code = normalize_code(str(code or "")) or ""
        action = str(action or "").strip().upper()
        matches = self.active_pending_orders()
        if order_id:
            matches = [order for order in matches if str(order.get("id") or "") == order_id]
        if code:
            matches = [order for order in matches if str(order.get("code") or "") == code]
        if action:
            matches = [order for order in matches if str(order.get("action") or "").upper() == action]
        if not matches:
            return None, "No matching active pending order."
        if len(matches) > 1:
            return None, "Multiple active pending orders matched; please provide order_id."
        return matches[0], None

    def cancel_matching_pending_order(self, order_id: str = "", code: str = "", action: str = "", reason: str = "") -> dict[str, Any]:
        order, error = self.resolve_active_pending_order(order_id, code, action)
        if error or order is None:
            raise ValueError(error or "No matching active pending order.")
        order["status"] = "CANCELLED"
        order["cancelled_at"] = now_str()
        if reason:
            order["cancel_reason"] = reason
        self.save()
        return order

    def update_pending_order(
        self,
        order_id: str = "",
        code: str = "",
        action: str = "",
        qty: int | None = None,
        limit_price: float | None = None,
        quote: Quote | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        order, error = self.resolve_active_pending_order(order_id, code, action)
        if error or order is None:
            raise ValueError(error or "No matching active pending order.")
        action_name = str(order.get("action") or "").upper()
        target_code = str(order.get("code") or "")
        new_qty = int(qty if qty is not None else int(order.get("qty") or 0))
        new_limit_price = float(limit_price if limit_price is not None else float(order.get("limit_price") or 0))
        if new_qty <= 0 or new_limit_price <= 0:
            raise ValueError("Updated qty and limit_price must be greater than 0.")
        if action_name == "BUY":
            self.validate_buy_quantity(target_code, new_qty)
            current_reserved = float(order.get("limit_price") or 0) * int(order.get("qty") or 0)
            available = round(self.cash - self.reserved_cash() + current_reserved, 2)
            required = round(new_limit_price * new_qty, 2)
            if required > available + 1e-6:
                raise ValueError(f"Available cash is not enough for updated buy order; required {required:.2f}, available {available:.2f}.")
        elif action_name == "SELL":
            self.validate_trade_quantity(target_code, new_qty)
            current_reserved = int(order.get("qty") or 0)
            available_qty = self.available_sell_qty(target_code) + current_reserved
            if new_qty > available_qty:
                raise ValueError(f"Sell quantity is not enough for updated order; available {available_qty}.")
        else:
            raise ValueError("Unsupported pending order action.")
        order["qty"] = new_qty
        order["limit_price"] = round(new_limit_price, 4)
        if quote:
            order["last_price"] = round(float(quote.price), 4)
            order["name"] = quote.name
            order["currency"] = quote.currency
        order["updated_at"] = now_str()
        if reason:
            order["update_reason"] = reason
        self.save()
        return order

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
        realized_by_code: dict[str, float] = {}
        for trade in self.data.get("trades") or []:
            if trade.get("action") == "SELL":
                code = str(trade.get("code") or "")
                realized_by_code[code] = realized_by_code.get(code, 0.0) + float(trade.get("profit") or 0)
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
            qty = int(item["qty"])
            base_cost_amount = float(item["cost_amount"])
            realized = realized_by_code.get(str(item["code"]), 0.0)
            breakeven_cost_amount = base_cost_amount - realized
            item["base_cost_amount"] = base_cost_amount
            item["realized_profit"] = realized
            item["breakeven_cost_amount"] = breakeven_cost_amount
            item["avg_cost"] = base_cost_amount / qty if qty else 0.0
            item["breakeven_cost"] = breakeven_cost_amount / qty if qty else 0.0
            item["cost_amount"] = breakeven_cost_amount
            if item.get("actual_cost_complete"):
                item["actual_avg_cost"] = item["actual_cost_amount"] / qty if qty else 0.0
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

    def record_account_history(self, row: dict[str, Any], limit: int = 1500) -> None:
        history = self.data.get("account_history") or []
        if not isinstance(history, list):
            history = []
        normalized = row.copy()
        normalized["date"] = str(normalized.get("date") or today_str())
        normalized["time"] = str(normalized.get("time") or now_str())[:16]
        by_key = {(str(item.get("date")), str(item.get("time"))): item for item in history if isinstance(item, dict)}
        key = (normalized["date"], normalized["time"])
        if by_key.get(key) == normalized:
            return
        by_key[key] = normalized
        merged = sorted(by_key.values(), key=lambda x: (str(x.get("date")), str(x.get("time"))))
        self.data["account_history"] = merged[-limit:]
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
        self._insert_risk_tab()
        self._rename_global_hotkey_label()

        self.tabs.setTabText(0, "常规")
        self.tabs.setTabText(1, "风控")
        self.tabs.setTabText(2, "盯盘显示")
        self.tabs.setTabText(3, "盯盘外观")
        self.tab_sizes = {
            0: QSize(520, 430),
            1: QSize(520, 390),
            2: QSize(500, 450),
            3: QSize(420, 390),
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

    def _insert_risk_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        cfg = self.owner.store.risk_config()

        risk_box = QGroupBox("下单风控")
        form = QFormLayout(risk_box)
        self.risk_enabled = QCheckBox("启用下单前风控校验")
        self.risk_enabled.setChecked(bool(cfg.get("enabled", True)))
        self.risk_block_st = QCheckBox("禁止买入 ST 风险股")
        self.risk_block_st.setChecked(bool(cfg.get("block_st_buy", True)))

        self.risk_max_position = QDoubleSpinBox()
        self.risk_max_position.setRange(1.0, 100.0)
        self.risk_max_position.setDecimals(1)
        self.risk_max_position.setSuffix("%")
        self.risk_max_position.setValue(float(cfg.get("max_position_pct", 65.0)))

        self.risk_max_buy = QDoubleSpinBox()
        self.risk_max_buy.setRange(1.0, 100.0)
        self.risk_max_buy.setDecimals(1)
        self.risk_max_buy.setSuffix("%")
        self.risk_max_buy.setValue(float(cfg.get("max_single_buy_pct", 25.0)))

        self.risk_max_pending = QSpinBox()
        self.risk_max_pending.setRange(1, 20)
        self.risk_max_pending.setValue(int(cfg.get("max_pending_per_code", 3)))

        form.addRow("", self.risk_enabled)
        form.addRow("", self.risk_block_st)
        form.addRow("单票最大仓位", self.risk_max_position)
        form.addRow("单笔最大买入", self.risk_max_buy)
        form.addRow("同代码活动委托上限", self.risk_max_pending)
        layout.addWidget(risk_box)
        layout.addStretch(1)

        self.risk_enabled.toggled.connect(self._on_risk_changed)
        self.risk_block_st.toggled.connect(self._on_risk_changed)
        self.risk_max_position.valueChanged.connect(self._on_risk_changed)
        self.risk_max_buy.valueChanged.connect(self._on_risk_changed)
        self.risk_max_pending.valueChanged.connect(self._on_risk_changed)
        self.tabs.insertTab(1, tab, "风控")

    def _on_risk_changed(self, *_args: Any) -> None:
        self.owner.store.set_risk_config(
            {
                "enabled": self.risk_enabled.isChecked(),
                "block_st_buy": self.risk_block_st.isChecked(),
                "max_position_pct": float(self.risk_max_position.value()),
                "max_single_buy_pct": float(self.risk_max_buy.value()),
                "max_pending_per_code": int(self.risk_max_pending.value()),
            }
        )
        self.owner.render_all()

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
        self.setWindowTitle(f"{DISPLAY_NAME} {APP_VERSION}")
        self.setMinimumSize(760, 520)
        self.store = PortfolioStore()
        self.quotes = QuoteService()
        self.quote_cache: dict[str, Quote] = {}
        self.money_flow_cache: dict[str, MoneyFlow] = {}
        self._money_flow_last_fetch: dt.datetime | None = None
        self.price_history: dict[str, list[tuple[str, float]]] = {}
        self.compact_window: LegacyCompactWindow | None = None
        self._settings_dialog = None
        self._compact_mode_active = False
        self._suppress_compact_restore = False
        self._tray_menu_open = False
        self._compact_timer_was_active = False
        self._compact_top_timer_was_active = False
        self._closing = False
        self._app_icon_choice = load_compact_config().get("app_icon")
        self._codex_order_mtime = 0.0

        self._build_ui()
        self._build_tray()
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown_compact)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.refresh_quotes(auto=True))
        self.timer.start(self.store.refresh_seconds * 1000)
        self.codex_timer = QTimer(self)
        self.codex_timer.timeout.connect(self.poll_codex_orders)
        self.codex_timer.start(1500)
        self.refresh_quotes(auto=True)
        QTimer.singleShot(800, self.preload_compact_window)

    def _build_ui(self) -> None:
        root = QWidget()
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        nav_panel = QWidget()
        nav_panel.setObjectName("NavPanel")
        nav_panel.setFixedWidth(184)
        nav_layout = QVBoxLayout(nav_panel)
        nav_layout.setContentsMargins(14, 16, 14, 14)
        nav_layout.setSpacing(10)

        brand = QLabel("AIStockSim")
        brand.setObjectName("BrandTitle")
        subtitle = QLabel("2.0 工作台")
        subtitle.setObjectName("BrandSubtitle")
        nav_layout.addWidget(brand)
        nav_layout.addWidget(subtitle)

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("MainNav")
        self.nav_list.setSpacing(3)
        self.nav_list.setFocusPolicy(Qt.NoFocus)
        nav_layout.addWidget(self.nav_list, 1)

        compact_btn = QPushButton("盯盘模式")
        compact_btn.clicked.connect(self.enter_compact_mode)
        settings_btn = QPushButton("全局设置")
        settings_btn.clicked.connect(self.open_main_settings)
        nav_layout.addWidget(compact_btn)
        nav_layout.addWidget(settings_btn)

        workspace = QWidget()
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(14, 12, 14, 10)
        workspace_layout.setSpacing(10)
        self.status = QLabel("")
        self.status.setStyleSheet("font-size: 13px; color: #555;")
        workspace_layout.addWidget(self._account_panel())

        self.page_title = QLabel("")
        self.page_title.setObjectName("PageTitle")
        self.page_hint = QLabel("")
        self.page_hint.setObjectName("PageHint")
        self.page_hint.setWordWrap(True)
        workspace_layout.addWidget(self.page_title)
        workspace_layout.addWidget(self.page_hint)

        self.page_stack = QStackedWidget()
        workspace_layout.addWidget(self.page_stack, 1)
        workspace_layout.addWidget(self.status)

        pages = [
            ("总览", "账户、风险、自选雷达和持仓快照。", self._overview_tab),
            ("行情交易", "自选股行情、限价委托和未成交订单。", self._market_tab),
            ("持仓", "持仓买卖、加仓减仓和清仓入口。", self._position_tab),
            ("AI 工作台", "外部 AI 多智能体分析、候选指令、报告中心和审批入口。", self._agent_tab),
            ("复盘", "持仓复盘、账户曲线、操作者表现和交易质量。", self._review_workspace_tab),
            ("策略", "内置量化信号、风控规则和 AI 可调用策略上下文。", self._strategy_tab),
            ("日志", "交易记录与 AI 托管日志。", self._log_workspace_tab),
            ("AI 设置", "OpenAI-compatible API、Codex JSON 指令和模型配置。", self._ai_tab),
        ]
        self.nav_meta: list[dict[str, str]] = []
        for label, hint, factory in pages:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, hint)
            item.setTextAlignment(Qt.AlignVCenter)
            self.nav_list.addItem(item)
            self.page_stack.addWidget(factory())
            self.nav_meta.append({"label": label, "hint": hint})
        self.nav_list.currentRowChanged.connect(self.change_page)
        self.nav_list.setCurrentRow(0)

        shell.addWidget(nav_panel)
        shell.addWidget(workspace, 1)
        self.setCentralWidget(root)

        self._style()

    def change_page(self, row: int) -> None:
        if row < 0 or row >= self.page_stack.count():
            return
        self.page_stack.setCurrentIndex(row)
        meta = self.nav_meta[row]
        self.page_title.setText(meta["label"])
        self.page_hint.setText(meta["hint"])

    def _metric_card(self, title: str) -> tuple[QFrame, QLabel, QLabel]:
        card = QFrame()
        card.setObjectName("MetricCard")
        card.setFrameShape(QFrame.NoFrame)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("MetricTitle")
        value_label = QLabel("-")
        value_label.setObjectName("MetricValue")
        hint_label = QLabel("")
        hint_label.setObjectName("MetricHint")
        hint_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addWidget(hint_label)
        return card, value_label, hint_label

    def _overview_tab(self) -> QWidget:
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        tab.setWidget(content)

        metrics = QGridLayout()
        metric_defs = [
            ("equity", "总资产"),
            ("cash", "可用资金"),
            ("gain", "累计收益"),
            ("orders", "活动委托"),
            ("risk", "风险状态"),
            ("agent", "AI 最新结论"),
        ]
        self.overview_metric_hints: dict[str, QLabel] = {}
        for index, (key, title) in enumerate(metric_defs):
            card, value, hint = self._metric_card(title)
            setattr(self, f"overview_{key}", value)
            self.overview_metric_hints[key] = hint
            metrics.addWidget(card, index // 3, index % 3)
        for column in range(3):
            metrics.setColumnStretch(column, 1)
        layout.addLayout(metrics)

        insight_row = QGridLayout()
        ai_box = QGroupBox("AI 决策摘要")
        ai_layout = QVBoxLayout(ai_box)
        self.overview_signal = QLabel("-")
        self.overview_signal.setWordWrap(True)
        self.overview_agent_detail = QLabel("-")
        self.overview_agent_detail.setWordWrap(True)
        ai_layout.addWidget(QLabel("策略信号"))
        ai_layout.addWidget(self.overview_signal)
        ai_layout.addWidget(QLabel("多智能体摘要"))
        ai_layout.addWidget(self.overview_agent_detail)

        actions_box = QGroupBox("快捷操作")
        actions_layout = QVBoxLayout(actions_box)
        refresh = QPushButton("立即刷新行情")
        agent = QPushButton("生成 AI 分析")
        compact = QPushButton("盯盘模式")
        refresh.clicked.connect(lambda: self.refresh_quotes(auto=False))
        agent.clicked.connect(self.generate_agent_report)
        compact.clicked.connect(self.enter_compact_mode)
        actions_layout.addWidget(refresh)
        actions_layout.addWidget(agent)
        actions_layout.addWidget(compact)
        actions_layout.addStretch(1)

        curve_box = QGroupBox("账户曲线")
        curve_layout = QVBoxLayout(curve_box)
        self.overview_curve_hint = QLabel("")
        self.overview_curve_hint.setObjectName("MetricHint")
        self.overview_curve = EquityCurveWidget()
        curve_layout.addWidget(self.overview_curve_hint)
        curve_layout.addWidget(self.overview_curve)

        insight_row.addWidget(ai_box, 0, 0)
        insight_row.addWidget(actions_box, 0, 1)
        insight_row.addWidget(curve_box, 0, 2)
        insight_row.setColumnStretch(0, 2)
        insight_row.setColumnStretch(1, 1)
        insight_row.setColumnStretch(2, 2)
        layout.addLayout(insight_row)

        audit_box = QGroupBox("风险审计")
        audit_layout = QVBoxLayout(audit_box)
        self.overview_risk_table = QTableWidget(0, 4)
        self.overview_risk_table.setHorizontalHeaderLabels(["项目", "状态", "说明", "级别"])
        self.overview_risk_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.overview_risk_table.horizontalHeader().setStretchLastSection(True)
        self.overview_risk_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.overview_risk_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.overview_risk_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.overview_risk_table.verticalHeader().setDefaultSectionSize(32)
        self.overview_risk_table.setMinimumHeight(32 * 5 + self.overview_risk_table.horizontalHeader().height() + 18)
        audit_layout.addWidget(self.overview_risk_table)
        layout.addWidget(audit_box)

        decision_box = QGroupBox("AI 决策链")
        decision_layout = QVBoxLayout(decision_box)
        self.overview_decision_table = QTableWidget(0, 4)
        self.overview_decision_table.setHorizontalHeaderLabels(["环节", "立场", "结论", "证据/下一步"])
        self.overview_decision_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.overview_decision_table.horizontalHeader().setStretchLastSection(True)
        self.overview_decision_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.overview_decision_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.overview_decision_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.overview_decision_table.verticalHeader().setDefaultSectionSize(32)
        self.overview_decision_table.setMinimumHeight(32 * 5 + self.overview_decision_table.horizontalHeader().height() + 18)
        decision_layout.addWidget(self.overview_decision_table)
        layout.addWidget(decision_box)

        watch_box = QGroupBox("自选股策略雷达")
        watch_layout = QVBoxLayout(watch_box)
        self.overview_watch_table = QTableWidget(0, 7)
        self.overview_watch_table.setHorizontalHeaderLabels(["代码", "名称", "最新价", "涨跌幅", "趋势", "资金", "风控"])
        self.overview_watch_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.overview_watch_table.horizontalHeader().setStretchLastSection(True)
        self.overview_watch_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.overview_watch_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.overview_watch_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.overview_watch_table.verticalHeader().setDefaultSectionSize(34)
        self.overview_watch_table.setMinimumHeight(34 * 5 + self.overview_watch_table.horizontalHeader().height() + 18)
        watch_layout.addWidget(self.overview_watch_table)
        layout.addWidget(watch_box)

        holdings_box = QGroupBox("持仓风险快照")
        holdings_layout = QVBoxLayout(holdings_box)
        self.overview_positions_table = QTableWidget(0, 7)
        self.overview_positions_table.setHorizontalHeaderLabels(["代码", "名称", "持仓", "可卖", "仓位", "浮盈亏", "回本价"])
        self.overview_positions_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.overview_positions_table.horizontalHeader().setStretchLastSection(True)
        self.overview_positions_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.overview_positions_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.overview_positions_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.overview_positions_table.verticalHeader().setDefaultSectionSize(34)
        self.overview_positions_table.setMinimumHeight(34 * 5 + self.overview_positions_table.horizontalHeader().height() + 18)
        holdings_layout.addWidget(self.overview_positions_table)
        layout.addWidget(holdings_box)
        layout.addStretch(1)
        return tab

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
        self.code_input.setPlaceholderText("输入代码：600000 / sh688001 / hk01810")
        add_btn = QPushButton("加入自选")
        remove_btn = QPushButton("移除选中")
        add_btn.clicked.connect(self.add_watch)
        remove_btn.clicked.connect(self.remove_selected_watch)
        controls.addWidget(self.code_input, 1)
        controls.addWidget(add_btn)
        controls.addWidget(remove_btn)
        layout.addLayout(controls)

        self.market_table = QTableWidget(0, 12)
        self.market_table.setHorizontalHeaderLabels(
            ["代码", "名称", "最新价", "涨跌幅", "时间", "来源", "币种", "每手", "趋势", "RSI", "资金", "风控"]
        )
        self.market_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.market_table.horizontalHeader().setStretchLastSection(False)
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
        self.pending_table.verticalHeader().setDefaultSectionSize(34)
        pending_table_height = 34 * 5 + self.pending_table.horizontalHeader().height() + 18
        self.pending_table.setMinimumHeight(pending_table_height)
        pending_layout.addWidget(self.pending_table)
        pending_margins = pending_layout.contentsMargins()
        pending_box.setMinimumHeight(
            pending_table_height
            + cancel_pending.sizeHint().height()
            + pending_layout.spacing()
            + pending_margins.top()
            + pending_margins.bottom()
            + 24
        )
        layout.addWidget(pending_box, 2)
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
        self.position_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.position_table.horizontalHeader().setStretchLastSection(False)
        self.position_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.position_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.position_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.position_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.position_table.verticalHeader().setDefaultSectionSize(34)
        self.position_table.setMinimumHeight(34 * 5 + self.position_table.horizontalHeader().height() + 18)
        self.position_table.itemSelectionChanged.connect(self.update_position_order_rule)
        layout.addWidget(self.position_table)
        return tab

    def _position_analysis_tab(self) -> QWidget:
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        tab.setWidget(content)
        self.position_summary_label = QLabel("")
        self.position_summary_label.setStyleSheet("font-size: 13px; color: #555;")
        layout.addWidget(self.position_summary_label)

        analysis_box = QGroupBox("当前持仓复盘")
        analysis_layout = QVBoxLayout(analysis_box)
        self.position_analysis_table = QTableWidget(0, 13)
        self.position_analysis_table.setHorizontalHeaderLabels(
            ["代码", "名称", "持仓天数", "持仓", "交易均价", "回本价", "现价", "回本盈亏", "已实现", "总收益", "回本率", "买入次数", "卖出次数"]
        )
        self.position_analysis_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.position_analysis_table.horizontalHeader().setStretchLastSection(False)
        self.position_analysis_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.position_analysis_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.position_analysis_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.position_analysis_table.verticalHeader().setDefaultSectionSize(34)
        analysis_table_height = 34 * 5 + self.position_analysis_table.horizontalHeader().height() + 18
        self.position_analysis_table.setMinimumHeight(analysis_table_height)
        analysis_layout.addWidget(self.position_analysis_table)
        analysis_margins = analysis_layout.contentsMargins()
        analysis_box.setMinimumHeight(analysis_table_height + analysis_margins.top() + analysis_margins.bottom() + 28)
        layout.addWidget(analysis_box)

        history_box = QGroupBox("每日持仓快照")
        history_layout = QVBoxLayout(history_box)
        self.position_history_table = QTableWidget(0, 11)
        self.position_history_table.setHorizontalHeaderLabels(
            ["日期", "时间", "代码", "名称", "持仓", "交易均价", "回本价", "现价", "市值", "回本盈亏", "回本率"]
        )
        self.position_history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.position_history_table.horizontalHeader().setStretchLastSection(False)
        self.position_history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.position_history_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.position_history_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.position_history_table.verticalHeader().setDefaultSectionSize(34)
        history_table_height = 34 * 5 + self.position_history_table.horizontalHeader().height() + 18
        self.position_history_table.setMinimumHeight(history_table_height)
        history_layout.addWidget(self.position_history_table)
        history_margins = history_layout.contentsMargins()
        history_box.setMinimumHeight(history_table_height + history_margins.top() + history_margins.bottom() + 28)
        layout.addWidget(history_box)
        layout.addStretch(1)
        return tab

    def _review_tab(self) -> QWidget:
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        tab.setWidget(content)

        header = QHBoxLayout()
        self.review_summary_label = QLabel("")
        self.review_summary_label.setStyleSheet("font-size: 13px; color: #555;")
        refresh = QPushButton("刷新复盘")
        refresh.clicked.connect(self.render_review)
        header.addWidget(self.review_summary_label, 1)
        header.addWidget(refresh)
        layout.addLayout(header)

        curve_box = QGroupBox("账户曲线")
        curve_layout = QVBoxLayout(curve_box)
        self.review_curve_widget = EquityCurveWidget()
        curve_layout.addWidget(self.review_curve_widget)
        self.review_curve_table = QTableWidget(0, 8)
        self.review_curve_table.setHorizontalHeaderLabels(
            ["时间", "总资产", "可用资金", "持仓市值", "累计收益", "收益率", "回撤", "活动委托"]
        )
        self.review_curve_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.review_curve_table.horizontalHeader().setStretchLastSection(False)
        self.review_curve_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.review_curve_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.review_curve_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.review_curve_table.verticalHeader().setDefaultSectionSize(34)
        curve_height = 34 * 5 + self.review_curve_table.horizontalHeader().height() + 18
        self.review_curve_table.setMinimumHeight(curve_height)
        curve_layout.addWidget(self.review_curve_table)
        curve_margins = curve_layout.contentsMargins()
        curve_box.setMinimumHeight(curve_height + curve_margins.top() + curve_margins.bottom() + 28)
        layout.addWidget(curve_box)

        operator_box = QGroupBox("操作者表现")
        operator_layout = QVBoxLayout(operator_box)
        self.review_operator_table = QTableWidget(0, 8)
        self.review_operator_table.setHorizontalHeaderLabels(
            ["操作者", "买入次数", "卖出次数", "已实现收益", "胜率", "平均卖出收益", "最近操作", "备注"]
        )
        self.review_operator_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.review_operator_table.horizontalHeader().setStretchLastSection(True)
        self.review_operator_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.review_operator_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.review_operator_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.review_operator_table.verticalHeader().setDefaultSectionSize(34)
        operator_height = 34 * 5 + self.review_operator_table.horizontalHeader().height() + 18
        self.review_operator_table.setMinimumHeight(operator_height)
        operator_layout.addWidget(self.review_operator_table)
        operator_margins = operator_layout.contentsMargins()
        operator_box.setMinimumHeight(operator_height + operator_margins.top() + operator_margins.bottom() + 28)
        layout.addWidget(operator_box)

        quality_box = QGroupBox("交易质量提示")
        quality_layout = QVBoxLayout(quality_box)
        self.review_quality_table = QTableWidget(0, 9)
        self.review_quality_table.setHorizontalHeaderLabels(
            ["时间", "操作者", "方向", "代码", "名称", "数量", "价格", "结果", "提示"]
        )
        self.review_quality_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.review_quality_table.horizontalHeader().setStretchLastSection(True)
        self.review_quality_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.review_quality_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.review_quality_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.review_quality_table.verticalHeader().setDefaultSectionSize(34)
        quality_height = 34 * 5 + self.review_quality_table.horizontalHeader().height() + 18
        self.review_quality_table.setMinimumHeight(quality_height)
        quality_layout.addWidget(self.review_quality_table)
        quality_margins = quality_layout.contentsMargins()
        quality_box.setMinimumHeight(quality_height + quality_margins.top() + quality_margins.bottom() + 28)
        layout.addWidget(quality_box)

        layout.addStretch(1)
        return tab

    def _review_workspace_tab(self) -> QWidget:
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        tab.setWidget(content)

        position_title = QLabel("持仓复盘")
        position_title.setObjectName("SectionTitle")
        layout.addWidget(position_title)
        position_page = self._position_analysis_tab()
        position_page.setMinimumHeight(360)
        layout.addWidget(position_page, 1)

        account_title = QLabel("账户与交易质量")
        account_title.setObjectName("SectionTitle")
        layout.addWidget(account_title)
        review_page = self._review_tab()
        review_page.setMinimumHeight(520)
        layout.addWidget(review_page, 2)
        return tab

    def _strategy_tab(self) -> QWidget:
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        tab.setWidget(content)

        catalog_box = QGroupBox("内置策略目录")
        catalog_layout = QVBoxLayout(catalog_box)
        catalog_hint = QLabel("这些策略由本地程序确定性计算，作为 strategy_context 提供给外部 AI；它们不是 AI 结论。")
        catalog_hint.setWordWrap(True)
        catalog_layout.addWidget(catalog_hint)
        self.strategy_catalog_table = QTableWidget(0, 5)
        self.strategy_catalog_table.setHorizontalHeaderLabels(["策略", "状态", "输入", "输出", "AI 调用方式"])
        self.strategy_catalog_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.strategy_catalog_table.horizontalHeader().setStretchLastSection(True)
        self.strategy_catalog_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.strategy_catalog_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.strategy_catalog_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.strategy_catalog_table.verticalHeader().setDefaultSectionSize(34)
        self.strategy_catalog_table.setMinimumHeight(34 * 6 + self.strategy_catalog_table.horizontalHeader().height() + 18)
        catalog_layout.addWidget(self.strategy_catalog_table)
        layout.addWidget(catalog_box)

        matrix_box = QGroupBox("策略信号矩阵")
        matrix_layout = QVBoxLayout(matrix_box)
        matrix_hint = QLabel("矩阵按自选股和持仓合并展示，便于对比趋势、RSI、资金流、仓位风险和未成交委托。")
        matrix_hint.setWordWrap(True)
        matrix_layout.addWidget(matrix_hint)
        self.strategy_signal_table = QTableWidget(0, 10)
        self.strategy_signal_table.setHorizontalHeaderLabels(
            ["代码", "名称", "最新价", "涨跌幅", "趋势", "RSI", "资金流", "风控", "仓位", "活动委托"]
        )
        self.strategy_signal_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.strategy_signal_table.horizontalHeader().setStretchLastSection(True)
        self.strategy_signal_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.strategy_signal_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.strategy_signal_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.strategy_signal_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.strategy_signal_table.verticalHeader().setDefaultSectionSize(34)
        self.strategy_signal_table.setMinimumHeight(34 * 8 + self.strategy_signal_table.horizontalHeader().height() + 18)
        matrix_layout.addWidget(self.strategy_signal_table)
        layout.addWidget(matrix_box, 1)

        detail_box = QGroupBox("AI 可用上下文预览")
        detail_layout = QVBoxLayout(detail_box)
        self.strategy_context_preview = QPlainTextEdit()
        self.strategy_context_preview.setReadOnly(True)
        self.strategy_context_preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.strategy_context_preview.setMinimumHeight(220)
        detail_layout.addWidget(self.strategy_context_preview)
        layout.addWidget(detail_box, 1)
        return tab

    def _log_workspace_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        trade_box = QGroupBox("交易记录")
        trade_layout = QVBoxLayout(trade_box)
        self.trade_table = QTableWidget(0, 9)
        self.trade_table.setHorizontalHeaderLabels(
            ["时间", "操作者", "方向", "代码", "名称", "数量", "价格", "金额", "收益/原因"]
        )
        self.trade_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.trade_table.setEditTriggers(QTableWidget.NoEditTriggers)
        trade_layout.addWidget(self.trade_table)
        layout.addWidget(trade_box, 1)

        ai_box = QGroupBox("AI 托管日志")
        ai_layout = QVBoxLayout(ai_box)
        controls = QHBoxLayout()
        refresh = QPushButton("刷新日志")
        clear = QPushButton("清空日志")
        refresh.clicked.connect(self.render_ai_logs)
        clear.clicked.connect(self.clear_ai_logs)
        controls.addStretch(1)
        controls.addWidget(refresh)
        controls.addWidget(clear)
        ai_layout.addLayout(controls)

        self.ai_log_table = QTableWidget(0, 8)
        self.ai_log_table.setHorizontalHeaderLabels(
            ["时间", "来源", "操作者", "摘要", "提交", "撤单", "改价", "错误"]
        )
        self.ai_log_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.ai_log_table.horizontalHeader().setStretchLastSection(True)
        self.ai_log_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.ai_log_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.ai_log_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.ai_log_table.verticalHeader().setDefaultSectionSize(34)
        self.ai_log_table.itemSelectionChanged.connect(self.render_selected_ai_log_detail)
        ai_layout.addWidget(self.ai_log_table, 2)

        self.ai_log_detail = QPlainTextEdit()
        self.ai_log_detail.setReadOnly(True)
        self.ai_log_detail.setPlaceholderText("选择一条 AI 托管日志后显示完整输入、风控结果和执行结果。")
        ai_layout.addWidget(self.ai_log_detail, 1)
        layout.addWidget(ai_box, 2)
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

    def _agent_tab(self) -> QWidget:
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        tab.setWidget(content)

        pipeline_box = QGroupBox("AI Agent Pipeline")
        pipeline_layout = QVBoxLayout(pipeline_box)
        pipeline_hint = QLabel("外部 AI 会读取本地 strategy_context；这里可配置本次多智能体投研流水线。")
        pipeline_hint.setWordWrap(True)
        pipeline_layout.addWidget(pipeline_hint)

        pipeline_controls = QHBoxLayout()
        self.pipeline_retries = QSpinBox()
        self.pipeline_retries.setRange(0, 5)
        self.pipeline_retries.setValue(int(self.store.ai_pipeline_config().get("max_retries", 2)))
        self.pipeline_retries.valueChanged.connect(self.save_ai_pipeline_from_ui)
        toggle_agent = QPushButton("启用/停用选中")
        reset_pipeline = QPushButton("恢复默认流水线")
        toggle_agent.clicked.connect(self.toggle_selected_pipeline_agent)
        reset_pipeline.clicked.connect(self.reset_ai_pipeline)
        pipeline_controls.addWidget(QLabel("失败重试"))
        pipeline_controls.addWidget(self.pipeline_retries)
        pipeline_controls.addWidget(toggle_agent)
        pipeline_controls.addWidget(reset_pipeline)
        pipeline_controls.addStretch(1)
        pipeline_layout.addLayout(pipeline_controls)

        self.agent_pipeline_table = QTableWidget(0, 6)
        self.agent_pipeline_table.setHorizontalHeaderLabels(["启用", "阶段", "角色", "输入上下文", "结构化输出", "状态"])
        self.agent_pipeline_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.agent_pipeline_table.horizontalHeader().setStretchLastSection(True)
        self.agent_pipeline_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.agent_pipeline_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.agent_pipeline_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.agent_pipeline_table.verticalHeader().setDefaultSectionSize(34)
        pipeline_layout.addWidget(self.agent_pipeline_table)
        layout.addWidget(pipeline_box)

        controls = QHBoxLayout()
        run = QPushButton("生成 AI 分析")
        copy = QPushButton("复制 JSON 指令")
        load = QPushButton("加载候选到指令框")
        open_report = QPushButton("打开报告")
        run.clicked.connect(self.generate_agent_report)
        copy.clicked.connect(self.copy_agent_commands)
        load.clicked.connect(self.load_agent_commands_to_ai_output)
        open_report.clicked.connect(self.open_selected_agent_report)
        controls.addStretch(1)
        controls.addWidget(run)
        controls.addWidget(copy)
        controls.addWidget(load)
        controls.addWidget(open_report)
        layout.addLayout(controls)

        chat_box = QGroupBox("Agent Chatroom")
        chat_layout = QVBoxLayout(chat_box)
        chat_hint = QLabel("围绕当前行情、持仓、风控、策略上下文和最新 AI 报告追问；Chatroom 只输出解释和建议，不直接提交委托。")
        chat_hint.setWordWrap(True)
        chat_layout.addWidget(chat_hint)
        self.agent_chat_view = QPlainTextEdit()
        self.agent_chat_view.setReadOnly(True)
        self.agent_chat_view.setMinimumHeight(180)
        self.agent_chat_view.setPlaceholderText("保存 API 配置后，可以询问：为什么当前不适合补仓？哪只股票需要优先降风险？")
        chat_layout.addWidget(self.agent_chat_view)
        chat_controls = QHBoxLayout()
        self.agent_chat_input = QLineEdit()
        self.agent_chat_input.setPlaceholderText("输入给 AI 的问题，例如：结合当前持仓，今天最该关注哪个风险？")
        send_chat = QPushButton("发送")
        clear_chat = QPushButton("清空对话")
        send_chat.clicked.connect(self.send_agent_chat)
        clear_chat.clicked.connect(self.clear_agent_chat)
        self.agent_chat_input.returnPressed.connect(self.send_agent_chat)
        chat_controls.addWidget(self.agent_chat_input, 1)
        chat_controls.addWidget(send_chat)
        chat_controls.addWidget(clear_chat)
        chat_layout.addLayout(chat_controls)
        layout.addWidget(chat_box)

        report_box = QGroupBox("报告中心")
        report_layout = QVBoxLayout(report_box)
        self.agent_report_table = QTableWidget(0, 5)
        self.agent_report_table.setHorizontalHeaderLabels(["时间", "来源", "摘要", "候选指令", "Markdown 报告"])
        self.agent_report_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.agent_report_table.horizontalHeader().setStretchLastSection(True)
        self.agent_report_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.agent_report_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.agent_report_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.agent_report_table.verticalHeader().setDefaultSectionSize(34)
        report_layout.addWidget(self.agent_report_table)
        layout.addWidget(report_box)

        rebalance_box = QGroupBox("组合再平衡建议")
        rebalance_layout = QVBoxLayout(rebalance_box)
        rebalance_hint = QLabel("本地规则先给出仓位和风险层面的再平衡提示，AI 可在此基础上生成更完整的组合经理结论。")
        rebalance_hint.setWordWrap(True)
        rebalance_layout.addWidget(rebalance_hint)
        self.rebalance_table = QTableWidget(0, 5)
        self.rebalance_table.setHorizontalHeaderLabels(["对象", "建议", "原因", "触发条件", "AI 使用方式"])
        self.rebalance_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.rebalance_table.horizontalHeader().setStretchLastSection(True)
        self.rebalance_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.rebalance_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.rebalance_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.rebalance_table.verticalHeader().setDefaultSectionSize(34)
        self.rebalance_table.setMinimumHeight(34 * 5 + self.rebalance_table.horizontalHeader().height() + 18)
        rebalance_layout.addWidget(self.rebalance_table)
        layout.addWidget(rebalance_box)

        approval_box = QGroupBox("候选指令审批")
        approval_layout = QVBoxLayout(approval_box)
        approval_hint = QLabel("AI 只生成候选指令；真正执行仍需用户确认或明确托管授权，并继续通过现金、T+1、每手和风控校验。")
        approval_hint.setWordWrap(True)
        approval_layout.addWidget(approval_hint)
        approval_controls = QHBoxLayout()
        approve_all = QPushButton("执行全部可执行候选")
        approve_all.clicked.connect(self.execute_agent_candidate_commands)
        approval_controls.addStretch(1)
        approval_controls.addWidget(approve_all)
        approval_layout.addLayout(approval_controls)
        self.agent_command_table = QTableWidget(0, 7)
        self.agent_command_table.setHorizontalHeaderLabels(["动作", "代码", "数量", "委托价", "原因", "预审", "审批状态"])
        self.agent_command_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.agent_command_table.horizontalHeader().setStretchLastSection(True)
        self.agent_command_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.agent_command_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.agent_command_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.agent_command_table.verticalHeader().setDefaultSectionSize(34)
        approval_layout.addWidget(self.agent_command_table)
        layout.addWidget(approval_box)

        result_box = QGroupBox("角色分析")
        result_layout = QVBoxLayout(result_box)
        self.agent_table = QTableWidget(0, 5)
        self.agent_table.setHorizontalHeaderLabels(["角色", "观点", "摘要", "关注", "建议动作"])
        self.agent_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.agent_table.horizontalHeader().setStretchLastSection(False)
        self.agent_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.agent_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.agent_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.agent_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.agent_table.setWordWrap(False)
        self.agent_table.verticalHeader().setDefaultSectionSize(38)
        self.agent_table.setColumnWidth(0, 130)
        self.agent_table.setColumnWidth(1, 80)
        self.agent_table.setColumnWidth(2, 430)
        self.agent_table.setColumnWidth(3, 150)
        self.agent_table.setColumnWidth(4, 420)
        agent_table_height = 38 * 4 + self.agent_table.horizontalHeader().height() + 18
        self.agent_table.setMinimumHeight(agent_table_height)
        self.agent_table.itemSelectionChanged.connect(self.render_selected_agent_detail)
        result_layout.addWidget(self.agent_table, 2)

        self.agent_detail = QPlainTextEdit()
        self.agent_detail.setReadOnly(True)
        self.agent_detail.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.agent_detail.setMinimumHeight(180)
        self.agent_detail.setPlaceholderText("配置 API 后生成 AI 多智能体分析；选择一个代理可查看完整依据、风险点和 JSON 指令草案。")
        result_layout.addWidget(self.agent_detail, 1)
        layout.addWidget(result_box, 2)
        return tab

    def _ai_log_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        controls = QHBoxLayout()
        refresh = QPushButton("刷新日志")
        clear = QPushButton("清空日志")
        refresh.clicked.connect(self.render_ai_logs)
        clear.clicked.connect(self.clear_ai_logs)
        controls.addStretch(1)
        controls.addWidget(refresh)
        controls.addWidget(clear)
        layout.addLayout(controls)

        self.ai_log_table = QTableWidget(0, 8)
        self.ai_log_table.setHorizontalHeaderLabels(
            ["时间", "来源", "操作者", "摘要", "提交", "撤单", "改价", "错误"]
        )
        self.ai_log_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.ai_log_table.horizontalHeader().setStretchLastSection(True)
        self.ai_log_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.ai_log_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.ai_log_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.ai_log_table.verticalHeader().setDefaultSectionSize(34)
        self.ai_log_table.itemSelectionChanged.connect(self.render_selected_ai_log_detail)
        layout.addWidget(self.ai_log_table, 2)

        self.ai_log_detail = QPlainTextEdit()
        self.ai_log_detail.setReadOnly(True)
        self.ai_log_detail.setPlaceholderText("选择一条 AI 托管日志后显示完整输入、风控结果和执行结果。")
        layout.addWidget(self.ai_log_detail, 1)
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
            '[{"action":"buy","code":"hk01810","qty":200,"limit_price":28.0,"reason":"回调到目标价后模拟买入"},\n'
            ' {"action":"amend","code":"sh600000","side":"sell","limit_price":12.8,"reason":"调整旧卖单"},\n'
            ' {"action":"cancel","code":"sh600000","side":"sell","reason":"取消旧委托"}]\n\n'
            f"Codex 本地指令文件：{CODEX_ORDER_FILE}\n"
            f"Codex 账户快照文件：{CODEX_SNAPSHOT_FILE}\n"
            f"Codex 执行结果文件：{CODEX_RESULT_FILE}\n"
            "软件运行时会自动轮询本地指令文件，执行后写入结果并清空指令文件。"
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
            #NavPanel { background: #202833; border-right: 1px solid #131820; }
            #BrandTitle { color: #ffffff; font-size: 19px; font-weight: 700; }
            #BrandSubtitle { color: #aeb8c6; font-size: 12px; }
            #MainNav { background: transparent; border: 0; color: #dfe6ee; font-size: 14px; }
            #MainNav::item { padding: 10px 9px; border-radius: 5px; }
            #MainNav::item:selected { background: #2f80ed; color: #ffffff; }
            #MainNav::item:hover { background: #344255; }
            #PageTitle { font-size: 20px; font-weight: 700; color: #17202a; }
            #PageHint { color: #697386; font-size: 13px; }
            #SectionTitle { font-size: 16px; font-weight: 700; color: #17202a; margin-top: 8px; }
            #MetricCard { background: #ffffff; border: 1px solid #d6dae0; border-radius: 6px; }
            #MetricTitle { color: #6b7280; font-size: 12px; }
            #MetricValue { color: #17202a; font-size: 19px; font-weight: 700; }
            #MetricHint { color: #697386; font-size: 12px; }
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
            QMessageBox.warning(self, "代码无效", "请输入 A 股或港股代码，例如 600000、sh688001、hk01810。")
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
            self.record_price_history(fetched)
            self.refresh_money_flows(codes, force=not auto)
            executed = self.try_execute_pending_orders()
            mode = "自动刷新" if auto else "手动刷新"
            suffix = f"，成交 {executed} 笔委托" if executed else ""
            self.status.setText(f"{mode}：{now_str()}，返回 {len(fetched)} 个代码{suffix}")
        except Exception as exc:
            mode = "自动刷新" if auto else "手动刷新"
            self.status.setText(f"{mode}失败：{exc}")
        self.render_all()

    def refresh_money_flows(self, codes: list[str], force: bool = False) -> None:
        now = dt.datetime.now()
        if not force and self._money_flow_last_fetch is not None:
            if (now - self._money_flow_last_fetch).total_seconds() < 120:
                return
        a_codes: list[str] = []
        for code in codes:
            norm = normalize_code(code)
            if norm and not norm.startswith("hk") and norm not in a_codes:
                a_codes.append(norm)
        a_codes = a_codes[:12]
        if not a_codes:
            return
        self._money_flow_last_fetch = now
        try:
            flows = self.quotes.fetch_money_flows(a_codes)
            if flows:
                self.money_flow_cache.update(flows)
        except Exception:
            return

    def render_all(self) -> None:
        self.render_account()
        self.render_overview()
        self.render_market()
        self.render_positions()
        self.render_position_analysis()
        self.render_review()
        self.render_strategy_workspace()
        self.render_pending_orders()
        self.render_trades()
        self.render_agent_report()
        self.render_agent_pipeline()
        self.render_agent_report_center()
        self.render_agent_commands()
        self.render_rebalance_suggestions()
        self.render_agent_chat()
        self.render_ai_logs()
        self.write_codex_snapshot()

    def overview_risk_summary(self, positions: dict[str, dict[str, Any]], summary: dict[str, float]) -> tuple[str, float]:
        warnings: list[str] = []
        max_weight = 0.0
        equity = summary["equity"]
        for code, item in positions.items():
            quote = self.quote_cache.get(code)
            price = quote.price if quote else float(item.get("breakeven_cost") or item.get("avg_cost") or 0)
            weight = price * int(item.get("qty") or 0) / equity * 100 if equity else 0.0
            max_weight = max(max_weight, weight)
            risk = self.risk_signal_for_code(code, quote)
            if any(key in risk for key in ("ST", "超仓", "接近上限")):
                warnings.append(f"{code} {risk}")
        active_orders = len(self.store.active_pending_orders())
        if active_orders:
            warnings.append(f"{active_orders} 条活动委托")
        if not warnings:
            return "风险可控", 0.0
        return "；".join(warnings[:4]), -1.0

    def record_price_history(self, quotes: dict[str, Quote]) -> None:
        stamp = now_str()
        for code, quote in quotes.items():
            if not quote or quote.price <= 0:
                continue
            series = self.price_history.setdefault(code, [])
            if series and series[-1][1] == quote.price:
                continue
            series.append((stamp, float(quote.price)))
            self.price_history[code] = series[-120:]

    def account_equity_estimate(self) -> float:
        market_value = 0.0
        for code, item in self.store.positions().items():
            quote = self.quote_cache.get(code)
            if quote:
                market_value += quote.price * int(item["qty"])
            else:
                market_value += float(item.get("cost_amount") or 0)
        return max(0.0, self.store.cash + market_value)

    def account_summary(self) -> dict[str, float]:
        positions = self.store.positions()
        market_value = 0.0
        for code, item in positions.items():
            quote = self.quote_cache.get(code)
            if quote:
                market_value += quote.price * int(item["qty"])
            else:
                market_value += float(item.get("cost_amount") or 0)
        equity = self.store.cash + market_value
        initial = float(self.store.data.get("initial_cash") or 0)
        gain = equity - initial
        gain_pct = gain / initial * 100 if initial else 0.0
        reserved = self.store.reserved_cash()
        return {
            "market_value": market_value,
            "equity": equity,
            "initial": initial,
            "gain": gain,
            "gain_pct": gain_pct,
            "reserved": reserved,
            "available_cash": self.store.available_cash(),
            "cash": self.store.cash,
        }

    def record_account_snapshot(self, summary: dict[str, float]) -> None:
        self.store.record_account_history(
            {
                "date": today_str(),
                "time": now_str(),
                "equity": round(float(summary["equity"]), 2),
                "cash": round(float(summary["cash"]), 2),
                "available_cash": round(float(summary["available_cash"]), 2),
                "reserved": round(float(summary["reserved"]), 2),
                "market_value": round(float(summary["market_value"]), 2),
                "gain": round(float(summary["gain"]), 2),
                "gain_pct": round(float(summary["gain_pct"]), 2),
                "positions": len(self.store.positions()),
                "active_orders": len(self.store.active_pending_orders()),
            }
        )

    def account_curve_rows(self) -> list[dict[str, Any]]:
        history = [item for item in self.store.data.get("account_history") or [] if isinstance(item, dict)]
        rows: list[dict[str, Any]] = []
        peak = 0.0
        for item in sorted(history, key=lambda x: (str(x.get("date")), str(x.get("time")))):
            row = item.copy()
            equity = float(row.get("equity") or 0)
            if equity > peak:
                peak = equity
            drawdown = equity / peak * 100 - 100 if peak else 0.0
            row["drawdown_pct"] = round(float(drawdown), 2)
            rows.append(row)
        return rows

    def operator_performance_rows(self) -> list[dict[str, Any]]:
        stats: dict[str, dict[str, Any]] = {}
        for trade in self.store.data.get("trades") or []:
            if not isinstance(trade, dict):
                continue
            operator = str(trade.get("operator") or "未知")
            item = stats.setdefault(
                operator,
                {
                    "operator": operator,
                    "buy_count": 0,
                    "sell_count": 0,
                    "realized": 0.0,
                    "win_count": 0,
                    "latest": "",
                    "latest_action": "",
                },
            )
            action = str(trade.get("action") or "").upper()
            if action == "BUY":
                item["buy_count"] += 1
            elif action == "SELL":
                item["sell_count"] += 1
                profit = float(trade.get("profit") or 0)
                item["realized"] += profit
                if profit > 0:
                    item["win_count"] += 1
            latest_time = str(trade.get("time") or "")
            if latest_time >= str(item.get("latest") or ""):
                item["latest"] = latest_time
                item["latest_action"] = (
                    f"{'买入' if action == 'BUY' else '卖出' if action == 'SELL' else action} "
                    f"{trade.get('code', '')} {trade.get('qty', '')} 股"
                )
        rows = []
        for item in stats.values():
            sell_count = int(item["sell_count"])
            realized = float(item["realized"])
            lower = str(item["operator"]).lower()
            if lower in ("ai", "codex") or "ai" in lower or "codex" in lower:
                note = "AI/Codex 模拟操作"
            elif str(item["operator"]) == "用户":
                note = "用户手动操作"
            else:
                note = "自定义操作者"
            item["win_rate"] = int(item["win_count"]) / sell_count * 100 if sell_count else 0.0
            item["avg_sell_profit"] = realized / sell_count if sell_count else 0.0
            item["note"] = note
            rows.append(item)
        return sorted(rows, key=lambda x: (float(x.get("realized") or 0), str(x.get("operator") or "")), reverse=True)

    def trade_quality_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for trade in reversed(self.store.data.get("trades") or []):
            if not isinstance(trade, dict):
                continue
            action = str(trade.get("action") or "").upper()
            code = str(trade.get("code") or "")
            price = float(trade.get("price") or 0)
            quote = self.quote_cache.get(code)
            sign = 0.0
            if action == "SELL":
                profit = float(trade.get("profit") or 0)
                sign = profit
                result = money(profit)
                if profit > 0:
                    hint = "卖出兑现盈利，复盘是否按计划止盈。"
                elif profit < 0:
                    hint = "卖出确认亏损，复盘止损是否及时。"
                else:
                    hint = "卖出基本持平，关注机会成本。"
            elif action == "BUY" and quote and price > 0:
                move = quote.price / price * 100 - 100
                sign = move
                result = pct(move)
                if move >= 2:
                    hint = "买入后浮盈，留意是否已有止盈计划。"
                elif move <= -2:
                    hint = "买入后浮亏，检查买入依据和止损线。"
                else:
                    hint = "买入后波动不大，继续观察策略信号。"
            elif action == "BUY":
                result = "-"
                hint = "买入记录，等待行情刷新后复盘。"
            else:
                result = "-"
                hint = str(trade.get("reason") or "暂无复盘提示。")
            rows.append(
                {
                    "time": str(trade.get("time") or ""),
                    "operator": str(trade.get("operator") or ""),
                    "action": "买入" if action == "BUY" else "卖出" if action == "SELL" else action,
                    "code": code,
                    "name": str(trade.get("name") or ""),
                    "qty": str(trade.get("qty") or ""),
                    "price": f"{price:.3f}",
                    "result": result,
                    "hint": hint,
                    "sign": sign,
                }
            )
        return rows

    def strategy_signals(self, code: str, quote: Quote | None) -> tuple[str, str, str]:
        if not quote:
            return "-", "-", self.risk_signal_for_code(code, None)
        series = self.price_history.get(code) or []
        prices = [price for _stamp, price in series if price > 0]
        if len(prices) >= 5:
            base = prices[-5]
            move = (prices[-1] / base - 1) * 100 if base else 0.0
            if move >= 0.35:
                trend = f"短线上行 {move:+.2f}%"
            elif move <= -0.35:
                trend = f"短线下行 {move:+.2f}%"
            else:
                trend = f"震荡 {move:+.2f}%"
        else:
            if quote.change_pct >= 1.5:
                trend = "日内强势"
            elif quote.change_pct <= -1.5:
                trend = "日内弱势"
            else:
                trend = "采样中"
        return trend, self.rsi_signal(prices), self.risk_signal_for_code(code, quote)

    def rsi_signal(self, prices: list[float]) -> str:
        if len(prices) < 15:
            return "RSI采样中"
        changes = [prices[i] - prices[i - 1] for i in range(len(prices) - 14, len(prices))]
        gains = [change for change in changes if change > 0]
        losses = [-change for change in changes if change < 0]
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - 100 / (1 + rs)
        if rsi >= 70:
            label = "偏热"
        elif rsi <= 30:
            label = "偏冷"
        else:
            label = "中性"
        return f"RSI {rsi:.0f} {label}"

    def money_flow_signal(self, code: str) -> str:
        norm = normalize_code(code or "")
        if norm and norm.startswith("hk"):
            return "港股暂无"
        flow = self.money_flow_cache.get(norm or code)
        if not flow:
            return "资金采样中"
        amount = compact_amount(flow.main_net)
        if flow.main_net > 0 and flow.main_pct >= 3:
            label = "主力流入"
        elif flow.main_net < 0 and flow.main_pct <= -3:
            label = "主力流出"
        elif flow.main_net > 0:
            label = "小幅流入"
        elif flow.main_net < 0:
            label = "小幅流出"
        else:
            label = "资金平衡"
        return f"{label} {amount} / {flow.main_pct:+.1f}%"

    def risk_signal_for_code(self, code: str, quote: Quote | None) -> str:
        cfg = self.store.risk_config()
        if not cfg.get("enabled", True):
            return "风控关闭"
        quote_name = quote.name if quote else code
        if cfg.get("block_st_buy", True) and "ST" in str(quote_name).upper():
            return "ST限制买入"
        positions = self.store.positions()
        item = positions.get(code) or {}
        qty = int(item.get("qty") or 0)
        if not qty:
            return "无持仓"
        price = quote.price if quote else float(item.get("breakeven_cost") or item.get("avg_cost") or 0)
        equity = self.account_equity_estimate()
        weight = price * qty / equity * 100 if equity else 0.0
        max_position = float(cfg.get("max_position_pct", 65.0))
        if weight >= max_position:
            return f"超仓 {weight:.0f}%"
        if weight >= max_position * 0.8:
            return f"接近上限 {weight:.0f}%"
        return f"仓位 {weight:.0f}%"

    def agent_market_rows(self) -> list[dict[str, Any]]:
        positions = self.store.positions()
        codes = sorted(set(self.store.watchlist + list(positions.keys())))
        equity = self.account_equity_estimate()
        rows: list[dict[str, Any]] = []
        for code in codes:
            quote = self.quote_cache.get(code)
            item = positions.get(code) or {}
            qty = int(item.get("qty") or 0)
            price = quote.price if quote else float(item.get("breakeven_cost") or item.get("avg_cost") or 0)
            value = price * qty
            weight = value / equity * 100 if equity else 0.0
            trend, rsi, risk = self.strategy_signals(code, quote)
            pending = [order for order in self.store.active_pending_orders() if str(order.get("code") or "") == code]
            flow = self.money_flow_cache.get(code)
            rows.append(
                {
                    "code": code,
                    "name": quote.name if quote else str(item.get("name") or code),
                    "price": round(float(price), 4),
                    "change_pct": round(float(quote.change_pct), 2) if quote else None,
                    "trend": trend,
                    "rsi": rsi,
                    "risk": risk,
                    "money_flow": self.money_flow_signal(code),
                    "main_net": round(float(flow.main_net), 2) if flow else None,
                    "main_pct": round(float(flow.main_pct), 2) if flow else None,
                    "flow_date": flow.date if flow else "",
                    "flow_source": flow.source if flow else "",
                    "qty": qty,
                    "available": int(item.get("available") or 0),
                    "weight_pct": round(float(weight), 2),
                    "breakeven_cost": round(float(item.get("breakeven_cost") or 0), 4) if item else None,
                    "floating": round((price - float(item.get("breakeven_cost") or price)) * qty, 2) if qty else 0.0,
                    "pending_count": len(pending),
                    "pending": pending,
                }
            )
        return rows

    def strategy_catalog_rows(self) -> list[dict[str, str]]:
        return [
            {
                "name": "趋势动量",
                "status": "启用",
                "inputs": "最近 120 次价格记录",
                "outputs": "短线上行/下行/震荡",
                "usage": "strategy_context.market_rows[].trend",
            },
            {
                "name": "RSI 冷热",
                "status": "启用",
                "inputs": "最近价格序列",
                "outputs": "偏热、偏冷、强势、弱势、中性",
                "usage": "strategy_context.market_rows[].rsi",
            },
            {
                "name": "A 股资金流",
                "status": "启用",
                "inputs": "东方财富主力净流入与占比",
                "outputs": "主力流入/流出/资金平衡",
                "usage": "strategy_context.market_rows[].money_flow/main_net/main_pct",
            },
            {
                "name": "仓位风控",
                "status": "启用",
                "inputs": "持仓、市值、现金、风控配置",
                "outputs": "超仓、接近上限、仓位可控",
                "usage": "strategy_context.market_rows[].risk 和 risk_audit",
            },
            {
                "name": "交易规则",
                "status": "启用",
                "inputs": "交易日历、交易时段、每手规则、T+1",
                "outputs": "委托预审、成交拦截、可卖数量",
                "usage": "候选指令审批和 execute_ai_orders",
            },
            {
                "name": "交易质量",
                "status": "启用",
                "inputs": "历史买卖记录与当前价",
                "outputs": "买入后浮盈/浮亏、卖出收益、复盘提示",
                "usage": "strategy_context.recent_trade_quality",
            },
            {
                "name": "账户曲线",
                "status": "启用",
                "inputs": "账户历史快照",
                "outputs": "收益率、当前回撤、最大回撤",
                "usage": "strategy_context.account_curve",
            },
        ]

    def strategy_context(self) -> dict[str, Any]:
        curve_rows = self.account_curve_rows()
        latest_curve = curve_rows[-1] if curve_rows else {}
        max_drawdown = min((float(row.get("drawdown_pct") or 0) for row in curve_rows), default=0.0)
        return {
            "note": "These are deterministic local strategy/risk signals for the AI to analyze. They are not an AI-generated conclusion.",
            "generated_at": now_str(),
            "strategy_catalog": self.strategy_catalog_rows(),
            "rebalance_suggestions": self.rebalance_suggestions(),
            "account": self.account_summary(),
            "market_rows": self.agent_market_rows(),
            "operator_performance": self.operator_performance_rows(),
            "recent_trade_quality": self.trade_quality_rows()[:50],
            "account_curve": {
                "latest": latest_curve,
                "max_drawdown_pct": round(float(max_drawdown), 2),
                "samples": curve_rows[-80:],
            },
        }

    def risk_audit_rows(self) -> list[dict[str, Any]]:
        summary = self.account_summary()
        positions = self.store.positions()
        active_orders = self.store.active_pending_orders()
        rows: list[dict[str, Any]] = []

        def add(item: str, status: str, detail: str, sign: float = 0.0) -> None:
            rows.append({"item": item, "status": status, "detail": detail, "sign": sign})

        cn_time = trading_time_error("sh000001")
        hk_time = trading_time_error("hk01810")
        if cn_time is None and hk_time is None:
            add("交易时段", "A/HK 均可交易", "模拟委托可按当前限价撮合。", 1.0)
        elif cn_time is None:
            add("交易时段", "A 股可交易", hk_time or "港股状态未知", 0.5)
        elif hk_time is None:
            add("交易时段", "港股可交易", cn_time or "A 股状态未知", 0.0)
        else:
            add("交易时段", "非交易时段", cn_time, -0.5)

        reserved = float(summary.get("reserved") or 0)
        available_cash = float(summary.get("available_cash") or 0)
        equity = float(summary.get("equity") or 0)
        if reserved > 0:
            add("现金/冻结", "有冻结资金", f"可用 {money(available_cash)}，买入委托冻结 {money(reserved)}。", -0.2)
        elif equity and available_cash / equity < 0.05:
            add("现金/冻结", "现金偏低", f"可用资金 {money(available_cash)}，低于总资产 5%。", -0.3)
        else:
            add("现金/冻结", "充足", f"可用资金 {money(available_cash)}。", 0.8)

        max_weight = 0.0
        max_code = ""
        for code, item in positions.items():
            quote = self.quote_cache.get(code)
            price = quote.price if quote else float(item.get("breakeven_cost") or item.get("avg_cost") or 0)
            qty = int(item.get("qty") or 0)
            weight = price * qty / equity * 100 if equity else 0.0
            if weight > max_weight:
                max_weight = weight
                max_code = code
        max_position = float(self.store.risk_config().get("max_position_pct", 65.0))
        if max_weight >= max_position:
            add("持仓集中度", "超出上限", f"{max_code} 仓位约 {max_weight:.1f}%，上限 {max_position:.1f}%。", -1.0)
        elif max_weight >= max_position * 0.8:
            add("持仓集中度", "接近上限", f"{max_code} 仓位约 {max_weight:.1f}%。", -0.5)
        else:
            add("持仓集中度", "可控", f"最高单票仓位 {max_weight:.1f}%。", 0.5)

        qty_total = sum(int(item.get("qty") or 0) for item in positions.values())
        sellable_total = sum(int(item.get("available") or 0) for item in positions.values())
        if qty_total and sellable_total < qty_total:
            add("T+1 可卖", "部分不可卖", f"持仓 {qty_total} 股，可卖 {sellable_total} 股。", -0.2)
        elif qty_total:
            add("T+1 可卖", "全部可卖", f"持仓 {qty_total} 股均为历史仓。", 0.6)
        else:
            add("T+1 可卖", "无持仓", "当前没有需要执行 T+1 检查的持仓。", 0.0)

        if active_orders:
            add("活动委托", "待撮合", f"当前有 {len(active_orders)} 条未成交委托。", -0.2)
        else:
            add("活动委托", "无", "没有未成交委托占用资金或仓位。", 0.5)

        cfg = self.store.risk_config()
        st_status = "开启" if cfg.get("block_st_buy", True) else "关闭"
        add("ST 买入限制", st_status, "开启时，ST 股票买入会被风控拦截。" if st_status == "开启" else "关闭后需自行承担 ST 风险。", 0.5 if st_status == "开启" else -0.8)

        ai = self.store.data.get("ai") or {}
        if ai.get("api_key"):
            add("AI 接入", "已配置", f"模型 {ai.get('model') or '未设置'}，候选指令仍需预审和确认。", 0.6)
        else:
            add("AI 接入", "未配置", "未填写 API Key 时不会调用外部 AI，只能使用本地策略上下文。", 0.0)
        return rows

    def rebalance_suggestions(self) -> list[dict[str, Any]]:
        summary = self.account_summary()
        equity = float(summary.get("equity") or 0)
        available_cash = float(summary.get("available_cash") or 0)
        cfg = self.store.risk_config()
        max_position = float(cfg.get("max_position_pct", 65.0))
        rows: list[dict[str, Any]] = []

        def add(target: str, suggestion: str, reason: str, condition: str, usage: str, priority: float = 0.0) -> None:
            rows.append(
                {
                    "target": target,
                    "suggestion": suggestion,
                    "reason": reason,
                    "condition": condition,
                    "usage": usage,
                    "priority": priority,
                }
            )

        positions = self.store.positions()
        if not positions:
            add("组合", "等待建仓", "当前没有持仓。", "先添加自选并观察策略信号。", "组合经理可生成观察清单。", 0.0)

        for code, item in positions.items():
            quote = self.quote_cache.get(code)
            price = quote.price if quote else float(item.get("breakeven_cost") or item.get("avg_cost") or 0)
            qty = int(item.get("qty") or 0)
            value = price * qty
            weight = value / equity * 100 if equity else 0.0
            name = quote.name if quote else str(item.get("name") or code)
            breakeven = float(item.get("breakeven_cost") or item.get("avg_cost") or 0)
            floating = (price - breakeven) * qty if qty and breakeven else 0.0
            available = int(item.get("available") or 0)
            label = f"{code} {name}"
            if weight >= max_position:
                add(label, "优先降仓", f"单票仓位 {weight:.1f}% 已超过风控上限 {max_position:.1f}%。", "反弹或 AI 确认弱势时分批降低集中度。", "风险经理/组合经理必须优先处理。", -1.0)
            elif weight >= max_position * 0.8:
                add(label, "控制加仓", f"单票仓位 {weight:.1f}% 接近上限。", "除非趋势和资金流同时改善，否则不追加仓位。", "组合经理给买入建议时需解释集中度。", -0.5)
            if floating < 0 and breakeven and price / breakeven - 1 <= -0.08:
                add(label, "复核止损", f"较回本价浮亏约 {pct(price / breakeven * 100 - 100)}。", "若反弹无量或风险审计转弱，优先确认减仓条件。", "风险经理需要给出是否继续承受回撤。", -0.7)
            if "ST" in str(name).upper():
                add(label, "风险票观察", "名称包含 ST，买入受限且波动风险更高。", "只考虑可卖仓位的风险释放，不做盲目补仓。", "新闻/情绪和风险经理必须单独说明。", -0.8)
            if qty and available <= 0:
                add(label, "T+1 等待", "当前持仓暂无可卖数量。", "等待下一交易日可卖后再执行减仓计划。", "候选卖出指令会被可卖数量预审拦截。", -0.2)

        if equity and available_cash / equity < 0.05:
            add("现金", "保留流动性", f"可用资金仅占总资产 {available_cash / equity * 100:.1f}%。", "除非出现高胜率机会，否则减少新增买入。", "组合经理应优先给出持有/减仓而非补仓。", -0.4)
        elif equity and available_cash / equity >= 0.2:
            add("现金", "可等待机会", f"可用资金占总资产 {available_cash / equity * 100:.1f}%。", "仅在趋势、资金流、风险审计都支持时分批试错。", "组合经理可提出低仓位试探条件。", 0.3)

        active_orders = self.store.active_pending_orders()
        if active_orders:
            add("未成交委托", "复核挂单", f"当前有 {len(active_orders)} 条活动委托。", "行情刷新后检查是否仍符合触发条件。", "AI 候选改价/撤单需先匹配活动委托。", -0.2)
        if not rows:
            add("组合", "保持观察", "仓位、现金和委托暂未触发明显再平衡条件。", "等待趋势/资金流或 AI 报告给出新证据。", "组合经理可以维持 hold。", 0.2)
        return rows[:12]

    def decision_chain_rows(self) -> list[dict[str, Any]]:
        report = self.store.latest_agent_report() or {}
        rows: list[dict[str, Any]] = []
        agents = report.get("agents") if isinstance(report.get("agents"), list) else []
        if agents:
            for agent in agents:
                if not isinstance(agent, dict):
                    continue
                rows.append(
                    {
                        "stage": str(agent.get("role") or "AI 代理"),
                        "stance": str(agent.get("stance") or "中性"),
                        "summary": str(agent.get("summary") or ""),
                        "evidence": str(agent.get("focus") or agent.get("risk") or ""),
                        "sign": 0.0,
                    }
                )
        else:
            for agent in self.store.ai_pipeline_config().get("agents", [])[:5]:
                if not agent.get("enabled", True):
                    continue
                rows.append(
                    {
                        "stage": str(agent.get("role") or "AI 代理"),
                        "stance": "等待",
                        "summary": "尚未生成 AI 分析",
                        "evidence": str(agent.get("outputs") or ""),
                        "sign": 0.0,
                    }
                )

        commands = report.get("commands") if isinstance(report.get("commands"), list) else []
        actionable = [item for item in commands if isinstance(item, dict) and str(item.get("action") or "hold").lower() != "hold"]
        if actionable:
            rows.append(
                {
                    "stage": "候选指令",
                    "stance": f"{len(actionable)} 条待审",
                    "summary": "AI 已给出可人工审批的候选操作。",
                    "evidence": "在 AI 工作台查看预审结果后再执行。",
                    "sign": 0.2,
                }
            )
        elif report:
            rows.append(
                {
                    "stage": "候选指令",
                    "stance": "观望",
                    "summary": "本轮 AI 未给出买卖候选。",
                    "evidence": str(report.get("summary") or ""),
                    "sign": 0.0,
                }
            )
        return rows[:8]

    def render_account(self) -> None:
        summary = self.account_summary()
        self.record_account_snapshot(summary)
        gain = summary["gain"]
        gain_pct = summary["gain_pct"]
        reserved = summary["reserved"]
        cash_text = money(summary["available_cash"])
        if reserved:
            cash_text += f"（冻结 {money(reserved)}）"
        self.cash_label.setText(cash_text)
        self.cash_label.setToolTip(f"现金余额 {money(summary['cash'])}；买入委托冻结 {money(reserved)}")
        self.equity_label.setText(money(summary["equity"]))
        self.profit_label.setText(f"{money(gain)} / {pct(gain_pct)}")
        self.profit_label.setStyleSheet("color: #d21f1f;" if gain > 0 else "color: #14934a;" if gain < 0 else "")
        self.date_label.setText(today_str() + "（T+1：今日买入不可卖出）")

    def render_overview(self) -> None:
        if not hasattr(self, "overview_equity"):
            return
        summary = self.account_summary()
        positions = self.store.positions()
        active_orders = self.store.active_pending_orders()
        risk_text, risk_sign = self.overview_risk_summary(positions, summary)

        def metric_hint(key: str, text: str) -> None:
            hint = getattr(self, "overview_metric_hints", {}).get(key)
            if hint:
                hint.setText(text)

        self.overview_equity.setText(money(summary["equity"]))
        metric_hint("equity", f"持仓市值 {money(summary['market_value'])}")
        self.overview_cash.setText(money(summary["available_cash"]))
        metric_hint("cash", f"现金余额 {money(summary['cash'])}，冻结 {money(summary['reserved'])}")
        self.overview_gain.setText(f"{money(summary['gain'])} / {pct(summary['gain_pct'])}")
        self.overview_gain.setStyleSheet("color: #d21f1f;" if summary["gain"] > 0 else "color: #14934a;" if summary["gain"] < 0 else "")
        metric_hint("gain", f"初始资金 {money(summary['initial'])}")
        self.overview_orders.setText(f"{len(active_orders)} 条")
        metric_hint("orders", "未成交委托会占用现金或可卖数量")
        self.overview_risk.setText(risk_text)
        self.overview_risk.setStyleSheet("color: #14934a;" if risk_sign >= 0 else "color: #d21f1f;")
        metric_hint("risk", "来自持仓、委托和风控配置")

        report = self.store.latest_agent_report()
        report_summary = str((report or {}).get("summary") or "尚未生成 AI 多智能体分析")
        self.overview_agent.setText("已生成" if report else "未生成")
        metric_hint("agent", str((report or {}).get("time") or "需要先配置 API 并生成分析"))
        self.overview_agent_detail.setText(report_summary)

        codes = self.store.watchlist
        hot = []
        cold = []
        for code in codes:
            quote = self.quote_cache.get(code)
            trend, rsi, _risk = self.strategy_signals(code, quote)
            if any(key in trend + rsi for key in ("上行", "偏热", "强势")):
                hot.append(code)
            if any(key in trend + rsi for key in ("下行", "偏冷", "弱势")):
                cold.append(code)
        signal_bits = []
        if hot:
            signal_bits.append("偏强：" + "、".join(hot[:4]))
        if cold:
            signal_bits.append("偏弱：" + "、".join(cold[:4]))
        self.overview_signal.setText("；".join(signal_bits) if signal_bits else "暂无明显策略信号")

        curve_rows = self.account_curve_rows()
        if hasattr(self, "overview_curve"):
            self.overview_curve.set_curve(curve_rows)
        latest_drawdown = float(curve_rows[-1].get("drawdown_pct") or 0) if curve_rows else 0.0
        max_drawdown = min((float(row.get("drawdown_pct") or 0) for row in curve_rows), default=0.0)
        if hasattr(self, "overview_curve_hint"):
            self.overview_curve_hint.setText(f"当前回撤 {pct(latest_drawdown)}，最大回撤 {pct(max_drawdown)}，样本 {len(curve_rows)} 条")

        risk_rows = self.risk_audit_rows()
        if hasattr(self, "overview_risk_table"):
            self.overview_risk_table.setRowCount(len(risk_rows))
            for row, item in enumerate(risk_rows):
                sign = float(item.get("sign") or 0)
                level = "通过" if sign > 0 else "提醒" if sign < 0 else "观察"
                values = [
                    str(item.get("item") or ""),
                    str(item.get("status") or ""),
                    str(item.get("detail") or ""),
                    level,
                ]
                self._set_row(self.overview_risk_table, row, values, sign)
                for col in (2,):
                    cell = self.overview_risk_table.item(row, col)
                    if cell:
                        cell.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        decision_rows = self.decision_chain_rows()
        if hasattr(self, "overview_decision_table"):
            self.overview_decision_table.setRowCount(len(decision_rows))
            for row, item in enumerate(decision_rows):
                sign = float(item.get("sign") or 0)
                values = [
                    str(item.get("stage") or ""),
                    str(item.get("stance") or ""),
                    str(item.get("summary") or ""),
                    str(item.get("evidence") or ""),
                ]
                self._set_row(self.overview_decision_table, row, values, sign)
                for col in (2, 3):
                    cell = self.overview_decision_table.item(row, col)
                    if cell:
                        cell.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.overview_watch_table.setRowCount(len(codes))
        for row, code in enumerate(codes):
            quote = self.quote_cache.get(code)
            trend, _rsi, risk = self.strategy_signals(code, quote)
            values = [
                code,
                quote.name if quote else "-",
                f"{quote.price:.3f}" if quote else "-",
                pct(quote.change_pct) if quote else "-",
                trend,
                self.money_flow_signal(code),
                risk,
            ]
            self._set_row(self.overview_watch_table, row, values, quote.change_pct if quote else 0.0)

        position_rows = list(positions.values())
        self.overview_positions_table.setRowCount(len(position_rows))
        equity = summary["equity"]
        for row, item in enumerate(position_rows):
            code = str(item.get("code") or "")
            quote = self.quote_cache.get(code)
            price = quote.price if quote else float(item.get("breakeven_cost") or item.get("avg_cost") or 0)
            qty = int(item.get("qty") or 0)
            value = price * qty
            floating = value - float(item.get("cost_amount") or 0)
            weight = value / equity * 100 if equity else 0.0
            values = [
                code,
                str(item.get("name") or code),
                str(qty),
                str(item.get("available") or 0),
                f"{weight:.1f}%",
                money(floating, item.get("currency") or "CNY"),
                f"{float(item.get('breakeven_cost') or 0):.3f}",
            ]
            self._set_row(self.overview_positions_table, row, values, floating)

    def render_market(self) -> None:
        codes = self.store.watchlist
        self.market_table.setRowCount(len(codes))
        for row, code in enumerate(codes):
            quote = self.quote_cache.get(code)
            trend, rsi, risk = self.strategy_signals(code, quote)
            money_flow = self.money_flow_signal(code)
            values = [
                code,
                quote.name if quote else "-",
                f"{quote.price:.3f}" if quote else "-",
                pct(quote.change_pct) if quote else "-",
                quote.time_label if quote else "-",
                quote.source if quote else "-",
                quote.currency if quote else "-",
                str(self.store.board_lot(code)),
                trend,
                rsi,
                money_flow,
                risk,
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
            base_cost_amount = float(item.get("base_cost_amount") or cost_amount)
            value = price * qty
            floating = value - cost_amount
            realized = float(item.get("realized_profit") or 0.0)
            total_profit = floating
            return_pct = total_profit / base_cost_amount * 100 if base_cost_amount else 0.0
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
            total_cost += base_cost_amount
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

    def render_review(self) -> None:
        if not hasattr(self, "review_curve_table"):
            return
        summary = self.account_summary()
        curve_rows = self.account_curve_rows()
        latest_drawdown = float(curve_rows[-1].get("drawdown_pct") or 0) if curve_rows else 0.0
        max_drawdown = min((float(row.get("drawdown_pct") or 0) for row in curve_rows), default=0.0)
        active_days = len({str(row.get("date") or "") for row in curve_rows if row.get("date")})
        if hasattr(self, "review_curve_widget"):
            self.review_curve_widget.set_curve(curve_rows)
        self.review_summary_label.setText(
            f"总资产 {money(summary['equity'])}，累计收益 {money(summary['gain'])} / {pct(summary['gain_pct'])}，"
            f"当前回撤 {pct(latest_drawdown)}，最大回撤 {pct(max_drawdown)}，记录 {active_days} 个交易日"
        )

        recent_curve = list(reversed(curve_rows))[:300]
        self.review_curve_table.setRowCount(len(recent_curve))
        for row, item in enumerate(recent_curve):
            drawdown = float(item.get("drawdown_pct") or 0)
            values = [
                str(item.get("time") or ""),
                money(float(item.get("equity") or 0)),
                money(float(item.get("available_cash") or 0)),
                money(float(item.get("market_value") or 0)),
                money(float(item.get("gain") or 0)),
                pct(float(item.get("gain_pct") or 0)),
                pct(drawdown),
                str(item.get("active_orders") or 0),
            ]
            self._set_row(self.review_curve_table, row, values, drawdown)

        operator_rows = self.operator_performance_rows()
        self.review_operator_table.setRowCount(len(operator_rows))
        for row, item in enumerate(operator_rows):
            realized = float(item.get("realized") or 0)
            values = [
                str(item.get("operator") or ""),
                str(item.get("buy_count") or 0),
                str(item.get("sell_count") or 0),
                money(realized),
                pct(float(item.get("win_rate") or 0)),
                money(float(item.get("avg_sell_profit") or 0)),
                str(item.get("latest_action") or ""),
                str(item.get("note") or ""),
            ]
            self._set_row(self.review_operator_table, row, values, realized)

        quality_rows = self.trade_quality_rows()[:300]
        self.review_quality_table.setRowCount(len(quality_rows))
        for row, item in enumerate(quality_rows):
            values = [
                str(item.get("time") or ""),
                str(item.get("operator") or ""),
                str(item.get("action") or ""),
                str(item.get("code") or ""),
                str(item.get("name") or ""),
                str(item.get("qty") or ""),
                str(item.get("price") or ""),
                str(item.get("result") or ""),
                str(item.get("hint") or ""),
            ]
            self._set_row(self.review_quality_table, row, values, float(item.get("sign") or 0))

    def render_strategy_workspace(self) -> None:
        if not hasattr(self, "strategy_catalog_table"):
            return
        catalog = self.strategy_catalog_rows()
        self.strategy_catalog_table.setRowCount(len(catalog))
        for row, item in enumerate(catalog):
            values = [
                str(item.get("name") or ""),
                str(item.get("status") or ""),
                str(item.get("inputs") or ""),
                str(item.get("outputs") or ""),
                str(item.get("usage") or ""),
            ]
            self._set_row(self.strategy_catalog_table, row, values, 0.0)
            for col in (2, 3, 4):
                cell = self.strategy_catalog_table.item(row, col)
                if cell:
                    cell.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        rows = self.agent_market_rows()
        self.strategy_signal_table.setRowCount(len(rows))
        for row, item in enumerate(rows):
            sign = float(item.get("change_pct") or 0)
            values = [
                str(item.get("code") or ""),
                str(item.get("name") or ""),
                f"{float(item.get('price') or 0):.3f}" if item.get("price") is not None else "-",
                pct(float(item.get("change_pct") or 0)) if item.get("change_pct") is not None else "-",
                str(item.get("trend") or ""),
                str(item.get("rsi") or ""),
                str(item.get("money_flow") or ""),
                str(item.get("risk") or ""),
                pct(float(item.get("weight_pct") or 0)),
                str(item.get("pending_count") or 0),
            ]
            self._set_row(self.strategy_signal_table, row, values, sign)
            for col in (4, 5, 6, 7):
                cell = self.strategy_signal_table.item(row, col)
                if cell:
                    cell.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        preview = {
            "strategy_catalog": catalog,
            "market_rows": rows,
            "account_curve": self.strategy_context().get("account_curve"),
        }
        self.strategy_context_preview.setPlainText(json.dumps(preview, ensure_ascii=False, indent=2))

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

    def extract_json_payload(self, text: str) -> Any:
        raw = str(text or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
            raw = re.sub(r"\s*```$", "", raw)
        try:
            return json.loads(raw)
        except Exception:
            pass
        start_candidates = [idx for idx in (raw.find("{"), raw.find("[")) if idx >= 0]
        if not start_candidates:
            raise ValueError("AI 返回内容中没有 JSON。")
        start = min(start_candidates)
        end = max(raw.rfind("}"), raw.rfind("]"))
        if end <= start:
            raise ValueError("AI 返回内容中的 JSON 不完整。")
        return json.loads(raw[start : end + 1])

    def normalize_ai_agent_report(self, payload: Any, raw_text: str) -> dict[str, Any]:
        if isinstance(payload, list):
            report = {"agents": payload}
        elif isinstance(payload, dict):
            report = payload.get("report") if isinstance(payload.get("report"), dict) else payload
        else:
            raise ValueError("AI 返回 JSON 必须是对象，或代理数组。")

        agents_raw = report.get("agents") or report.get("roles") or []
        if not isinstance(agents_raw, list):
            agents_raw = []
        agents: list[dict[str, Any]] = []
        for idx, item in enumerate(agents_raw):
            if not isinstance(item, dict):
                continue
            agents.append(
                {
                    "role": str(item.get("role") or item.get("name") or f"AI 代理 {idx + 1}"),
                    "stance": str(item.get("stance") or item.get("view") or item.get("opinion") or "中性"),
                    "summary": str(item.get("summary") or item.get("analysis") or item.get("conclusion") or ""),
                    "focus": str(item.get("focus") or item.get("basis") or item.get("watch") or ""),
                    "actions": str(item.get("actions") or item.get("recommendation") or item.get("suggestion") or ""),
                    "details": item.get("details") if isinstance(item.get("details"), dict) else item,
                }
            )
        if not agents:
            summary_text = str(report.get("summary") or report.get("conclusion") or raw_text[:500])
            agents = [
                {
                    "role": "AI 综合分析师",
                    "stance": str(report.get("stance") or "中性"),
                    "summary": summary_text,
                    "focus": "综合分析",
                    "actions": str(report.get("actions") or report.get("recommendation") or ""),
                    "details": report,
                }
            ]

        commands = report.get("commands") or report.get("orders") or []
        if not isinstance(commands, list):
            commands = []
        summary = str(report.get("summary") or report.get("conclusion") or agents[-1].get("summary") or "AI 多智能体分析已生成")
        return {
            "id": now_str() + f"-ai-agent-{len(self.store.data.get('agent_reports') or []):04d}",
            "time": now_str(),
            "source": "AI",
            "summary": summary,
            "agents": agents,
            "commands": commands,
            "raw_response": raw_text,
            "notes": report.get("notes") if isinstance(report.get("notes"), list) else [],
        }

    def ai_agent_prompt(self) -> str:
        cfg = self.store.ai_pipeline_config()
        agents = [agent for agent in (cfg.get("agents") or []) if agent.get("enabled", True)]
        if not agents:
            agents = [agent.copy() for agent in DEFAULT_AI_PIPELINE]
        agent_lines = []
        for index, agent in enumerate(agents, 1):
            agent_lines.append(
                f"{index}. {agent.get('role')}：输入={agent.get('inputs')}；输出={agent.get('outputs')}"
            )
        agent_spec = "；".join(agent_lines)
        return (
            "你是 AIStockSim 的外部 AI 多智能体投资分析模块，只分析模拟盘，不操作真实账户。"
            "输入里包含真实行情、持仓、委托、风控配置，以及本地策略上下文 strategy_context。"
            "strategy_context 只是确定性策略/风控信号，供你参考，不是最终结论；最终多智能体分析必须由你完成。"
            f"本次启用的 agent pipeline 是：{agent_spec}。"
            "请严格按照启用的 agent 输出 agents 数组，除非某角色输入不足，否则不要省略。"
            "请严格输出一个 JSON 对象，不要 Markdown，不要解释性前后缀。"
            "JSON 格式："
            "{\"summary\":\"一句话总览\","
            "\"agents\":["
            "{\"role\":\"技术面分析师\",\"stance\":\"偏多|中性|偏空|高风险|可控\","
            "\"summary\":\"基于价格/趋势/RSI的分析\","
            "\"focus\":\"关键观察点\","
            "\"actions\":\"操作建议或观察条件\","
            "\"details\":{\"evidence\":[\"依据1\",\"依据2\"],\"risks\":[\"风险1\"]}}"
            "],"
            "\"commands\":[{\"action\":\"hold|buy|sell|cancel|amend\",\"code\":\"sh600000\",\"qty\":100,"
            "\"limit_price\":12.8,\"reason\":\"简短理由\"}],"
            "\"notes\":[\"补充说明\"]}。"
            "commands 只是候选 JSON 指令，不要为了凑数强行下单；没有把握时使用 hold。"
            "必须遵守 T+1、可用现金、冻结资金、每手数量、风控限制和只允许快照内股票代码。"
            "这是模拟交易练习，不构成投资建议。"
        )

    def markdown_table(self, headers: list[str], rows: list[list[Any]]) -> str:
        def cell(value: Any) -> str:
            text = str(value if value is not None else "")
            return text.replace("|", "\\|").replace("\n", "<br>")

        if not headers:
            return ""
        lines = [
            "| " + " | ".join(cell(header) for header in headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        for row in rows:
            padded = list(row)[: len(headers)] + [""] * max(0, len(headers) - len(row))
            lines.append("| " + " | ".join(cell(value) for value in padded) + " |")
        return "\n".join(lines)

    def ai_report_markdown(self, report: dict[str, Any]) -> str:
        snapshot = report.get("snapshot") if isinstance(report.get("snapshot"), dict) else self.account_snapshot()
        strategy = snapshot.get("strategy_context") if isinstance(snapshot.get("strategy_context"), dict) else {}
        account = snapshot.get("strategy_context", {}).get("account") if isinstance(snapshot.get("strategy_context"), dict) else {}
        if not isinstance(account, dict):
            account = {}
        positions = snapshot.get("positions") if isinstance(snapshot.get("positions"), dict) else {}
        pending_orders = snapshot.get("pending_orders") if isinstance(snapshot.get("pending_orders"), list) else []
        market_rows = strategy.get("market_rows") if isinstance(strategy.get("market_rows"), list) else []
        pipeline = report.get("pipeline") if isinstance(report.get("pipeline"), dict) else {}
        attempts = report.get("attempts") if isinstance(report.get("attempts"), list) else []

        lines: list[str] = [
            f"# AIStockSim AI 多智能体分析报告",
            "",
            f"- 生成时间：{report.get('time') or now_str()}",
            f"- 报告来源：{report.get('source') or 'AI'}",
            f"- 摘要：{report.get('summary') or ''}",
            "",
            "> 本报告由用户配置的 OpenAI-compatible API 生成；本地策略、资金流、风控和复盘数据仅作为 AI 分析上下文。模拟交易练习不构成投资建议。",
            "",
            "## 工作流追踪",
            "",
            self.markdown_table(
                ["启用代理", "失败重试", "实际尝试"],
                [
                    [
                        "、".join(str(agent.get("role") or "") for agent in (pipeline.get("agents") or []) if isinstance(agent, dict)) or "-",
                        str(pipeline.get("max_retries", "")),
                        "；".join(f"{item.get('attempt')}:{item.get('status')}" for item in attempts if isinstance(item, dict)) or "-",
                    ]
                ],
            ),
            "",
            "## 账户快照",
            "",
            self.markdown_table(
                ["总资产", "可用资金", "现金余额", "持仓市值", "累计收益", "收益率", "冻结资金"],
                [
                    [
                        money(float(account.get("equity") or 0)),
                        money(float(account.get("available_cash") or 0)),
                        money(float(account.get("cash") or 0)),
                        money(float(account.get("market_value") or 0)),
                        money(float(account.get("gain") or 0)),
                        pct(float(account.get("gain_pct") or 0)),
                        money(float(account.get("reserved") or 0)),
                    ]
                ],
            ),
            "",
            "## AI 角色分析",
            "",
        ]

        agents = report.get("agents") if isinstance(report.get("agents"), list) else []
        for agent in agents:
            if not isinstance(agent, dict):
                continue
            lines.extend(
                [
                    f"### {agent.get('role') or 'AI 代理'}",
                    "",
                    f"- 观点：{agent.get('stance') or ''}",
                    f"- 关注：{agent.get('focus') or ''}",
                    f"- 摘要：{agent.get('summary') or ''}",
                    f"- 建议：{agent.get('actions') or ''}",
                    "",
                ]
            )
            details = agent.get("details")
            if isinstance(details, dict):
                evidence = details.get("evidence")
                risks = details.get("risks")
                if isinstance(evidence, list) and evidence:
                    lines.append("依据：")
                    lines.extend(f"- {item}" for item in evidence[:8])
                    lines.append("")
                if isinstance(risks, list) and risks:
                    lines.append("风险：")
                    lines.extend(f"- {item}" for item in risks[:8])
                    lines.append("")

        commands = report.get("commands") if isinstance(report.get("commands"), list) else []
        lines.extend(
            [
                "## 候选 JSON 指令",
                "",
                "```json",
                json.dumps(commands, ensure_ascii=False, indent=2),
                "```",
                "",
                "## 自选股策略上下文",
                "",
            ]
        )
        market_table_rows = []
        for row in market_rows[:30]:
            if not isinstance(row, dict):
                continue
            market_table_rows.append(
                [
                    row.get("code"),
                    row.get("name"),
                    row.get("price"),
                    pct(float(row.get("change_pct") or 0)) if row.get("change_pct") is not None else "-",
                    row.get("trend"),
                    row.get("rsi"),
                    row.get("money_flow"),
                    row.get("risk"),
                    row.get("qty"),
                    f"{float(row.get('weight_pct') or 0):.1f}%",
                ]
            )
        lines.extend(
            [
                self.markdown_table(
                    ["代码", "名称", "最新价", "涨跌幅", "趋势", "RSI", "资金", "风控", "持仓", "仓位"],
                    market_table_rows,
                ),
                "",
                "## 当前持仓",
                "",
            ]
        )
        position_rows = []
        for code, item in positions.items():
            if not isinstance(item, dict):
                continue
            position_rows.append(
                [
                    code,
                    item.get("name"),
                    item.get("qty"),
                    item.get("available"),
                    f"{float(item.get('actual_avg_cost')):.3f}" if item.get("actual_avg_cost") is not None else "-",
                    f"{float(item.get('breakeven_cost') or 0):.3f}",
                    money(float(item.get("cost_amount") or 0), str(item.get("currency") or "CNY")),
                ]
            )
        lines.extend(
            [
                self.markdown_table(["代码", "名称", "持仓", "可卖", "交易均价", "回本价", "回本成本"], position_rows),
                "",
                "## 未成交委托",
                "",
            ]
        )
        pending_rows = []
        for order in pending_orders[:50]:
            if not isinstance(order, dict):
                continue
            pending_rows.append(
                [
                    order.get("created_at"),
                    order.get("operator"),
                    order.get("action"),
                    order.get("code"),
                    order.get("name"),
                    order.get("qty"),
                    order.get("limit_price"),
                    order.get("last_price"),
                    order.get("reason"),
                ]
            )
        lines.extend(
            [
                self.markdown_table(["提交时间", "操作者", "方向", "代码", "名称", "数量", "委托价", "现价", "原因"], pending_rows),
                "",
            ]
        )
        notes = report.get("notes") if isinstance(report.get("notes"), list) else []
        if notes:
            lines.extend(["## AI 补充说明", ""])
            lines.extend(f"- {item}" for item in notes)
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def write_ai_report_markdown(self, report: dict[str, Any]) -> str:
        out_dir = runtime_dir()
        os.makedirs(out_dir, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(out_dir, f"AIStockSim_AI分析报告_{stamp}.md")
        latest_path = os.path.join(out_dir, "AIStockSim_最新AI分析报告.md")
        content = self.ai_report_markdown(report)
        for path in (report_path, latest_path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        return report_path

    def generate_agent_report(self) -> None:
        self.save_ai_config()
        ai = self.store.data.get("ai") or {}
        if not ai.get("api_key"):
            QMessageBox.warning(self, "缺少 API Key", "AI 多智能体分析需要先在“AI 接入”页填写 OpenAI-compatible API Key。")
            self.status.setText("未生成 AI 分析：缺少 API Key")
            return

        pipeline_cfg = self.store.ai_pipeline_config()
        pipeline_agents = [agent.copy() for agent in pipeline_cfg.get("agents", []) if agent.get("enabled", True)]
        if not pipeline_agents:
            pipeline_agents = [agent.copy() for agent in DEFAULT_AI_PIPELINE]
        snapshot = self.account_snapshot()
        payload = {
            "model": ai.get("model") or "gpt-4.1-mini",
            "messages": [
                {"role": "system", "content": self.ai_agent_prompt()},
                {"role": "user", "content": json.dumps(snapshot, ensure_ascii=False)},
            ],
            "temperature": 0.2,
        }
        max_retries = int(pipeline_cfg.get("max_retries", 2))
        attempts: list[dict[str, Any]] = []
        try:
            report = None
            content = ""
            for attempt in range(max_retries + 1):
                attempt_no = attempt + 1
                self.status.setText(f"正在请求 AI 多智能体分析... 第 {attempt_no}/{max_retries + 1} 次")
                QApplication.processEvents()
                try:
                    resp = requests.post(
                        (ai.get("api_base") or "https://api.openai.com/v1").rstrip("/") + "/chat/completions",
                        headers={"Authorization": "Bearer " + ai["api_key"], "Content-Type": "application/json"},
                        json=payload,
                        timeout=60,
                    )
                    resp.raise_for_status()
                    content = resp.json()["choices"][0]["message"]["content"]
                    report = self.normalize_ai_agent_report(self.extract_json_payload(content), content)
                    attempts.append({"attempt": attempt_no, "status": "success"})
                    break
                except Exception as attempt_exc:
                    attempts.append({"attempt": attempt_no, "status": "failed", "error": str(attempt_exc)})
                    if attempt >= max_retries:
                        raise
            if report is None:
                raise ValueError("AI 分析未返回有效报告。")
            report["snapshot"] = snapshot
            report["pipeline"] = {"max_retries": max_retries, "agents": pipeline_agents}
            report["attempts"] = attempts
            report_path = self.write_ai_report_markdown(report)
            report["markdown_report"] = report_path
            self.store.append_agent_report(report)
            self.store.append_ai_log(
                {
                    "source": "AI 多智能体分析",
                    "operator": "AI",
                    "summary": report.get("summary", ""),
                    "submitted": 0,
                    "cancelled": 0,
                    "amended": 0,
                    "filled": 0,
                    "errors": [],
                    "report_id": report.get("id"),
                    "report_file": report_path,
                    "commands": report.get("commands") or [],
                    "pipeline": report.get("pipeline"),
                    "attempts": attempts,
                    "snapshot": snapshot,
                    "response": content,
                }
            )
            self.render_agent_report(report)
            self.render_ai_logs()
            self.render_overview()
            self.render_agent_pipeline()
            self.status.setText(f"已生成 AI 多智能体分析并保存报告：{report_path}")
        except Exception as exc:
            self.store.append_ai_log(
                {
                    "source": "AI 多智能体分析",
                    "operator": "AI",
                    "summary": "AI 多智能体分析失败",
                    "submitted": 0,
                    "cancelled": 0,
                    "amended": 0,
                    "filled": 0,
                    "errors": [str(exc)],
                    "pipeline": {"max_retries": max_retries, "agents": pipeline_agents},
                    "attempts": attempts,
                    "snapshot": snapshot,
                }
            )
            self.render_ai_logs()
            self.status.setText(f"AI 多智能体分析失败：{exc}")
            QMessageBox.warning(self, "AI 分析失败", str(exc))

    def render_agent_report(self, report: dict[str, Any] | None = None) -> None:
        if not hasattr(self, "agent_table"):
            return
        report = report or self.store.latest_agent_report()
        agents = list((report or {}).get("agents") or [])
        self.agent_table.setRowCount(len(agents))
        for row, agent in enumerate(agents):
            values = [
                str(agent.get("role") or ""),
                str(agent.get("stance") or ""),
                str(agent.get("summary") or ""),
                str(agent.get("focus") or ""),
                str(agent.get("actions") or ""),
            ]
            sign = 1.0 if str(agent.get("stance")) in ("偏多", "观察加仓机会", "可控") else -1.0 if str(agent.get("stance")) in ("偏空", "高风险", "先控风险") else 0.0
            self._set_row(self.agent_table, row, values, sign)
            for col in range(self.agent_table.columnCount()):
                item = self.agent_table.item(row, col)
                if item:
                    item.setData(Qt.UserRole, agent.get("role"))
                    if col >= 2:
                        item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if report:
            self.agent_detail.setPlainText(json.dumps(report, ensure_ascii=False, indent=2))
        self.render_agent_report_center()
        self.render_agent_commands(report)

    def render_agent_pipeline(self) -> None:
        if not hasattr(self, "agent_pipeline_table"):
            return
        report = self.store.latest_agent_report() or {}
        roles = {str(agent.get("role") or "") for agent in (report.get("agents") or []) if isinstance(agent, dict)}
        cfg = self.store.ai_pipeline_config()
        if hasattr(self, "pipeline_retries"):
            self.pipeline_retries.blockSignals(True)
            self.pipeline_retries.setValue(int(cfg.get("max_retries", 2)))
            self.pipeline_retries.blockSignals(False)
        agents = cfg.get("agents") or []
        self.agent_pipeline_table.setRowCount(len(agents))
        for row, agent in enumerate(agents):
            role = str(agent.get("role") or "")
            enabled = bool(agent.get("enabled", True))
            matched = any(role[:2] in existing or existing[:2] in role for existing in roles)
            status = "已生成" if matched else "等待 AI 输出" if enabled else "已停用"
            values = [
                "是" if enabled else "否",
                str(row + 1),
                role,
                str(agent.get("inputs") or ""),
                str(agent.get("outputs") or ""),
                status,
            ]
            self._set_row(self.agent_pipeline_table, row, values, 1.0 if matched else 0.0)
            for col in range(self.agent_pipeline_table.columnCount()):
                item = self.agent_pipeline_table.item(row, col)
                if item:
                    item.setData(Qt.UserRole, row)
                    if col >= 3:
                        item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    def save_ai_pipeline_from_ui(self) -> None:
        cfg = self.store.ai_pipeline_config()
        cfg["max_retries"] = int(self.pipeline_retries.value()) if hasattr(self, "pipeline_retries") else int(cfg.get("max_retries", 2))
        self.store.set_ai_pipeline_config(cfg)
        self.status.setText(f"AI 分析失败重试次数已设置为 {cfg['max_retries']}")

    def toggle_selected_pipeline_agent(self) -> None:
        if not hasattr(self, "agent_pipeline_table"):
            return
        row = self.agent_pipeline_table.currentRow()
        if row < 0:
            self.status.setText("请先选择一个 AI 代理。")
            return
        cfg = self.store.ai_pipeline_config()
        agents = cfg.get("agents") or []
        if row >= len(agents):
            return
        agents[row]["enabled"] = not bool(agents[row].get("enabled", True))
        cfg["agents"] = agents
        self.store.set_ai_pipeline_config(cfg)
        self.render_agent_pipeline()
        state = "启用" if agents[row]["enabled"] else "停用"
        self.status.setText(f"已{state}代理：{agents[row].get('role')}")

    def reset_ai_pipeline(self) -> None:
        self.store.reset_ai_pipeline_config()
        self.render_agent_pipeline()
        self.status.setText("AI agent pipeline 已恢复默认。")

    def render_agent_report_center(self) -> None:
        if not hasattr(self, "agent_report_table"):
            return
        reports = [item for item in reversed(self.store.data.get("agent_reports") or []) if isinstance(item, dict)][:80]
        self.agent_report_table.setRowCount(len(reports))
        for row, report in enumerate(reports):
            commands = report.get("commands") if isinstance(report.get("commands"), list) else []
            path = str(report.get("markdown_report") or "")
            values = [
                str(report.get("time") or ""),
                str(report.get("source") or "AI"),
                str(report.get("summary") or ""),
                str(len(commands)),
                os.path.basename(path) if path else "-",
            ]
            self._set_row(self.agent_report_table, row, values, 0.0)
            for col in range(self.agent_report_table.columnCount()):
                item = self.agent_report_table.item(row, col)
                if item:
                    item.setData(Qt.UserRole, path)
                    if col == 2:
                        item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    def render_rebalance_suggestions(self) -> None:
        if not hasattr(self, "rebalance_table"):
            return
        rows = self.rebalance_suggestions()
        self.rebalance_table.setRowCount(len(rows))
        for row, item in enumerate(rows):
            sign = float(item.get("priority") or 0)
            values = [
                str(item.get("target") or ""),
                str(item.get("suggestion") or ""),
                str(item.get("reason") or ""),
                str(item.get("condition") or ""),
                str(item.get("usage") or ""),
            ]
            self._set_row(self.rebalance_table, row, values, sign)
            for col in (2, 3, 4):
                cell = self.rebalance_table.item(row, col)
                if cell:
                    cell.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    def render_agent_commands(self, report: dict[str, Any] | None = None) -> None:
        if not hasattr(self, "agent_command_table"):
            return
        report = report or self.store.latest_agent_report() or {}
        commands = report.get("commands") if isinstance(report.get("commands"), list) else []
        self.agent_command_table.setRowCount(len(commands))
        for row, command in enumerate(commands):
            if not isinstance(command, dict):
                continue
            action = str(command.get("action") or "hold").lower()
            audit = self.audit_candidate_command(command)
            status = "无需执行" if action == "hold" else "待用户确认" if audit == "可执行" else "需修正"
            values = [
                action,
                str(command.get("code") or ""),
                str(command.get("qty") or ""),
                str(command.get("limit_price") or ""),
                str(command.get("reason") or ""),
                audit,
                status,
            ]
            self._set_row(self.agent_command_table, row, values, -1.0 if audit != "可执行" and action != "hold" else 0.0)
            for col in range(self.agent_command_table.columnCount()):
                item = self.agent_command_table.item(row, col)
                if item and col == 4:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    def audit_candidate_command(self, command: dict[str, Any]) -> str:
        if not isinstance(command, dict):
            return "格式无效"
        action = str(command.get("action") or "hold").lower()
        if action == "hold":
            return "无需执行"
        if action in ("cancel", "cancel_order", "amend", "modify", "update", "replace", "change_price"):
            order_id = str(command.get("order_id") or command.get("id") or "").strip()
            side = normalize_order_side(command.get("side") or command.get("order_action") or command.get("direction"))
            code = normalize_code(str(command.get("code") or ""))
            order, error = self.store.resolve_active_pending_order(order_id, code or "", side)
            if error or order is None:
                return str(error or "没有匹配的活动委托")
            if action in ("amend", "modify", "update", "replace", "change_price"):
                qty_value = command.get("qty")
                price_value = command.get("limit_price")
                qty = int(qty_value) if qty_value not in (None, "") else int(order.get("qty") or 0)
                limit_price = float(price_value) if price_value not in (None, "") else float(order.get("limit_price") or 0)
                code = str(order.get("code") or "")
                quote = self.quote_cache.get(code)
                if quote:
                    risk_errors = self.risk_violations_for_order(str(order.get("action") or ""), quote, qty, limit_price, order, check_pending_limit=False)
                    if risk_errors:
                        return "风控拦截：" + "；".join(risk_errors)
            return "可执行"
        if action not in ("buy", "sell"):
            return "未知动作"
        code = normalize_code(str(command.get("code") or ""))
        if not code:
            return "缺少代码"
        quote = self.quote_cache.get(code)
        if not quote:
            return "暂无行情"
        try:
            qty = int(command.get("qty") or 0)
            limit_price = float(command.get("limit_price") or 0)
        except Exception:
            return "数量或价格无效"
        if qty <= 0 or limit_price <= 0:
            return "数量或价格无效"
        time_error = trading_time_error(code)
        if time_error:
            return time_error
        try:
            if action == "buy":
                self.store.validate_buy_quantity(code, qty)
                required = round(limit_price * qty, 2)
                available = self.store.available_cash()
                if required > available + 1e-6:
                    return f"可用资金不足，需 {money(required, quote.currency)}"
            else:
                self.store.validate_trade_quantity(code, qty)
                available_qty = self.store.available_sell_qty(code)
                if qty > available_qty:
                    return f"可卖不足，剩余 {available_qty} 股"
        except Exception as exc:
            return str(exc)
        risk_errors = self.risk_violations_for_order(action, quote, qty, limit_price)
        if risk_errors:
            return "风控拦截：" + "；".join(risk_errors)
        return "可执行"

    def render_selected_agent_detail(self) -> None:
        if not hasattr(self, "agent_table") or not hasattr(self, "agent_detail"):
            return
        report = self.store.latest_agent_report() or {}
        row = self.agent_table.currentRow()
        if row < 0:
            self.agent_detail.setPlainText(json.dumps(report, ensure_ascii=False, indent=2))
            return
        item = self.agent_table.item(row, 0)
        role = item.data(Qt.UserRole) if item else ""
        agent = next((entry for entry in report.get("agents") or [] if entry.get("role") == role), None)
        self.agent_detail.setPlainText(json.dumps(agent or report, ensure_ascii=False, indent=2))

    def copy_agent_commands(self) -> None:
        report = self.store.latest_agent_report()
        if not report:
            self.status.setText("暂无 AI 多智能体分析，请先配置 API 并生成分析。")
            QApplication.clipboard().setText("[]")
            return
        commands = report.get("commands") or []
        QApplication.clipboard().setText(json.dumps(commands, ensure_ascii=False, indent=2))
        self.status.setText("已复制组合经理候选 JSON 指令")

    def load_agent_commands_to_ai_output(self) -> None:
        report = self.store.latest_agent_report()
        if not report:
            self.status.setText("暂无候选指令，请先生成 AI 分析。")
            return
        commands = report.get("commands") or []
        if not hasattr(self, "ai_output"):
            self.status.setText("AI 指令框尚未初始化。")
            return
        self.ai_output.setPlainText(json.dumps(commands, ensure_ascii=False, indent=2))
        self.status.setText("已将候选 JSON 指令加载到 AI 设置页，可继续人工检查后执行。")

    def executable_agent_commands(self) -> list[dict[str, Any]]:
        report = self.store.latest_agent_report() or {}
        commands = report.get("commands") if isinstance(report.get("commands"), list) else []
        executable = []
        for command in commands:
            if not isinstance(command, dict):
                continue
            if str(command.get("action") or "hold").lower() == "hold":
                continue
            if self.audit_candidate_command(command) == "可执行":
                executable.append(command)
        return executable

    def execute_agent_candidate_commands(self) -> None:
        commands = self.executable_agent_commands()
        if not commands:
            self.status.setText("没有通过预审的候选指令可执行。")
            return
        text = json.dumps(commands, ensure_ascii=False, indent=2)
        if QMessageBox.question(
            self,
            "执行候选指令",
            f"将执行 {len(commands)} 条通过预审的 AI 候选指令。\n\n这些仍会再次经过模拟盘规则和风控校验，确认继续吗？",
        ) != QMessageBox.Yes:
            return
        self.execute_ai_orders(text, "AI")
        self.render_agent_commands()

    def agent_chat_context(self) -> dict[str, Any]:
        latest_report = self.store.latest_agent_report() or {}
        short_report = {
            "time": latest_report.get("time"),
            "summary": latest_report.get("summary"),
            "agents": latest_report.get("agents") or [],
            "commands": latest_report.get("commands") or [],
            "markdown_report": latest_report.get("markdown_report"),
        } if latest_report else {}
        return {
            "generated_at": now_str(),
            "account": self.account_summary(),
            "market_rows": self.agent_market_rows(),
            "positions": self.store.positions(),
            "pending_orders": self.store.active_pending_orders(),
            "risk_audit": self.risk_audit_rows(),
            "rebalance_suggestions": self.rebalance_suggestions(),
            "recent_trade_quality": self.trade_quality_rows()[:20],
            "latest_agent_report": short_report,
        }

    def render_agent_chat(self) -> None:
        if not hasattr(self, "agent_chat_view"):
            return
        chat = self.store.data.get("agent_chat") if isinstance(self.store.data.get("agent_chat"), list) else []
        role_names = {"user": "用户", "assistant": "AI", "system": "系统"}
        blocks = []
        for item in chat[-80:]:
            if not isinstance(item, dict):
                continue
            role = role_names.get(str(item.get("role") or ""), str(item.get("role") or "未知"))
            blocks.append(f"[{item.get('time') or ''}] {role}\n{item.get('content') or ''}")
        self.agent_chat_view.setPlainText("\n\n".join(blocks))
        bar = self.agent_chat_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def clear_agent_chat(self) -> None:
        if QMessageBox.question(self, "清空对话", "确认清空 Agent Chatroom 的本地对话历史吗？") != QMessageBox.Yes:
            return
        self.store.clear_agent_chat()
        self.render_agent_chat()
        self.status.setText("Agent Chatroom 对话已清空。")

    def send_agent_chat(self) -> None:
        if not hasattr(self, "agent_chat_input"):
            return
        question = self.agent_chat_input.text().strip()
        if not question:
            self.status.setText("请输入要追问 AI 的问题。")
            return
        self.save_ai_config()
        ai = self.store.data.get("ai") or {}
        if not ai.get("api_key"):
            QMessageBox.warning(self, "缺少 API Key", "Agent Chatroom 需要先在“AI 设置”页填写 OpenAI-compatible API Key。")
            self.status.setText("未发送 Agent Chatroom：缺少 API Key")
            return

        self.store.append_agent_chat("user", question)
        self.agent_chat_input.clear()
        self.render_agent_chat()
        context = self.agent_chat_context()
        history = []
        for item in (self.store.data.get("agent_chat") or [])[-10:]:
            if not isinstance(item, dict):
                continue
            role = "assistant" if item.get("role") == "assistant" else "user"
            history.append({"role": role, "content": str(item.get("content") or "")})
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 AIStockSim 的 Agent Chatroom，只讨论模拟盘，不操作真实账户。"
                    "回答要基于当前账户、行情、风险审计、策略上下文和最新多智能体报告。"
                    "如果给出买卖想法，只能用自然语言说明条件和风险，不要输出可直接执行的 JSON 指令。"
                    "需要明确区分事实、推断和不确定性。"
                ),
            },
            {"role": "user", "content": "当前模拟盘上下文 JSON：\n" + json.dumps(context, ensure_ascii=False)},
            *history,
        ]
        payload = {
            "model": ai.get("model") or "gpt-4.1-mini",
            "messages": messages,
            "temperature": 0.3,
        }
        try:
            self.status.setText("Agent Chatroom 正在请求 AI 回复...")
            QApplication.processEvents()
            resp = requests.post(
                (ai.get("api_base") or "https://api.openai.com/v1").rstrip("/") + "/chat/completions",
                headers={"Authorization": "Bearer " + ai["api_key"], "Content-Type": "application/json"},
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            answer = str(resp.json()["choices"][0]["message"]["content"]).strip()
            self.store.append_agent_chat("assistant", answer)
            self.store.append_ai_log(
                {
                    "source": "Agent Chatroom",
                    "operator": "AI",
                    "summary": question[:120],
                    "submitted": 0,
                    "cancelled": 0,
                    "amended": 0,
                    "filled": 0,
                    "errors": [],
                    "snapshot": context,
                    "response": answer,
                }
            )
            self.render_agent_chat()
            self.render_ai_logs()
            self.status.setText("Agent Chatroom 已回复。")
        except Exception as exc:
            self.store.append_ai_log(
                {
                    "source": "Agent Chatroom",
                    "operator": "AI",
                    "summary": question[:120],
                    "submitted": 0,
                    "cancelled": 0,
                    "amended": 0,
                    "filled": 0,
                    "errors": [str(exc)],
                    "snapshot": context,
                }
            )
            self.render_ai_logs()
            self.status.setText(f"Agent Chatroom 请求失败：{exc}")
            QMessageBox.warning(self, "Agent Chatroom 请求失败", str(exc))

    def open_selected_agent_report(self) -> None:
        path = ""
        if hasattr(self, "agent_report_table"):
            row = self.agent_report_table.currentRow()
            if row >= 0:
                item = self.agent_report_table.item(row, 0)
                path = str(item.data(Qt.UserRole) or "") if item else ""
        if not path:
            report = self.store.latest_agent_report() or {}
            path = str(report.get("markdown_report") or "")
        if path and os.path.exists(path):
            os.startfile(path)
            self.status.setText(f"已打开 AI Markdown 报告：{path}")
        else:
            self.status.setText("暂无可打开的 Markdown 报告。")

    def render_ai_logs(self) -> None:
        if not hasattr(self, "ai_log_table"):
            return
        logs = list(reversed(self.store.data.get("ai_logs") or []))[:300]
        self.ai_log_table.setRowCount(len(logs))
        for row, log in enumerate(logs):
            errors = log.get("errors") or []
            if not isinstance(errors, list):
                errors = [str(errors)]
            values = [
                str(log.get("time") or ""),
                str(log.get("source") or ""),
                str(log.get("operator") or ""),
                str(log.get("summary") or ""),
                str(log.get("submitted") or 0),
                str(log.get("cancelled") or 0),
                str(log.get("amended") or 0),
                str(len(errors)),
            ]
            self._set_row(self.ai_log_table, row, values, -1.0 if errors else 0.0)
            for col in range(self.ai_log_table.columnCount()):
                item = self.ai_log_table.item(row, col)
                if item:
                    item.setData(Qt.UserRole, log.get("id"))

    def render_selected_ai_log_detail(self) -> None:
        if not hasattr(self, "ai_log_table") or not hasattr(self, "ai_log_detail"):
            return
        row = self.ai_log_table.currentRow()
        if row < 0:
            self.ai_log_detail.clear()
            return
        item = self.ai_log_table.item(row, 0)
        log_id = item.data(Qt.UserRole) if item else ""
        logs = self.store.data.get("ai_logs") or []
        log = next((entry for entry in logs if entry.get("id") == log_id), None)
        self.ai_log_detail.setPlainText(json.dumps(log or {}, ensure_ascii=False, indent=2))

    def clear_ai_logs(self) -> None:
        if QMessageBox.question(self, "清空日志", "确定清空 AI 托管日志吗？") != QMessageBox.Yes:
            return
        self.store.clear_ai_logs()
        self.render_ai_logs()
        self.ai_log_detail.clear()

    def risk_violations_for_order(
        self,
        action: str,
        quote: Quote,
        qty: int,
        limit_price: float,
        replacing_order: dict[str, Any] | None = None,
        check_pending_limit: bool = True,
    ) -> list[str]:
        cfg = self.store.risk_config()
        if not cfg.get("enabled", True):
            return []
        action_name = action.upper()
        code = quote.code
        errors: list[str] = []
        replace_id = str((replacing_order or {}).get("id") or "")
        active_same_code = [
            order
            for order in self.store.active_pending_orders()
            if str(order.get("code") or "") == code and str(order.get("id") or "") != replace_id
        ]
        max_pending = int(cfg.get("max_pending_per_code", 3))
        if check_pending_limit and len(active_same_code) >= max_pending:
            errors.append(f"{code} 已有 {len(active_same_code)} 条活动委托，达到同代码委托上限 {max_pending}。")
        if action_name != "BUY":
            return errors

        if cfg.get("block_st_buy", True) and "ST" in quote.name.upper():
            errors.append(f"{quote.name} 属于 ST 风险股，当前风控禁止买入。")
        equity = self.account_equity_estimate()
        order_value = max(0.0, float(limit_price) * int(qty))
        if equity > 0:
            max_single_buy = equity * float(cfg.get("max_single_buy_pct", 25.0)) / 100
            if order_value > max_single_buy + 1e-6:
                errors.append(
                    f"单笔买入金额 {money(order_value, quote.currency)} 超过账户权益 {float(cfg.get('max_single_buy_pct', 25.0)):.1f}% 上限。"
                )
            positions = self.store.positions()
            current_qty = int((positions.get(code) or {}).get("qty") or 0)
            pending_buy_value = 0.0
            for order in self.store.active_pending_orders():
                if str(order.get("id") or "") == replace_id:
                    continue
                if str(order.get("code") or "") == code and str(order.get("action") or "").upper() == "BUY":
                    pending_buy_value += float(order.get("limit_price") or 0) * int(order.get("qty") or 0)
            target_value = current_qty * quote.price + pending_buy_value + order_value
            target_pct = target_value / equity * 100
            max_position = float(cfg.get("max_position_pct", 65.0))
            if target_pct > max_position + 1e-6:
                errors.append(f"{code} 买入后预计仓位 {target_pct:.1f}%，超过单票最大仓位 {max_position:.1f}%。")
        return errors

    def _set_row(self, table: QTableWidget, row: int, values: list[str], sign: float = 0.0) -> None:
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setToolTip(value)
            item.setTextAlignment(Qt.AlignCenter if col < 2 else Qt.AlignRight | Qt.AlignVCenter)
            header_item = table.horizontalHeaderItem(col)
            header = header_item.text() if header_item else ""
            signed_headers = {
                "涨跌幅",
                "浮盈亏",
                "收益率",
                "累计收益",
                "回撤",
                "回本盈亏",
                "回本率",
                "已实现",
                "已实现收益",
                "平均卖出收益",
                "总收益",
                "结果",
                "观点",
                "资金",
                "风控",
            }
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
        risk_errors = self.risk_violations_for_order(action, quote, count, dialog.limit_price())
        if risk_errors:
            return "风控拦截：\n" + "\n".join(risk_errors)
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
                qty = int(order.get("qty") or 0)
                risk_errors = self.risk_violations_for_order(action, quote, qty, quote.price, order, check_pending_limit=False)
                if risk_errors:
                    order["status"] = "FAILED"
                    order["failed_at"] = now_str()
                    order["error"] = "风控拦截：" + "；".join(risk_errors)
                    changed = True
                    continue
                reason = f"限价委托触发，委托价 {limit_price:.3f}"
                if action == "BUY":
                    self.store.buy(quote, qty, str(order.get("operator") or "用户"), reason)
                else:
                    self.store.sell(quote, qty, str(order.get("operator") or "用户"), reason)
                order["status"] = "FILLED"
                order["filled_at"] = now_str()
                order["filled_price"] = round(float(quote.price), 4)
                executed += 1
                changed = True
                if str(order.get("operator") or "").lower() in ("ai", "codex"):
                    self.store.append_ai_log(
                        {
                            "source": "委托撮合",
                            "operator": str(order.get("operator") or ""),
                            "summary": f"{code} {action} {qty} 股触发成交，成交价 {quote.price:.3f}",
                            "submitted": 0,
                            "cancelled": 0,
                            "amended": 0,
                            "filled": 1,
                            "errors": [],
                            "orders": [order],
                        }
                    )
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
            risk_errors = self.risk_violations_for_order(action, quote, count, quote.price, check_pending_limit=False)
            if risk_errors:
                return "风控拦截：\n" + "\n".join(risk_errors)
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
        codes = sorted(set(self.store.watchlist + list(positions.keys())))
        strategy_signals = {}
        for code in codes:
            trend, rsi, risk = self.strategy_signals(code, self.quote_cache.get(code))
            strategy_signals[code] = {"trend": trend, "rsi": rsi, "risk": risk}
        latest_report = self.store.latest_agent_report() or {}
        return {
            "date": today_str(),
            "cash": self.store.cash,
            "initial_cash": self.store.data.get("initial_cash"),
            "watchlist": self.store.watchlist,
            "board_lots": self.store.data.get("board_lots", {}),
            "quotes": {code: quote.__dict__ for code, quote in self.quote_cache.items()},
            "money_flows": {code: flow.__dict__ for code, flow in self.money_flow_cache.items()},
            "positions": positions,
            "pending_orders": self.store.active_pending_orders(),
            "risk": self.store.risk_config(),
            "ai_pipeline": self.store.ai_pipeline_config(),
            "strategy_signals": strategy_signals,
            "strategy_context": self.strategy_context(),
            "latest_agent_report": {
                "id": latest_report.get("id"),
                "time": latest_report.get("time"),
                "summary": latest_report.get("summary"),
                "commands": latest_report.get("commands") or [],
            } if latest_report else None,
            "rules": "模拟交易；用户和 AI/Codex 下单均为限价委托，buy/sell 指令必须包含 limit_price；买入在实时价小于等于委托价时成交，卖出在实时价大于等于委托价时成交；A股/港股均按 T+1，今日买入不可卖出；买入数量按市场每手/最低申报规则校验；暂不计算手续费、印花税、汇率。",
            "codex_order_schema": {
                "new_order": {"action": "buy|sell", "code": "sh600000", "qty": 100, "limit_price": 12.8, "reason": "short reason"},
                "cancel_order": {"action": "cancel", "order_id": "preferred when available", "code": "sh600000", "side": "sell", "reason": "short reason"},
                "amend_order": {"action": "amend", "order_id": "preferred when available", "code": "sh600000", "side": "sell", "qty": 100, "limit_price": 12.8, "reason": "short reason"},
                "matching": "Use order_id when possible. Without order_id, code + side must match exactly one active pending order.",
            },
        }

    def ask_ai(self) -> None:
        self.save_ai_config()
        ai = self.store.data.get("ai") or {}
        if not ai.get("api_key"):
            QMessageBox.warning(self, "缺少 API Key", "请先填写 OpenAI-compatible API Key。")
            return
        prompt = (
            "你是 AIStockSim - AI模拟炒股及摸鱼盯盘工具中的交易助手。只输出 JSON 数组，不要输出 Markdown。"
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
            self.store.append_ai_log(
                {
                    "source": "AI 建议",
                    "operator": "AI",
                    "summary": "AI 返回操作建议",
                    "submitted": 0,
                    "cancelled": 0,
                    "amended": 0,
                    "filled": 0,
                    "errors": [],
                    "response": content,
                    "snapshot": self.account_snapshot(),
                }
            )
            self.render_ai_logs()
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

    def write_codex_snapshot(self) -> None:
        try:
            snapshot = self.account_snapshot()
            snapshot["app"] = {"name": APP_NAME, "version": APP_VERSION}
            snapshot["codex_bridge"] = {
                "orders_file": CODEX_ORDER_FILE,
                "snapshot_file": CODEX_SNAPSHOT_FILE,
                "result_file": CODEX_RESULT_FILE,
                "polling": True,
                "schema": snapshot.get("codex_order_schema"),
            }
            save_json(CODEX_SNAPSHOT_FILE, snapshot)
        except Exception:
            return

    def poll_codex_orders(self) -> None:
        if self._closing:
            return
        ensure_config_dir()
        if not os.path.exists(CODEX_ORDER_FILE):
            return
        try:
            mtime = os.path.getmtime(CODEX_ORDER_FILE)
            if mtime <= self._codex_order_mtime:
                return
            self._codex_order_mtime = mtime
            data = load_json(CODEX_ORDER_FILE, [])
            orders = data.get("orders") if isinstance(data, dict) else data
            if not isinstance(orders, list) or not orders:
                return
            actionable = [item for item in orders if isinstance(item, dict) and str(item.get("action") or "hold").lower() != "hold"]
            if not actionable:
                save_json(CODEX_RESULT_FILE, {"time": now_str(), "source": "Codex 本地指令", "summary": "没有可执行指令", "orders": orders})
                save_json(CODEX_ORDER_FILE, [])
                self._codex_order_mtime = os.path.getmtime(CODEX_ORDER_FILE)
                return
            request_id = str(data.get("request_id") or data.get("id") or now_str()) if isinstance(data, dict) else now_str()
            result = self.execute_ai_orders(json.dumps(orders, ensure_ascii=False), "Codex", show_dialog=False)
            save_json(
                CODEX_RESULT_FILE,
                {
                    "time": now_str(),
                    "request_id": request_id,
                    "source": "Codex 本地指令",
                    "result": result,
                    "orders": orders,
                    "snapshot_file": CODEX_SNAPSHOT_FILE,
                },
            )
            save_json(CODEX_ORDER_FILE, [])
            self._codex_order_mtime = os.path.getmtime(CODEX_ORDER_FILE)
            self.status.setText(f"已执行 Codex 本地指令：{(result or {}).get('message', '')}")
        except Exception as exc:
            save_json(
                CODEX_RESULT_FILE,
                {
                    "time": now_str(),
                    "source": "Codex 本地指令",
                    "error": str(exc),
                    "snapshot_file": CODEX_SNAPSHOT_FILE,
                },
            )
            self.status.setText(f"Codex 本地指令执行失败：{exc}")

    def execute_ai_orders(self, text: str, operator: str, show_dialog: bool = True) -> dict[str, Any]:
        try:
            orders = json.loads(text)
            if isinstance(orders, dict):
                orders = orders.get("orders") or []
            if not isinstance(orders, list):
                raise ValueError("JSON 必须是数组，或包含 orders 数组。")
        except Exception as exc:
            self.store.append_ai_log(
                {
                    "source": "JSON 执行",
                    "operator": operator,
                    "summary": "JSON 解析失败",
                    "submitted": 0,
                    "cancelled": 0,
                    "amended": 0,
                    "filled": 0,
                    "errors": [str(exc)],
                    "raw_text": text,
                }
            )
            self.render_ai_logs()
            if show_dialog:
                QMessageBox.warning(self, "JSON 无效", str(exc))
            return {"submitted": 0, "cancelled": 0, "amended": 0, "filled": 0, "errors": [str(exc)], "message": f"JSON 解析失败：{exc}"}

        submitted = 0
        cancelled = 0
        updated = 0
        errors: list[str] = []
        for order in orders:
            if not isinstance(order, dict):
                errors.append(f"跳过无效指令：{order}")
                continue
            action = str(order.get("action") or "hold").lower()
            if action == "hold":
                continue
            order_id = str(order.get("order_id") or order.get("id") or "").strip()
            side = normalize_order_side(order.get("side") or order.get("order_action") or order.get("direction"))
            code = normalize_code(str(order.get("code") or ""))
            reason = str(order.get("reason") or "")

            if action in ("cancel", "cancel_order"):
                try:
                    self.store.cancel_matching_pending_order(order_id, code or "", side, reason)
                except Exception as exc:
                    errors.append(f"cancel: {exc}")
                    continue
                cancelled += 1
                continue

            if action in ("amend", "modify", "update", "replace", "change_price"):
                try:
                    matched_order, match_error = self.store.resolve_active_pending_order(order_id, code or "", side)
                    if match_error or matched_order is None:
                        raise ValueError(match_error or "没有匹配的活动委托。")
                    matched_code = str(matched_order.get("code") or "")
                    quote = self.quote_cache.get(matched_code)
                    if not quote:
                        self.quote_cache.update(self.quotes.fetch([matched_code]))
                        quote = self.quote_cache.get(matched_code)
                    qty_value = order.get("qty")
                    price_value = order.get("limit_price")
                    qty = int(qty_value) if qty_value not in (None, "") else None
                    limit_price = float(price_value) if price_value not in (None, "") else None
                    if qty is None and limit_price is None:
                        raise ValueError("amend/modify 至少需要 qty 或 limit_price。")
                    risk_quote = quote
                    if risk_quote is None:
                        raise ValueError(f"{matched_code}: 暂时无法取得实时价格。")
                    risk_qty = qty if qty is not None else int(matched_order.get("qty") or 0)
                    risk_limit = limit_price if limit_price is not None else float(matched_order.get("limit_price") or 0)
                    risk_errors = self.risk_violations_for_order(
                        str(matched_order.get("action") or ""),
                        risk_quote,
                        int(risk_qty),
                        float(risk_limit),
                        matched_order,
                        check_pending_limit=False,
                    )
                    if risk_errors:
                        raise ValueError("风控拦截：" + "；".join(risk_errors))
                    self.store.update_pending_order(
                        order_id=order_id,
                        code=code or "",
                        action=side,
                        qty=qty,
                        limit_price=limit_price,
                        quote=quote,
                        reason=reason,
                    )
                except Exception as exc:
                    errors.append(f"amend: {exc}")
                    continue
                updated += 1
                continue

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
            risk_errors = self.risk_violations_for_order(action, quote, qty, limit_price)
            if risk_errors:
                errors.append(f"{code}: 风控拦截：" + "；".join(risk_errors))
                continue
            try:
                self.store.add_pending_order(action, quote, qty, limit_price, operator, reason)
            except Exception as exc:
                errors.append(f"{code}: {exc}")
                continue
            submitted += 1
        executed = self.try_execute_pending_orders()
        self.render_all()
        message = f"提交 {submitted} 条，撤单 {cancelled} 条，改价 {updated} 条，成交 {executed} 笔。"
        if errors:
            message += "\n" + "\n".join(errors[:5])
        self.store.append_ai_log(
            {
                "source": "JSON 执行",
                "operator": operator,
                "summary": f"执行完成：{message.splitlines()[0]}",
                "submitted": submitted,
                "cancelled": cancelled,
                "amended": updated,
                "filled": executed,
                "errors": errors,
                "commands": orders,
                "snapshot": self.account_snapshot(),
            }
        )
        self.render_ai_logs()
        if show_dialog:
            QMessageBox.information(self, "AI 执行结果", message)
        return {
            "submitted": submitted,
            "cancelled": cancelled,
            "amended": updated,
            "filled": executed,
            "errors": errors,
            "message": message,
        }


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
