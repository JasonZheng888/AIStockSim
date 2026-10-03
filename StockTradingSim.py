# filename: StockTradingSim.py
# python -m PyInstaller -F -w .\StockTradingSim.py --name StockTradingSim --icon .\StockWidget.ico --add-data ".\StockWidget.ico;."
import datetime as dt
import json
import math
import os
import re
import sys
import winreg
from dataclasses import dataclass
from typing import Any

import requests
import StockWidget as LegacyStockWidget
from app_theme import configure_light_theme
from local_strategy_panel import LocalStrategyPanel
from local_strategy_runtime import quote_freshness_error
from window_state import MainWindowState
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
    QLayout,
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
APP_VERSION = "3.3.0"
DISPLAY_NAME = "AIStockSim - AI模拟炒股及摸鱼盯盘工具"
CONFIG_DIR = os.path.abspath(os.getenv("AISTOCKSIM_DATA_DIR") or os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), APP_NAME))
CONFIG_FILE = os.path.join(CONFIG_DIR, "portfolio.json")
CODEX_ORDER_FILE = os.path.join(CONFIG_DIR, "codex_orders.json")
CODEX_SNAPSHOT_FILE = os.path.join(CONFIG_DIR, "codex_snapshot.json")
CODEX_RESULT_FILE = os.path.join(CONFIG_DIR, "codex_result.json")
CODEX_KLINE_FILE = os.path.join(CONFIG_DIR, "codex_kline_history.json")
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
BACKGROUND_REFRESH_SECONDS = 30
IDLE_REFRESH_SECONDS = 60
CODEX_POLL_SECONDS = 5
MARKET_GATE_CODES = ["sh000001", "sz399001", "sz399006"]
MAX_PENDING_PER_CODE = 3
STRATEGY_LIBRARY = [
    {
        "id": "chan_daily", "name": "缠论日线笔结构（实验）", "group": "独立本地信号",
        "default_enabled": True,
        "definition": "日K包含、分型、严格笔与三笔中枢代理；可选一、二、三类买卖点及背驰结构条件。属于笔级实验代理，不是完整递归缠论。",
        "purpose": "产生可重放、可回测的本地候选，并明确数据、结构、风控和成交各阶段。",
        "inputs": "已收盘日K、结构确认日期、实时有效报价、账户与市场规则。",
        "outputs": "信号ID、确认日、结构失效位、数量与未下单原因。",
        "ai_usage": "先读 strategy_context.local_structure；CAN SLIM评分不是结构买点的必要条件。",
        "hard_rules": ["右侧确认不回填历史买点", "已完成日K确认后形成候选", "保留持仓结构止损退出", "本地模拟自动提交单独设置"],
    },
    {
        "id": "market_gate",
        "name": "市场环境闸门",
        "group": "CAN SLIM - M",
        "default_enabled": False,
        "definition": "先判断大盘与主要指数是否支持做多；市场转弱时，现金也是主动仓位。",
        "purpose": "避免单只股票看似有机会，但处在整体弱市或分化市时盲目开新仓。",
        "inputs": "上证指数、深证成指、创业板指行情与日K；自选股趋势联动。",
        "outputs": "绿色/黄色/红色市场环境观察，说明指数强弱及数据缺项。",
        "ai_usage": "仅在用户启用时参考 strategy_context.market_gate；环境评分不构成下单许可或否决。",
        "hard_rules": ["标明指数样本与数据缺项", "环境评分仅供观察"],
    },
    {
        "id": "canslim_radar",
        "name": "CAN SLIM 价格量能参考",
        "group": "CAN SLIM - C/A/N/S/L/I",
        "default_enabled": False,
        "definition": "用可获得的价格、量能、资金流和相对强弱近似评估 CAN SLIM 七要素；基本面缺失时明确降置信度。",
        "purpose": "把自选股分成领导者、近买点、观察、风险票和弱势剔除，而不是只看今日涨跌。",
        "inputs": "历史日K、MA、RSI、MACD/KDJ、60日强弱、量能、主力资金流、持仓状态。",
        "outputs": "CAN SLIM 分数、分桶、缺失项、领导力和资金需求提示。",
        "ai_usage": "AI 用 strategy_context.canslim_radar 比较候选强弱，缺基本面时不得假装已验证 EPS/营收。",
        "hard_rules": ["不把便宜当买点", "优先当前领导者而非落后补涨"],
    },
    {
        "id": "buy_point_discipline",
        "name": "买点纪律",
        "group": "交易执行",
        "default_enabled": False,
        "definition": "等待有效突破、回踩支撑或均线修复，不在远离枢轴/压力位时追高。",
        "purpose": "让买入理由从“看着涨了”变成“接近可定义风险的买点”。",
        "inputs": "MA20/60、20/60日高低点、压力位、VWAP、量能放大。",
        "outputs": "近买点、偏晚、回踩观察、拒绝追高等执行标签。",
        "ai_usage": "AI 提买入必须说明买点类型、委托价、失效条件和是否已偏离买点。",
        "hard_rules": ["说明买点类型及价格依据", "标明已知失效条件和数据缺项"],
    },
    {
        "id": "sell_discipline",
        "name": "卖出纪律",
        "group": "风险退出",
        "default_enabled": False,
        "definition": "先写退出规则，再谈收益；用 7%-8% 止损、3%-4% 战术风险、20%-25% 盈利保护和支撑破位处理持仓。",
        "purpose": "防止亏损越拖越大，也防止接近 20% 的盈利坐回亏损。",
        "inputs": "持仓成本/摊余回本价、当前价、MA/支撑、成交量、分时 VWAP、可卖数量。",
        "outputs": "止损复核、盈利保护、支撑破位、清仓/减仓观察。",
        "ai_usage": "用户启用时给出持仓盈亏、退出条件及依据；这些观察不禁止继续买入。",
        "hard_rules": ["退出建议说明依据", "区分观察性提示与用户委托"],
    },
    {
        "id": "intraday_vwap_execution",
        "name": "分时/VWAP 执行",
        "group": "交易执行",
        "default_enabled": False,
        "definition": "日K决定是否值得做，分时 VWAP、5/15/30 分钟变化和尾盘信号决定怎么挂单。",
        "purpose": "减少盘中追涨杀跌，让限价委托更贴近可成交和可控风险的位置。",
        "inputs": "当日分时、VWAP/均价线、近5/15/30分钟收益、尾盘抢筹/走弱。",
        "outputs": "站上/低于 VWAP、分时转强/转弱、尾盘信号和执行建议。",
        "ai_usage": "AI 下限价单前必须解释现价与 VWAP/均价线关系；风险退出限价应尽量可成交。",
        "hard_rules": ["短线执行不替代日K方向", "卖出风控不能为了小价差错失成交"],
    },
    {
        "id": "portfolio_risk",
        "name": "组合仓位纪律",
        "group": "组合管理",
        "default_enabled": False,
        "definition": "少数高质量仓位优先，现金可等待；集中度、ST、同主题拥挤和活动委托都要被看见。",
        "purpose": "避免把模拟资金铺满一堆同质弱信号，也避免单票或单主题风险失控。",
        "inputs": "可用现金、冻结资金、持仓权重、ST 标签、活动委托、交易质量。",
        "outputs": "持仓比例、可用现金、冻结资金、活动委托数量和组合观察。",
        "ai_usage": "仅在用户启用时说明持仓分布，不设置比例上限，不禁止ST或持仓加买。",
        "hard_rules": ["使用实际可用资金和可卖数量", "同一证券活动委托最多3条"],
    },
    {
        "id": "review_expectancy",
        "name": "交易复盘与期望值",
        "group": "复盘",
        "default_enabled": False,
        "definition": "用平均收益、平均亏损、规则遵守和最大回撤评价过程，不用单笔胜负评价 AI 或用户。",
        "purpose": "让模拟盘更像训练系统：错了能知道错在哪，对了也能知道是不是侥幸。",
        "inputs": "交易记录、账户曲线、操作者表现、交易质量提示。",
        "outputs": "执行质量、盈亏结构、回撤、可复盘问题。",
        "ai_usage": "AI 报告要说明本轮是否遵守策略，而不是只给涨跌判断。",
        "hard_rules": ["过程比单次对错重要", "频繁检查不等于频繁交易"],
    },
]
DEFAULT_ENABLED_STRATEGY_IDS = [
    item["id"] for item in STRATEGY_LIBRARY if item.get("default_enabled", True)
]
STRATEGY_LIBRARY_BY_ID = {item["id"]: item for item in STRATEGY_LIBRARY}
DEFAULT_AI_PIPELINE = [
    {
        "enabled": True,
        "role": "技术面分析师",
        "inputs": "价格、涨跌幅、趋势、RSI、交易时段",
        "outputs": "技术观点、关键价位、动量风险",
    },
    {
        "enabled": True,
        "role": "策略纪律官",
        "inputs": "已启用策略、本地结构候选及确认日、失效位、执行限制",
        "outputs": "策略匹配度、买点质量、止损/盈利保护、是否允许开新仓",
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


def normalize_compact_display_limit(value: Any) -> int:
    try:
        limit = int(value)
    except Exception:
        return 0
    return max(0, min(99, limit))


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


def parse_order_quantity(value: Any) -> int:
    try:
        numeric = float(value)
        if isinstance(value, bool) or not math.isfinite(numeric) or numeric <= 0 or numeric != int(numeric):
            raise ValueError
        return int(numeric)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("委托数量必须是明确的正整数股数") from None


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


def is_tradable_security(code: str) -> bool:
    """The supported mainland benchmark indices are quotes, not securities."""
    norm = normalize_code(code)
    return bool(norm and not norm.startswith(("sh000", "sz399")))


def buy_quantity_rule(code: str, board_lot: int) -> tuple[int, int, str]:
    if code.startswith("sh688"):
        return 200, 1, "科创板最低 200 股，之后按 1 股递增"
    if code.startswith("hk"):
        return board_lot, board_lot, f"港股按每手 {board_lot} 股买入"
    return board_lot, board_lot, f"{market_name(code)}按每手 {board_lot} 股买入"


def sell_quantity_rule(code: str, board_lot: int, available_qty: int) -> tuple[int, int, str]:
    if code.startswith("sh688") and 0 < available_qty < 200:
        return available_qty, available_qty, f"科创板可卖余额不足 200 股，应一次性卖出剩余 {available_qty} 股"
    return buy_quantity_rule(code, board_lot)


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
    asof_date: str = ""


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


@dataclass
class DailyKLine:
    code: str
    date: str
    open: float
    close: float
    high: float
    low: float
    volume: float
    amount: float
    amplitude: float
    change_pct: float
    change: float
    turnover: float
    source: str


@dataclass
class IntradayPoint:
    code: str
    time: str
    price: float
    volume: float
    amount: float
    avg_price: float
    source: str


def load_cached_daily_klines() -> dict[str, list[DailyKLine]]:
    payload = load_json(CODEX_KLINE_FILE, {})
    if not isinstance(payload, dict):
        return {}
    symbols = payload.get("symbols") or payload.get("stocks") or {}
    if not isinstance(symbols, dict):
        return {}
    cached: dict[str, list[DailyKLine]] = {}

    def as_float(value: Any) -> float:
        try:
            return float(value)
        except Exception:
            return 0.0

    for code, item in symbols.items():
        if not isinstance(item, dict):
            continue
        norm = normalize_code(str(code)) or str(code)
        raw_rows = item.get("klines") or []
        if not isinstance(raw_rows, list):
            continue
        rows: list[DailyKLine] = []
        for raw in raw_rows:
            if not isinstance(raw, dict):
                continue
            row_code = normalize_code(str(raw.get("code") or norm)) or norm
            date_text = str(raw.get("date") or "")
            if not date_text:
                continue
            rows.append(
                DailyKLine(
                    code=row_code,
                    date=date_text,
                    open=as_float(raw.get("open")),
                    close=as_float(raw.get("close")),
                    high=as_float(raw.get("high")),
                    low=as_float(raw.get("low")),
                    volume=as_float(raw.get("volume")),
                    amount=as_float(raw.get("amount")),
                    amplitude=as_float(raw.get("amplitude")),
                    change_pct=as_float(raw.get("change_pct")),
                    change=as_float(raw.get("change")),
                    turnover=as_float(raw.get("turnover")),
                    source=str(raw.get("source") or "本地K线缓存"),
                )
            )
        if rows:
            rows.sort(key=lambda row: row.date)
            cached[norm] = rows
    return cached


def eastmoney_secid(code: str) -> str | None:
    norm = normalize_code(code)
    if not norm:
        return None
    if norm.startswith("hk"):
        return "116." + norm[2:].zfill(5)
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

    def fetch_daily_klines(self, codes: list[str], limit: int = 1000000) -> dict[str, list[DailyKLine]]:
        out: dict[str, list[DailyKLine]] = {}
        requested: list[str] = []
        for code in codes:
            norm = normalize_code(code)
            if norm and norm not in requested:
                requested.append(norm)
        for code in requested:
            rows = self._fetch_daily_kline(code, limit=limit)
            if rows:
                out[code] = rows
        return out

    def fetch_intraday_points(self, codes: list[str]) -> dict[str, list[IntradayPoint]]:
        out: dict[str, list[IntradayPoint]] = {}
        requested: list[str] = []
        for code in codes:
            norm = normalize_code(code)
            if norm and norm not in requested:
                requested.append(norm)
        for code in requested:
            rows = self._fetch_intraday_points(code)
            if rows:
                out[code] = rows
        return out

    def _fetch_intraday_points(self, code: str) -> list[IntradayPoint]:
        secid = eastmoney_secid(code)
        norm = normalize_code(code) or code
        if not secid:
            return []
        try:
            resp = self.session.get(
                "https://push2his.eastmoney.com/api/qt/stock/trends2/get",
                params={
                    "secid": secid,
                    "ndays": "1",
                    "iscr": "0",
                    "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
                    "ut": "fa5fd1943c7b386f172d6893dbfba10b",
                },
                timeout=5,
            )
            payload = resp.json()
            data = (payload or {}).get("data") or {}
            trends = data.get("trends") or []
            rows: list[IntradayPoint] = []
            for raw in trends:
                parts = str(raw).split(",")
                if len(parts) < 2:
                    continue
                numeric = [self._to_float(part) for part in parts[1:]]
                if len(numeric) >= 7:
                    price = numeric[1]
                    volume = numeric[4]
                    amount = numeric[5]
                    avg_price = numeric[6]
                else:
                    price = numeric[0] if numeric else 0.0
                    avg_price = numeric[1] if len(numeric) >= 2 else 0.0
                    volume = numeric[2] if len(numeric) >= 3 else 0.0
                    amount = numeric[3] if len(numeric) >= 4 else 0.0
                if price <= 0:
                    continue
                if avg_price <= 0:
                    avg_price = price
                rows.append(
                    IntradayPoint(
                        code=norm,
                        time=parts[0],
                        price=price,
                        volume=volume,
                        amount=amount,
                        avg_price=avg_price,
                        source="东方财富分时",
                    )
                )
            return rows
        except Exception:
            return []

    def _fetch_daily_kline(self, code: str, limit: int = 1000000) -> list[DailyKLine]:
        secid = eastmoney_secid(code)
        norm = normalize_code(code) or code
        if not secid:
            return []
        try:
            resp = self.session.get(
                "https://push2his.eastmoney.com/api/qt/stock/kline/get",
                params={
                    "secid": secid,
                    "klt": "101",
                    "fqt": "1",
                    "lmt": str(limit),
                    "end": "20500101",
                    "fields1": "f1,f2,f3,f4,f5,f6",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                    "ut": "fa5fd1943c7b386f172d6893dbfba10b",
                },
                timeout=8,
            )
            payload = resp.json()
            data = (payload or {}).get("data") or {}
            klines = data.get("klines") or []
            rows: list[DailyKLine] = []
            truncated = False
            for raw in klines:
                parts = str(raw).split(",")
                if len(parts) < 11:
                    rows.clear()
                    truncated = True
                    continue
                op, close, high, low = [self._to_float(parts[index]) for index in (1, 2, 3, 4)]
                if (not all(math.isfinite(value) and value > 0 for value in (op, close, high, low))
                        or not low <= min(op, close) <= max(op, close) <= high):
                    # Invalid adjusted prices must break the history. Keeping
                    # the bars on both sides would invent continuous structure.
                    rows.clear()
                    truncated = True
                    continue
                rows.append(
                    DailyKLine(
                        code=norm,
                        date=parts[0],
                        open=op,
                        close=close,
                        high=high,
                        low=low,
                        volume=self._to_float(parts[5]),
                        amount=self._to_float(parts[6]),
                        amplitude=self._to_float(parts[7]),
                        change_pct=self._to_float(parts[8]),
                        change=self._to_float(parts[9]),
                        turnover=self._to_float(parts[10]),
                        source="东方财富日K（无效前复权/缺损K线前史已截断）" if truncated else "东方财富日K",
                    )
                )
            return rows
        except Exception:
            return []

    def _fetch_money_flow(self, code: str) -> MoneyFlow | None:
        secid = eastmoney_secid(code)
        norm = normalize_code(code) or ""
        if not secid or norm.startswith("hk"):
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
                timestamp = dt.datetime.fromtimestamp(ts, tz=dt.timezone(dt.timedelta(hours=8))) if ts > 0 else None
                time_label = timestamp.strftime("%H:%M:%S") if timestamp else "-"
                out[code] = Quote(
                    code=code,
                    name=str(item.get("f14") or code),
                    price=price,
                    change=self._to_float(item.get("f4")),
                    change_pct=self._to_float(item.get("f3")),
                    time_label=time_label,
                    source="东方财富",
                    currency="HKD",
                    asof_date=timestamp.date().isoformat() if timestamp else "",
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
            for line in self._decode_sina_response(resp.content).splitlines():
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
        return Quote(code, name, price, change, change_pct, parts[18] or "-", "新浪HK", "HKD",
                     self._normalize_quote_date(parts[17]))

    def _parse_sina_cn(self, code: str, parts: list[str]) -> Quote | None:
        if len(parts) < 32:
            return None
        name = parts[0] or code
        price = self._to_float(parts[3]) or self._to_float(parts[2])
        prev = self._to_float(parts[2])
        change = price - prev if price and prev else 0.0
        change_pct = (price / prev - 1) * 100 if price and prev else 0.0
        return Quote(code, name, price, change, change_pct, parts[31] or "-", "新浪", "CNY",
                     self._normalize_quote_date(parts[30]))

    @staticmethod
    def _decode_sina_response(content: bytes) -> str:
        # Endpoints/proxies can return UTF-8 despite older GBK assumptions.
        # Strict decoding avoids silently accepting corrupted stock names.
        try:
            return content.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError:
            return content.decode("gb18030", errors="strict")

    @staticmethod
    def _normalize_quote_date(value: Any) -> str:
        try:
            return dt.datetime.strptime(str(value).strip().replace("/", "-"), "%Y-%m-%d").date().isoformat()
        except (ValueError, TypeError):
            return ""

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
                "max_pending_per_code": MAX_PENDING_PER_CODE,
            },
            "strategy_settings": {
                "enabled_ids": DEFAULT_ENABLED_STRATEGY_IDS.copy(),
                "active_pack": "chan_daily",
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
        self.risk_config()

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
        # The user retained exactly this fixed order-count limit. Old settings
        # must not resurrect removed price, loss, time or exposure restrictions.
        cfg = {"max_pending_per_code": MAX_PENDING_PER_CODE}
        self.data["risk"] = cfg
        return cfg

    def set_risk_config(self, cfg: dict[str, Any]) -> None:
        self.risk_config()
        self.save()

    def strategy_config(self) -> dict[str, Any]:
        defaults = self._default()["strategy_settings"]
        cfg = self.data.setdefault("strategy_settings", {})
        if not isinstance(cfg, dict):
            cfg = defaults.copy()
            self.data["strategy_settings"] = cfg
        raw_ids = cfg.get("enabled_ids")
        if not isinstance(raw_ids, list):
            raw_ids = defaults["enabled_ids"].copy()
        normalized: list[str] = []
        for item in raw_ids:
            strategy_id = str(item or "")
            if strategy_id in STRATEGY_LIBRARY_BY_ID and strategy_id not in normalized:
                normalized.append(strategy_id)
        cfg["enabled_ids"] = normalized
        # User-requested migration: unrelated legacy strategies start unchecked.
        if cfg.get("local_structure_version") != 2:
            cfg["local_structure_version"] = 2
            cfg["enabled_ids"] = ["chan_daily"]
            cfg["active_pack"] = "chan_daily"
            cfg.setdefault("local_mode", "first_second_third")
            cfg.setdefault("local_auto_submit", False)
        cfg.setdefault("local_mode", "first_second_third")
        cfg.setdefault("active_pack", defaults["active_pack"])
        return cfg

    def enabled_strategy_ids(self) -> list[str]:
        return list(self.strategy_config().get("enabled_ids") or [])

    def is_strategy_enabled(self, strategy_id: str) -> bool:
        return strategy_id in set(self.enabled_strategy_ids())

    def set_strategy_enabled(self, strategy_id: str, enabled: bool) -> None:
        if strategy_id not in STRATEGY_LIBRARY_BY_ID:
            return
        ids = self.enabled_strategy_ids()
        if enabled and strategy_id not in ids:
            ids.append(strategy_id)
        if not enabled:
            ids = [item for item in ids if item != strategy_id]
        cfg = self.strategy_config()
        cfg["enabled_ids"] = ids
        self.save()

    def set_enabled_strategies(self, strategy_ids: list[str]) -> None:
        normalized: list[str] = []
        for strategy_id in strategy_ids:
            if strategy_id in STRATEGY_LIBRARY_BY_ID and strategy_id not in normalized:
                normalized.append(strategy_id)
        cfg = self.strategy_config()
        cfg["enabled_ids"] = normalized
        self.save()

    def reset_strategy_config(self) -> None:
        self.data["strategy_settings"] = self._default()["strategy_settings"]
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
            seen_roles = {str(agent.get("role") or "") for agent in normalized}
            for agent in DEFAULT_AI_PIPELINE:
                role = str(agent.get("role") or "")
                if role and role not in seen_roles:
                    normalized.append(agent.copy())
                    seen_roles.add(role)
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

    def move_watch(self, code: str, delta: int) -> int | None:
        norm = normalize_code(code)
        if not norm:
            return None
        items = self.watchlist
        if norm not in items:
            return None
        old_index = items.index(norm)
        new_index = max(0, min(len(items) - 1, old_index + int(delta)))
        if new_index == old_index:
            return old_index
        item = items.pop(old_index)
        items.insert(new_index, item)
        self.data["watchlist"] = items
        self.save()
        return new_index

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
        if not is_tradable_security(code):
            raise ValueError(f"{code} 为指数或无效代码，仅供观察，不能模拟交易")
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

    def validate_sell_quantity(self, code: str, qty: int, available_qty: int) -> None:
        if not is_tradable_security(code):
            raise ValueError(f"{code} 为指数或无效代码，仅供观察，不能模拟交易")
        min_qty, step, label = sell_quantity_rule(code, self.board_lot(code), int(available_qty))
        if qty < min_qty:
            raise ValueError(f"{label}；当前卖出数量低于最低卖出数量 {min_qty} 股")
        if step > 1 and qty % step != 0:
            raise ValueError(f"{label}；当前卖出数量必须是 {step} 的整数倍")
        if int(available_qty) < 200 and code.startswith("sh688") and qty != int(available_qty):
            raise ValueError(f"{label}；不足 200 股余额不能拆分卖出")

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

    def available_sell_qty(self, code: str, *, local_only: bool = False) -> int:
        pos = self.positions().get(code) or {}
        available = max(0, int(pos.get("available") or 0) - self.reserved_sell_qty(code))
        if local_only:
            local_qty = sum(int(lot.get("qty") or 0) for lot in self.data.get("lots", [])
                            if lot.get("code") == code and lot.get("local_signal_id")
                            and (code.startswith("hk") or str(lot.get("buy_date", today_str())) < today_str()))
            local_reserved = sum(int(order.get("qty") or 0) for order in self.active_pending_orders()
                                 if order.get("code") == code and order.get("action") == "SELL"
                                 and order.get("local_signal_id"))
            available = min(available, max(0, local_qty - local_reserved))
        return available

    def reset(self, initial_cash: float) -> None:
        self.data["cash"] = round(float(initial_cash), 2)
        self.data["initial_cash"] = round(float(initial_cash), 2)
        self.data["lots"] = []
        self.data["trades"] = []
        self.data["pending_orders"] = []
        self.data["position_history"] = []
        self.data["account_history"] = []
        self.save()

    def add_pending_order(self, action: str, quote: Quote, qty: int, limit_price: float, operator: str, reason: str = "", *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        action_name = action.upper()
        qty = parse_order_quantity(qty)
        limit_price = float(limit_price)
        active_count = sum(str(order.get("code") or "") == quote.code for order in self.active_pending_orders())
        if active_count >= MAX_PENDING_PER_CODE:
            raise ValueError(f"{quote.code} 已有 {active_count} 条活动委托，同代码最多 {MAX_PENDING_PER_CODE} 条")
        if action_name not in ("BUY", "SELL") or qty <= 0 or not math.isfinite(limit_price) or limit_price <= 0:
            raise ValueError("委托方向、数量或限价无效")
        if action_name == "BUY":
            self.validate_buy_quantity(quote.code, qty)
            required = round(limit_price * qty, 2)
            available = self.available_cash()
            if required > available + 1e-6:
                raise ValueError(f"可用资金不足；该买入委托需冻结 {money(required, quote.currency)}，当前剩余可用资金 {money(available)}")
        elif action_name == "SELL":
            available_qty = self.available_sell_qty(quote.code, local_only=bool(metadata and metadata.get("local_signal_id")))
            self.validate_sell_quantity(quote.code, qty, available_qty)
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
        for key in ("local_signal_id", "local_auto_event_id", "structure_stop", "signal_date",
                    "signal_confirmed_at", "local_model", "local_submission_kind"):
            if metadata and key in metadata:
                order[key] = metadata[key]
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
        new_qty = parse_order_quantity(qty if qty is not None else order.get("qty"))
        new_limit_price = float(limit_price if limit_price is not None else float(order.get("limit_price") or 0))
        if new_qty <= 0 or not math.isfinite(new_limit_price) or new_limit_price <= 0:
            raise ValueError("Updated qty and limit_price must be greater than 0.")
        if action_name == "BUY":
            self.validate_buy_quantity(target_code, new_qty)
            current_reserved = float(order.get("limit_price") or 0) * int(order.get("qty") or 0)
            available = round(self.cash - self.reserved_cash() + current_reserved, 2)
            required = round(new_limit_price * new_qty, 2)
            if required > available + 1e-6:
                raise ValueError(f"Available cash is not enough for updated buy order; required {required:.2f}, available {available:.2f}.")
        elif action_name == "SELL":
            current_reserved = int(order.get("qty") or 0)
            available_qty = self.available_sell_qty(target_code, local_only=bool(order.get("local_signal_id"))) + current_reserved
            self.validate_sell_quantity(target_code, new_qty, available_qty)
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

    def buy(self, quote: Quote, qty: int, operator: str = "用户", reason: str = "", *, pending_order_id: str = "") -> dict[str, Any]:
        qty = parse_order_quantity(qty)
        self.validate_buy_quantity(quote.code, qty)
        if not math.isfinite(quote.price) or quote.price <= 0:
            raise ValueError("成交价格无效")
        own_order = next((order for order in self.active_pending_orders()
                          if pending_order_id and order.get("id") == pending_order_id
                          and order.get("code") == quote.code and order.get("action") == "BUY"), None)
        own_reserved = float(own_order["limit_price"]) * int(own_order["qty"]) if own_order else 0.0
        cost = quote.price * qty
        if cost > self.cash - self.reserved_cash() + own_reserved + 1e-6:
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
        if own_order:
            lot = self.data["lots"][-1]
            for key in ("local_signal_id", "structure_stop"):
                if key in own_order:
                    lot[key] = own_order[key]
            own_order.update(status="FILLED", filled_at=now_str(), filled_price=round(quote.price, 4))
            own_order.pop("wait_reason", None)
        self.save()
        return trade

    def sell(self, quote: Quote, qty: int, operator: str = "用户", reason: str = "", *, local_only: bool = False, pending_order_id: str = "") -> dict[str, Any]:
        qty = parse_order_quantity(qty)
        if not math.isfinite(quote.price) or quote.price <= 0:
            raise ValueError("成交价格无效")
        eligible_lots = [
            lot for lot in self.data.get("lots", [])
            if lot.get("code") == quote.code
            and int(lot.get("qty") or 0) > 0
            and (not local_only or bool(lot.get("local_signal_id")))
            and (quote.code.startswith("hk") or str(lot.get("buy_date", today_str())) < today_str())
        ]
        available_qty = sum(int(lot.get("qty") or 0) for lot in eligible_lots)
        own_order = next((order for order in self.active_pending_orders()
                          if pending_order_id and order.get("id") == pending_order_id
                          and order.get("code") == quote.code and order.get("action") == "SELL"), None)
        own_reserved = int(own_order["qty"]) if own_order else 0
        available_qty = min(available_qty, self.available_sell_qty(quote.code) + own_reserved)
        local_reserved = sum(int(order.get("qty") or 0) for order in self.active_pending_orders()
                             if order.get("code") == quote.code and order.get("action") == "SELL"
                             and order.get("local_signal_id") and order is not own_order)
        if local_only:
            available_qty = min(available_qty, sum(int(lot["qty"]) for lot in eligible_lots) - local_reserved)
        self.validate_sell_quantity(quote.code, qty, available_qty)
        if qty > available_qty:
            raise ValueError("可卖数量不足；A 股同日买入按 T+1 规则不可卖出，港股支持当日卖出")
        remaining = qty
        proceeds = 0.0
        profit = 0.0
        allocations: list[tuple[dict[str, Any], int]] = []
        local_budget = max(0, sum(int(lot["qty"]) for lot in eligible_lots if lot.get("local_signal_id")) - local_reserved)
        for lot in eligible_lots:
            if remaining <= 0:
                break
            available = int(lot.get("qty") or 0)
            use_qty = min(available, remaining)
            if lot.get("local_signal_id"):
                use_qty = min(use_qty, local_budget)
                local_budget -= use_qty
            allocations.append((lot, available - use_qty))
            remaining -= use_qty
            proceeds += quote.price * use_qty
            breakeven_price = float(lot.get("breakeven_price") or lot.get("buy_price") or 0)
            profit += (quote.price - breakeven_price) * use_qty
        if remaining:
            raise ValueError("可卖数量不足，部分本地策略持仓已由其他卖单冻结")
        # Complete validation/calculation before changing any lot or cash balance.
        for lot, remaining_qty in allocations:
            lot["qty"] = remaining_qty
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
        if own_order:
            own_order.update(status="FILLED", filled_at=now_str(), filled_price=round(quote.price, 4))
            own_order.pop("wait_reason", None)
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
            if code.startswith("hk") or str(lot.get("buy_date", today_str())) < today_str():
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
        self._insert_compact_display_limit_group()
        self._insert_strategy_tab()
        self._rename_global_hotkey_label()
        self._configure_lazy_appearance_sliders()

        self.tabs.setTabText(0, "常规")
        self.tabs.setTabText(1, "风控")
        self.tabs.setTabText(2, "策略组合")
        self.tabs.setTabText(3, "盯盘显示")
        self.tabs.setTabText(4, "盯盘外观")
        self.tab_sizes = {
            0: QSize(520, 430),
            1: QSize(560, 560),
            2: QSize(620, 560),
            3: QSize(500, 450),
            4: QSize(420, 390),
        }
        self._make_pages_scrollable()
        self.tabs.setCurrentIndex(0)
        self._apply_tab_size(0)

    def _make_pages_scrollable(self) -> None:
        # Fixed dialog dimensions must not squeeze nested groups until their
        # checkboxes disappear, especially with Windows display scaling.
        was_blocked = self.tabs.blockSignals(True)
        for index in range(self.tabs.count()):
            content = self.tabs.widget(index)
            if isinstance(content, QScrollArea):
                continue
            title = self.tabs.tabText(index)
            if content.layout() is not None:
                content.layout().setSizeConstraint(QLayout.SetMinimumSize)
            scroll = QScrollArea()
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setWidgetResizable(True)
            self.tabs.removeTab(index)
            scroll.setWidget(content)
            self.tabs.insertTab(index, scroll, title)
        self.tabs.blockSignals(was_blocked)

    def _apply_tab_size(self, index: int) -> None:
        preferred = self.tab_sizes.get(index, QSize(520, 430))
        self.ensure_on_screen(preferred=preferred)
        if self.isVisible():
            # Native frame margins can settle one event after the resize.
            QTimer.singleShot(0, self.ensure_on_screen)

    def _placement_screen(self):
        frame = self.frameGeometry()
        screens = QApplication.screens()
        if self.isVisible() and screens:
            def overlap(screen):
                rect = frame.intersected(screen.availableGeometry())
                return max(0, rect.width()) * max(0, rect.height())
            screen = max(screens, key=overlap)
            if overlap(screen) > 0:
                return screen
        parent = self.parentWidget()
        return (parent.screen() if parent is not None else self.screen()) or QApplication.primaryScreen()

    def ensure_on_screen(self, *, preferred: QSize | None = None, center: bool = False) -> None:
        screen = self._placement_screen()
        if screen is None:
            return
        bounds = screen.availableGeometry().adjusted(12, 12, -12, -12)
        old_frame = self.frameGeometry()
        if preferred is None:
            preferred = self.tab_sizes.get(self.tabs.currentIndex(), QSize(520, 430))
        decoration = QSize(max(0, old_frame.width() - self.width()),
                           max(0, old_frame.height() - self.height()))
        maximum = (bounds.size() - decoration).expandedTo(QSize(1, 1))
        self.setFixedSize(preferred.boundedTo(maximum))
        if not self.isVisible():
            return
        frame = self.frameGeometry()
        target = frame.topLeft()
        if center or not old_frame.intersects(bounds):
            target.setX(bounds.x() + (bounds.width() - frame.width()) // 2)
            target.setY(bounds.y() + (bounds.height() - frame.height()) // 2)
        x = max(bounds.left(), min(target.x(), bounds.right() - frame.width() + 1))
        y = max(bounds.top(), min(target.y(), bounds.bottom() - frame.height() + 1))
        # Translate the existing position by the outer-frame displacement.
        # This includes the title bar and supports monitors at negative x/y.
        self.move(self.x() + x - frame.left(), self.y() + y - frame.top())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._place_after_show)

    def _place_after_show(self) -> None:
        if self.isVisible():
            self.ensure_on_screen(center=not getattr(self, "_has_been_shown", False))
            self._has_been_shown = True

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
        self.owner.store.risk_config()
        risk_box = QGroupBox("委托与账户规则")
        form = QFormLayout(risk_box)
        self.risk_max_pending = QSpinBox()
        self.risk_max_pending.setRange(MAX_PENDING_PER_CODE, MAX_PENDING_PER_CODE)
        self.risk_max_pending.setValue(MAX_PENDING_PER_CODE)
        self.risk_max_pending.setEnabled(False)
        form.addRow("同一证券活动委托最多", self.risk_max_pending)
        detail = QLabel("同一证券的买卖活动委托合计最多 3 条，成交或撤单后释放名额。"
                        "买入按明确股数提交，不因仓位比例或预算自动缩量。"
                        "资金、冻结金额、可卖数量、交易时段、T+1、申报数量和有效行情仍按账户规则校验。")
        detail.setWordWrap(True)
        form.addRow(detail)
        layout.addWidget(risk_box)
        layout.addStretch(1)
        self.tabs.insertTab(1, tab, "委托规则")

    def _insert_compact_display_limit_group(self) -> None:
        display_tab = self.tabs.widget(2)
        layout = display_tab.layout() if display_tab is not None else None
        if layout is None:
            return

        limit_box = QGroupBox("展示范围")
        limit_layout = QVBoxLayout(limit_box)
        limit_layout.setContentsMargins(10, 14, 10, 10)

        row = QHBoxLayout()
        self.compact_display_limit_spin = QSpinBox()
        self.compact_display_limit_spin.setRange(0, 99)
        self.compact_display_limit_spin.setSpecialValueText("全部")
        self.compact_display_limit_spin.setValue(self.owner.compact_display_limit())
        self.compact_display_limit_spin.setFixedWidth(90)
        self.compact_display_limit_spin.valueChanged.connect(self._on_compact_display_limit_changed)

        row.addWidget(QLabel("盯盘模式展示数量："))
        row.addWidget(self.compact_display_limit_spin)
        row.addStretch(1)
        limit_layout.addLayout(row)

        hint = QLabel("按主界面自选股当前顺序取前 X 个；设为“全部”时不限制。可在“行情交易”页用上移/下移调整顺序。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666;")
        limit_layout.addWidget(hint)
        layout.insertWidget(0, limit_box)

    def _insert_strategy_tab(self) -> None:
        tab = QScrollArea()
        tab.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        tab.setWidget(content)

        intro = QLabel(
            "这里控制本地策略库。勾选后的策略会写入 strategy_context，供用户查看，也供第一次接入的 AI 快速理解交易纪律。"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #555;")
        layout.addWidget(intro)

        controls = QHBoxLayout()
        enable_all = QPushButton("全部启用")
        reset_default = QPushButton("恢复默认组合")
        enable_all.clicked.connect(self._enable_all_strategies)
        reset_default.clicked.connect(self._reset_strategy_defaults)
        controls.addWidget(enable_all)
        controls.addWidget(reset_default)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.strategy_checkboxes: dict[str, QCheckBox] = {}
        enabled_ids = set(self.owner.store.enabled_strategy_ids())
        for strategy in STRATEGY_LIBRARY:
            box = QGroupBox(f"{strategy['name']} - {strategy['group']}")
            box_layout = QVBoxLayout(box)
            check = QCheckBox("启用该策略")
            check.setChecked(str(strategy["id"]) in enabled_ids)
            box_layout.addWidget(check)

            detail = QLabel(
                f"定义：{strategy['definition']}\n"
                f"作用：{strategy['purpose']}\n"
                f"输入：{strategy['inputs']}\n"
                f"输出：{strategy['outputs']}\n"
                f"AI 调用：{strategy['ai_usage']}\n"
                f"硬规则：{'；'.join(strategy.get('hard_rules') or [])}"
            )
            detail.setWordWrap(True)
            detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
            detail.setStyleSheet("color: #444; line-height: 1.25;")
            box_layout.addWidget(detail)

            strategy_id = str(strategy["id"])
            self.strategy_checkboxes[strategy_id] = check
            check.toggled.connect(lambda checked, sid=strategy_id: self._on_strategy_toggled(sid, checked))
            layout.addWidget(box)

        layout.addStretch(1)
        self.tabs.insertTab(2, tab, "策略组合")

    def _on_risk_changed(self, *_args: Any) -> None:
        self.owner.store.set_risk_config({"max_pending_per_code": MAX_PENDING_PER_CODE})
        self.owner.render_all()

    def _on_strategy_toggled(self, strategy_id: str, checked: bool) -> None:
        self.owner.store.set_strategy_enabled(strategy_id, checked)
        self.owner.render_all()

    def _enable_all_strategies(self) -> None:
        self.owner.store.set_enabled_strategies([str(item["id"]) for item in STRATEGY_LIBRARY])
        for strategy_id, checkbox in getattr(self, "strategy_checkboxes", {}).items():
            checkbox.blockSignals(True)
            checkbox.setChecked(True)
            checkbox.blockSignals(False)
        self.owner.render_all()

    def _reset_strategy_defaults(self) -> None:
        self.owner.store.reset_strategy_config()
        enabled_ids = set(self.owner.store.enabled_strategy_ids())
        for strategy_id, checkbox in getattr(self, "strategy_checkboxes", {}).items():
            checkbox.blockSignals(True)
            checkbox.setChecked(strategy_id in enabled_ids)
            checkbox.blockSignals(False)
        self.owner.render_all()

    def _rename_global_hotkey_label(self) -> None:
        for label in self.findChildren(QLabel):
            if label.text() == "隐藏/显示浮窗：":
                label.setText("显示/隐藏当前界面：")
                break

    def _configure_lazy_appearance_sliders(self) -> None:
        slider_specs = [
            ("slider_bg_alpha", "lbl_bg_alpha", lambda v: f"{v}%"),
            ("slider_win_opacity", "lbl_win_opacity", lambda v: f"{v}%"),
            ("slider_font", "lbl_font", lambda v: f"{v} pt"),
            ("slider_line", "lbl_line", lambda v: f"+{v} px"),
        ]
        for slider_name, label_name, formatter in slider_specs:
            slider = getattr(self, slider_name, None)
            label = getattr(self, label_name, None)
            if slider is None or label is None:
                continue
            slider.setTracking(False)
            slider.sliderMoved.connect(lambda value, lbl=label, fmt=formatter: lbl.setText(fmt(value)))

    def _on_global_interval_changed(self, _idx: int) -> None:
        seconds = self.global_interval_combo.currentData()
        if isinstance(seconds, int):
            self.owner.set_refresh_interval(seconds)

    def _on_compact_display_limit_changed(self, value: int) -> None:
        self.owner.set_compact_display_limit(value)


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
        self.daily_kline_cache: dict[str, list[DailyKLine]] = load_cached_daily_klines()
        self.intraday_cache: dict[str, list[IntradayPoint]] = {}
        self._money_flow_last_fetch: dt.datetime | None = None
        self._daily_kline_last_fetch: dt.datetime | None = dt.datetime.now() if self.daily_kline_cache else None
        self._intraday_last_fetch: dt.datetime | None = None
        self.price_history: dict[str, list[tuple[str, float]]] = {}
        self.compact_window: LegacyCompactWindow | None = None
        self._settings_dialog = None
        self._compact_mode_active = False
        self._suppress_compact_restore = False
        self._tray_menu_open = False
        self._compact_timer_was_active = False
        self._compact_top_timer_was_active = False
        self._closing = False
        self._startup_light_refresh = True
        self._last_snapshot_write: dt.datetime | None = None
        self._pending_page_render = False
        self._app_icon_choice = load_compact_config().get("app_icon")
        self._codex_order_mtime = 0.0

        self._build_ui()
        self._build_tray()
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.save_main_window_state)
            app.aboutToQuit.connect(self.shutdown_compact)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.refresh_quotes(auto=True))
        self.timer.start(self.store.refresh_seconds * 1000)
        self.codex_timer = QTimer(self)
        self.codex_timer.timeout.connect(self.poll_codex_orders)
        self.codex_timer.start(CODEX_POLL_SECONDS * 1000)
        self.status.setText("已加载本地账户和历史K缓存，稍后自动刷新行情...")
        QTimer.singleShot(700, lambda: self.refresh_quotes(auto=True))
        QTimer.singleShot(1800, self.preload_compact_window)
        QTimer.singleShot(12000, self.refresh_stale_daily_klines)
        self._main_window_state = MainWindowState(self, self.store.data.get("main_window"))

    def show_restored_window(self) -> None:
        self._main_window_state.show_restored()

    def save_main_window_state(self) -> None:
        state = getattr(self, "_main_window_state", None)
        if state is not None:
            self.store.data["main_window"] = state.snapshot()
            self.store.save()

    def closeEvent(self, event) -> None:
        event.ignore()
        self.quit_app()

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
        subtitle = QLabel(f"{APP_VERSION} · 浅色模式")
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
        self.set_auto_timer_seconds(self.store.refresh_seconds)
        self.page_stack.setCurrentIndex(row)
        meta = self.nav_meta[row]
        self.page_title.setText(meta["label"])
        self.page_hint.setText(meta["hint"])
        self.schedule_current_page_render()

    def schedule_current_page_render(self) -> None:
        if getattr(self, "_pending_page_render", False):
            return
        self._pending_page_render = True
        QTimer.singleShot(0, self._flush_current_page_render)

    def _flush_current_page_render(self) -> None:
        self._pending_page_render = False
        self.render_account()
        self.render_current_page()

    def render_current_page(self) -> None:
        if not hasattr(self, "nav_list"):
            return
        row = self.nav_list.currentRow()
        label = self.nav_meta[row]["label"] if 0 <= row < len(self.nav_meta) else ""
        if label == "总览":
            self.render_overview()
        elif label == "行情交易":
            self.render_market()
            self.render_pending_orders()
        elif label == "持仓":
            self.render_positions()
            self.render_position_analysis()
        elif label == "AI 工作台":
            self.render_agent_report()
            self.render_agent_pipeline()
            self.render_agent_report_center()
            self.render_agent_commands()
            self.render_rebalance_suggestions()
            self.render_agent_chat()
        elif label == "复盘":
            self.render_review()
        elif label == "策略":
            self.render_strategy_workspace()
        elif label == "日志":
            self.render_trades()
            self.render_ai_logs()
        elif label == "AI 设置":
            pass

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
        self.overview_positions_table.setHorizontalHeaderLabels(["代码", "名称", "持仓", "可卖", "仓位", "浮盈亏", "摊余回本价"])
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
        move_up_btn = QPushButton("上移")
        move_down_btn = QPushButton("下移")
        add_btn.clicked.connect(self.add_watch)
        remove_btn.clicked.connect(self.remove_selected_watch)
        move_up_btn.clicked.connect(lambda: self.move_selected_watch(-1))
        move_down_btn.clicked.connect(lambda: self.move_selected_watch(1))
        controls.addWidget(self.code_input, 1)
        controls.addWidget(add_btn)
        controls.addWidget(remove_btn)
        controls.addWidget(move_up_btn)
        controls.addWidget(move_down_btn)
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
            ["代码", "名称", "持仓", "可卖", "当前持仓成本", "摊余回本价", "现价", "市值", "回本盈亏", "回本率"]
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
            ["代码", "名称", "持仓天数", "持仓", "当前持仓成本", "摊余回本价", "现价", "回本盈亏", "已实现", "总收益", "回本率", "买入次数", "卖出次数"]
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
            ["日期", "时间", "代码", "名称", "持仓", "当前持仓成本", "摊余回本价", "现价", "市值", "回本盈亏", "回本率"]
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

        self.local_strategy_panel = LocalStrategyPanel(self)
        layout.addWidget(self.local_strategy_panel)

        catalog_box = QGroupBox("策略组合目录")
        catalog_layout = QVBoxLayout(catalog_box)
        catalog_hint = QLabel("这些策略可在“设置 - 策略组合”中启用/停用；启用项会写入 strategy_context，供用户和外部 AI 同步读取。")
        catalog_hint.setWordWrap(True)
        catalog_layout.addWidget(catalog_hint)
        self.strategy_catalog_table = QTableWidget(0, 6)
        self.strategy_catalog_table.setHorizontalHeaderLabels(["策略", "状态", "组合", "定义/作用", "输入/输出", "AI 调用方式"])
        self.strategy_catalog_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.strategy_catalog_table.horizontalHeader().setStretchLastSection(True)
        self.strategy_catalog_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.strategy_catalog_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.strategy_catalog_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.strategy_catalog_table.verticalHeader().setDefaultSectionSize(34)
        self.strategy_catalog_table.setMinimumHeight(34 * 6 + self.strategy_catalog_table.horizontalHeader().height() + 18)
        catalog_layout.addWidget(self.strategy_catalog_table)
        layout.addWidget(catalog_box)

        canslim_box = QGroupBox("CAN SLIM 价格量能参考（与缠论独立）")
        canslim_layout = QVBoxLayout(canslim_box)
        canslim_hint = QLabel("按市场闸门、趋势、相对强弱、资金需求、买点质量和卖出纪律给自选/持仓分桶。基本面未接入时会明确标记缺项。")
        canslim_hint.setWordWrap(True)
        canslim_layout.addWidget(canslim_hint)
        self.strategy_canslim_table = QTableWidget(0, 11)
        self.strategy_canslim_table.setHorizontalHeaderLabels(
            ["代码", "名称", "分桶", "评分", "灯号", "市场", "相对强弱", "买点/执行", "资金/证据", "风控/缺项", "建议"]
        )
        self.strategy_canslim_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.strategy_canslim_table.horizontalHeader().setStretchLastSection(True)
        self.strategy_canslim_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.strategy_canslim_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.strategy_canslim_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.strategy_canslim_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.strategy_canslim_table.verticalHeader().setDefaultSectionSize(36)
        self.strategy_canslim_table.setMinimumHeight(36 * 6 + self.strategy_canslim_table.horizontalHeader().height() + 18)
        canslim_layout.addWidget(self.strategy_canslim_table)
        layout.addWidget(canslim_box, 1)

        matrix_box = QGroupBox("策略信号矩阵")
        matrix_layout = QVBoxLayout(matrix_box)
        matrix_hint = QLabel("矩阵按自选股和持仓合并展示，便于对比趋势、RSI、资金流、仓位风险和未成交委托。")
        matrix_hint.setWordWrap(True)
        matrix_layout.addWidget(matrix_hint)
        self.strategy_signal_table = QTableWidget(0, 18)
        self.strategy_signal_table.setHorizontalHeaderLabels(
            ["代码", "名称", "最新价", "涨跌幅", "K线样本", "趋势", "分时", "均线", "RSI", "MACD", "KDJ", "量能", "支撑", "压力", "资金流", "风控", "仓位", "活动委托"]
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

        self.ai_log_table = QTableWidget(0, 9)
        self.ai_log_table.setHorizontalHeaderLabels(
            ["时间", "来源", "操作者", "摘要", "提交", "撤单", "改价", "成交", "错误"]
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

        self.ai_log_table = QTableWidget(0, 9)
        self.ai_log_table.setHorizontalHeaderLabels(
            ["时间", "来源", "操作者", "摘要", "提交", "撤单", "改价", "成交", "错误"]
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
            QMainWindow { background: #f7f8fa; color: #17202a; }
            #NavPanel { background: #202833; border-right: 1px solid #131820; }
            #BrandTitle { color: #ffffff; font-size: 19px; font-weight: 700; }
            #BrandSubtitle { color: #aeb8c6; font-size: 12px; }
            #MainNav { background: transparent; border: 0; color: #dfe6ee; font-size: 14px; }
            #MainNav::item { padding: 10px 9px; border-radius: 5px; }
            #MainNav::item:hover { background: #344255; }
            #MainNav::item:selected { background: #2563eb; color: #ffffff; }
            #PageTitle { font-size: 20px; font-weight: 700; color: #17202a; }
            #PageHint { color: #697386; font-size: 13px; }
            #SectionTitle { font-size: 16px; font-weight: 700; color: #17202a; margin-top: 8px; }
            #MetricCard { background: #ffffff; border: 1px solid #d6dae0; border-radius: 6px; }
            #MetricTitle { color: #6b7280; font-size: 12px; }
            #MetricValue { color: #17202a; font-size: 19px; font-weight: 700; }
            #MetricHint { color: #697386; font-size: 12px; }
            QGroupBox { color: #17202a; font-weight: 600; border: 1px solid #d6dae0; border-radius: 6px; margin-top: 12px; padding: 10px; background: #ffffff; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QTableWidget { color: #17202a; background: #ffffff; alternate-background-color: #f1f5f9; selection-background-color: #2563eb; selection-color: #ffffff; border: 1px solid #d6dae0; gridline-color: #edf0f3; }
            QHeaderView::section { color: #374151; background: #eef2f7; border: 0; border-right: 1px solid #d6dae0; border-bottom: 1px solid #d6dae0; padding: 5px; }
            QPushButton { color: #17202a; padding: 6px 12px; border: 1px solid #b8c0cc; border-radius: 5px; background: #ffffff; }
            QPushButton:hover { background: #f0f4f8; }
            QPushButton:pressed, QPushButton:checked { background: #dbeafe; border-color: #2563eb; }
            QPushButton:focus { border-color: #2563eb; }
            QLineEdit, QPlainTextEdit { color: #17202a; padding: 5px; border: 1px solid #b8c0cc; border-radius: 4px; background: #ffffff; selection-background-color: #2563eb; selection-color: #ffffff; }
            QLineEdit:focus, QPlainTextEdit:focus { border-color: #2563eb; }
            QSpinBox, QDoubleSpinBox, QComboBox { min-height: 28px; }
            QComboBox QAbstractItemView { color: #17202a; background: #ffffff; selection-background-color: #2563eb; selection-color: #ffffff; }
            QPushButton:disabled, QLineEdit:disabled, QPlainTextEdit:disabled { color: #697386; background: #f1f5f9; border-color: #d6dae0; }
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
            if self._settings_dialog.isMinimized():
                self._settings_dialog.showNormal()
            self._settings_dialog.ensure_on_screen()
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

    def compact_display_limit(self) -> int:
        cfg = load_compact_config()
        return normalize_compact_display_limit(cfg.get("display_limit", 0))

    def _compact_checked_codes(
        self,
        watchlist: list[str],
        show_all: bool = False,
        current_checked: list[str] | None = None,
        limit: int | None = None,
    ) -> list[str]:
        display_limit = self.compact_display_limit() if limit is None else normalize_compact_display_limit(limit)
        if display_limit > 0:
            return watchlist[:display_limit] or watchlist
        if show_all:
            return watchlist
        checked = [c for c in (current_checked or []) if c in watchlist]
        return checked or watchlist

    def set_compact_display_limit(self, limit: int) -> None:
        display_limit = normalize_compact_display_limit(limit)
        cfg = self.compact_window.current_config() if self.compact_window is not None else load_compact_config()
        cfg["display_limit"] = display_limit
        cfg["refresh_seconds"] = self.store.refresh_seconds
        cfg["app_icon"] = getattr(self, "_app_icon_choice", None)
        save_compact_config_file(cfg)
        if self.compact_window is not None:
            self.sync_compact_watchlist(show_all=True)
        label = "全部" if display_limit == 0 else f"前 {display_limit} 只"
        self.status.setText(f"盯盘模式展示范围已设置为：{label}")

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
            display_limit = normalize_compact_display_limit(cfg.get("display_limit", 0))
            cfg["codes"] = self.store.watchlist
            cfg["refresh_seconds"] = self.store.refresh_seconds
            cfg["display_limit"] = display_limit
            cfg["checked_codes"] = self._compact_checked_codes(
                self.store.watchlist,
                show_all=True,
                current_checked=cfg.get("checked_codes", self.store.watchlist),
                limit=display_limit,
            )
            cfg.setdefault("price_visible", True)
            cfg.setdefault("change_pct_visible", True)
            self.compact_window = LegacyCompactWindow(self, cfg)
            self.compact_window.set_on_change(lambda: self.save_compact_config(refresh_quotes=False))
            self.compact_window.set_open_settings_callback(self.open_main_settings)
            return True
        return False

    def sync_compact_watchlist(self, show_all: bool = False) -> None:
        if self.compact_window is None:
            return
        watchlist = self.store.watchlist
        checked = self._compact_checked_codes(
            watchlist,
            show_all=show_all,
            current_checked=list(self.compact_window.checked_codes),
        )
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
        cfg["display_limit"] = self.compact_display_limit()
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
        panel = getattr(self, "local_strategy_panel", None)
        worker = getattr(panel, "worker", None)
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            self.status.setText("正在停止离线回测，完成当前股票后退出…")
            QTimer.singleShot(200, self.quit_app)
            return
        self.save_main_window_state()
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

    def move_selected_watch(self, delta: int) -> None:
        code = self.selected_market_code()
        if not code:
            return
        new_row = self.store.move_watch(code, delta)
        if new_row is None:
            return
        self.sync_compact_watchlist(show_all=True)
        self.render_market()
        self.render_overview()
        self.render_strategy_workspace()
        self.write_codex_snapshot()
        if self.market_table.rowCount():
            self.market_table.selectRow(max(0, min(new_row, self.market_table.rowCount() - 1)))
        direction = "上移" if delta < 0 else "下移"
        self.status.setText(f"自选股已{direction}：{code}")

    def reset_account(self) -> None:
        dialog = InitialCapitalDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.store.reset(dialog.value())
            self.refresh_quotes()

    def active_market_for_codes(self, codes: list[str]) -> bool:
        for code in codes:
            norm = normalize_code(code or "")
            if not norm:
                continue
            if trading_time_error(norm) is None:
                return True
        return False

    def ui_foreground_active(self) -> bool:
        compact_visible = self.compact_window is not None and self.compact_window.isVisible()
        if compact_visible:
            try:
                if self.compact_window.isActiveWindow():
                    return True
            except Exception:
                pass
        if self.isVisible() and not self.isMinimized():
            return bool(self.isActiveWindow())
        return False

    def set_auto_timer_seconds(self, seconds: int) -> None:
        if not hasattr(self, "timer"):
            return
        ms = max(1, int(seconds)) * 1000
        if self.timer.interval() != ms:
            self.timer.setInterval(ms)

    def auto_refresh_skip_reason(self, codes: list[str]) -> str | None:
        compact_visible = self.compact_window is not None and self.compact_window.isVisible()
        if compact_visible:
            self.set_auto_timer_seconds(self.store.refresh_seconds)
            return None
        if self.store.active_pending_orders():
            self.set_auto_timer_seconds(self.store.refresh_seconds)
            return None
        if not self.active_market_for_codes(codes):
            self.set_auto_timer_seconds(IDLE_REFRESH_SECONDS)
            return f"非交易时段，自动刷新降频到 {IDLE_REFRESH_SECONDS} 秒"
        if not self.ui_foreground_active():
            self.set_auto_timer_seconds(BACKGROUND_REFRESH_SECONDS)
            return None
        self.set_auto_timer_seconds(self.store.refresh_seconds)
        return None

    def refresh_quotes(self, auto: bool = False) -> None:
        pending_codes = [str(order.get("code") or "") for order in self.store.active_pending_orders()]
        codes = self.store.watchlist + list(self.store.positions().keys()) + pending_codes + MARKET_GATE_CODES
        if not auto:
            self.set_auto_timer_seconds(self.store.refresh_seconds)
        if auto:
            skip_reason = self.auto_refresh_skip_reason(codes)
            if skip_reason:
                self.status.setText(f"{skip_reason}：{now_str()}")
                return
        try:
            fetched = self.quotes.fetch(codes)
            self.quote_cache.update(fetched)
            self.record_price_history(fetched)
            light_startup = bool(auto and getattr(self, "_startup_light_refresh", False))
            if light_startup:
                now = dt.datetime.now()
                self._startup_light_refresh = False
                self._money_flow_last_fetch = now
                self._intraday_last_fetch = now
            else:
                self.refresh_money_flows(codes, force=not auto)
                self.refresh_daily_klines(codes, force=not auto)
                self.refresh_intraday_points(codes, force=not auto)
            executed = self.try_execute_pending_orders()
            self.local_strategy_panel.on_quotes_refreshed()
            mode = "启动轻量刷新" if light_startup else "自动刷新" if auto else "手动刷新"
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

    def refresh_daily_klines(self, codes: list[str], force: bool = False) -> None:
        now = dt.datetime.now()
        if not force and self._daily_kline_last_fetch is not None:
            if (now - self._daily_kline_last_fetch).total_seconds() < 20:
                return
        # Per-symbol freshness and rotating bounded batches prevent a large
        # watchlist (or a failing first symbol) from starving later symbols.
        universe = list(dict.fromkeys(norm for code in codes if (norm := normalize_code(code))))
        fetched_at = getattr(self, "_daily_kline_fetched_at", {})
        attempted_at = getattr(self, "_daily_kline_attempted_at", {})
        self._daily_kline_fetched_at = fetched_at
        self._daily_kline_attempted_at = attempted_at
        requested: list[str] = []
        start = getattr(self, "_daily_kline_cursor", 0) % len(universe) if universe else 0
        for offset in range(len(universe)):
            index = (start + offset) % len(universe)
            code = universe[index]
            successful = fetched_at.get(code)
            attempted = attempted_at.get(code)
            if not force and successful and (now - successful).total_seconds() < 1800:
                continue
            if not force and attempted and (now - attempted).total_seconds() < 60:
                continue
            requested.append(code)
            self._daily_kline_cursor = (index + 1) % len(universe)
            if not force and len(requested) >= 4:
                break
        if not requested:
            return
        self._daily_kline_last_fetch = now
        for code in requested:
            attempted_at[code] = now
        try:
            rows = self.quotes.fetch_daily_klines(requested)
            if rows:
                self.daily_kline_cache.update(rows)
                for code, bars in rows.items():
                    if bars:
                        fetched_at[code] = now
                self.write_codex_kline_history()
        except Exception:
            return

    def refresh_stale_daily_klines(self) -> None:
        if self._closing:
            return
        codes = self.store.watchlist + list(self.store.positions().keys()) + MARKET_GATE_CODES
        self._daily_kline_last_fetch = None
        self.refresh_daily_klines(codes, force=False)
        self.write_codex_snapshot(force=True)

    def refresh_intraday_points(self, codes: list[str], force: bool = False) -> None:
        now = dt.datetime.now()
        if not force and self._intraday_last_fetch is not None:
            if (now - self._intraday_last_fetch).total_seconds() < max(20, self.store.refresh_seconds):
                return
        universe = list(dict.fromkeys(norm for code in codes if (norm := normalize_code(code))))
        start = getattr(self, "_intraday_cursor", 0) % len(universe) if universe else 0
        rotated = universe[start:] + universe[:start]
        requested = rotated if force else rotated[:4]
        if not requested:
            return
        self._intraday_cursor = (start + len(requested)) % len(universe)
        self._intraday_last_fetch = now
        try:
            rows = self.quotes.fetch_intraday_points(requested)
            if rows:
                self.intraday_cache.update(rows)
        except Exception:
            return

    def render_all(self) -> None:
        self.render_account()
        self.render_current_page()
        self.write_codex_snapshot()

    def overview_risk_summary(self, positions: dict[str, dict[str, Any]], summary: dict[str, float]) -> tuple[str, float]:
        counts: dict[str, int] = {}
        for order in self.store.active_pending_orders():
            code = str(order.get("code") or "")
            counts[code] = counts.get(code, 0) + 1
        full = [f"{code} 活动委托 {count}/{MAX_PENDING_PER_CODE}" for code, count in counts.items()
                if count >= MAX_PENDING_PER_CODE]
        if full:
            return "；".join(full[:4]), -1.0
        return f"活动委托 {sum(counts.values())} 条；可用资金 {money(summary.get('available_cash', self.store.available_cash()))}", 0.0

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

    def daily_kline_dicts(self, code: str, limit: int | None = None) -> list[dict[str, Any]]:
        rows = self.daily_kline_cache.get(normalize_code(code) or code) or []
        selected = rows[-limit:] if limit else rows
        return [item.__dict__.copy() for item in selected]

    def historical_data_summary(self) -> dict[str, Any]:
        symbols: dict[str, dict[str, Any]] = {}
        for code, rows in self.daily_kline_cache.items():
            symbols[code] = {
                "sample_count": len(rows),
                "first_date": rows[0].date if rows else "",
                "last_date": rows[-1].date if rows else "",
                "latest_close": round(float(rows[-1].close), 4) if rows else None,
            }
        return {
            "daily_kline_loaded": bool(symbols),
            "daily_kline_file": CODEX_KLINE_FILE,
            "daily_kline_format": "JSON path: symbols[code].klines[]",
            "daily_kline_note": "完整历史日K单独落盘；snapshot 内只保留技术摘要。AI 做策略分析时应优先结合 daily_technical_profiles 与该文件的完整K线。",
            "symbols": symbols,
        }

    @staticmethod
    def avg(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    def daily_rsi_value(self, closes: list[float], period: int = 14) -> float | None:
        if len(closes) <= period:
            return None
        changes = [closes[i] - closes[i - 1] for i in range(len(closes) - period, len(closes))]
        gains = [change for change in changes if change > 0]
        losses = [-change for change in changes if change < 0]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - 100 / (1 + rs)

    def ema_series(self, values: list[float], period: int) -> list[float]:
        if not values:
            return []
        alpha = 2 / (period + 1)
        out = [float(values[0])]
        for value in values[1:]:
            out.append(float(value) * alpha + out[-1] * (1 - alpha))
        return out

    def macd_profile(self, closes: list[float]) -> dict[str, Any]:
        if len(closes) < 35:
            return {"status": "样本不足"}
        ema12 = self.ema_series(closes, 12)
        ema26 = self.ema_series(closes, 26)
        diffs = [a - b for a, b in zip(ema12, ema26)]
        dea = self.ema_series(diffs, 9)
        if len(diffs) < 2 or len(dea) < 2:
            return {"status": "样本不足"}
        dif = diffs[-1]
        signal = dea[-1]
        hist = (dif - signal) * 2
        prev_dif = diffs[-2]
        prev_dea = dea[-2]
        if prev_dif <= prev_dea and dif > signal:
            label = "金叉"
        elif prev_dif >= prev_dea and dif < signal:
            label = "死叉"
        elif dif > signal:
            label = "多方区"
        else:
            label = "空方区"
        return {"status": label, "dif": round(dif, 4), "dea": round(signal, 4), "hist": round(hist, 4)}

    def kdj_profile(self, highs: list[float], lows: list[float], closes: list[float], period: int = 9) -> dict[str, Any]:
        if len(closes) < period:
            return {"status": "样本不足"}
        k = 50.0
        d = 50.0
        for index in range(len(closes)):
            start = max(0, index - period + 1)
            high = max(highs[start : index + 1])
            low = min(lows[start : index + 1])
            rsv = 50.0 if high <= low else (closes[index] - low) / (high - low) * 100
            k = k * 2 / 3 + rsv / 3
            d = d * 2 / 3 + k / 3
        j = 3 * k - 2 * d
        if j >= 100:
            status = "超买"
        elif j <= 0:
            status = "超卖"
        elif k > d:
            status = "偏强"
        else:
            status = "偏弱"
        return {"status": status, "k": round(k, 2), "d": round(d, 2), "j": round(j, 2)}

    def technical_profile(self, code: str) -> dict[str, Any]:
        norm = normalize_code(code) or code
        rows = self.daily_kline_cache.get(norm) or []
        if not rows:
            return {"status": "历史K采样中", "code": norm, "sample_count": 0}
        valid_rows = [
            item for item in rows
            if float(item.close) > 0 and float(item.high) > 0 and float(item.low) > 0
        ]
        closes = [float(item.close) for item in valid_rows]
        highs = [float(item.high) for item in valid_rows]
        lows = [float(item.low) for item in valid_rows]
        volumes = [float(item.volume) for item in valid_rows if item.volume >= 0]
        if not closes:
            return {"status": "历史K采样中", "code": norm, "sample_count": len(rows), "valid_sample_count": 0}
        close = closes[-1]
        periods = [5, 10, 20, 60, 120, 250]
        mas = {
            f"ma{period}": round(self.avg(closes[-period:]), 4) if len(closes) >= period else None
            for period in periods
        }
        ma5 = mas.get("ma5")
        ma10 = mas.get("ma10")
        ma20 = mas.get("ma20")
        ma60 = mas.get("ma60")
        if ma5 and ma10 and ma20 and ma60 and ma5 > ma10 > ma20 > ma60:
            ma_status = "多头排列"
        elif ma5 and ma10 and ma20 and ma60 and ma5 < ma10 < ma20 < ma60:
            ma_status = "空头排列"
        elif ma20 and close >= ma20:
            ma_status = "站上MA20"
        elif ma20:
            ma_status = "跌破MA20"
        else:
            ma_status = "均线样本不足"

        recent_20 = valid_rows[-20:] if len(valid_rows) >= 20 else valid_rows
        recent_60 = valid_rows[-60:] if len(valid_rows) >= 60 else valid_rows
        completed_60 = [item for item in valid_rows if str(item.date) < today_str()][-60:]
        support_candidates = [float(item.low) for item in recent_60 if 0 < float(item.low) <= close]
        resistance_candidates = [float(item.high) for item in recent_60 if float(item.high) >= close]
        support = max(support_candidates) if support_candidates else min(lows[-60:] if len(lows) >= 60 else lows)
        resistance = min(resistance_candidates) if resistance_candidates else max(highs[-60:] if len(highs) >= 60 else highs)
        prev = valid_rows[-2] if len(valid_rows) >= 2 else None
        gap = "无明显缺口"
        if prev:
            if valid_rows[-1].low > prev.high:
                gap = "向上跳空"
            elif valid_rows[-1].high < prev.low:
                gap = "向下跳空"

        rsi = self.daily_rsi_value(closes)
        if rsi is None:
            rsi_label = "RSI样本不足"
        elif rsi >= 70:
            rsi_label = "偏热"
        elif rsi <= 30:
            rsi_label = "偏冷"
        else:
            rsi_label = "中性"
        volume_5 = self.avg(volumes[-5:]) if len(volumes) >= 5 else 0.0
        volume_20 = self.avg(volumes[-20:]) if len(volumes) >= 20 else 0.0
        volume_ratio = volume_5 / volume_20 if volume_20 else 0.0
        if volume_ratio >= 1.5:
            volume_status = "放量"
        elif volume_ratio and volume_ratio <= 0.7:
            volume_status = "缩量"
        else:
            volume_status = "量能平稳" if volume_ratio else "量能样本不足"

        last_20_return = close / closes[-20] * 100 - 100 if len(closes) >= 20 and closes[-20] else 0.0
        last_60_return = close / closes[-60] * 100 - 100 if len(closes) >= 60 and closes[-60] else 0.0
        macd = self.macd_profile(closes)
        kdj = self.kdj_profile(highs, lows, closes)
        if ma_status == "多头排列" and macd.get("status") in ("金叉", "多方区"):
            trend = "日K偏强"
        elif ma_status == "空头排列" and macd.get("status") in ("死叉", "空方区"):
            trend = "日K偏弱"
        elif ma20 and close >= ma20:
            trend = "日K修复"
        else:
            trend = "日K震荡"
        return {
            "status": "ok",
            "code": norm,
            "sample_count": len(valid_rows),
            "raw_sample_count": len(rows),
            "first_date": valid_rows[0].date,
            "last_date": valid_rows[-1].date,
            "last_close": round(close, 4),
            "ma": mas,
            "ma_status": ma_status,
            "rsi14": round(rsi, 2) if rsi is not None else None,
            "rsi_status": rsi_label,
            "macd": macd,
            "kdj": kdj,
            "volume_ratio_5_20": round(volume_ratio, 3) if volume_ratio else None,
            "volume_status": volume_status,
            "support": round(support, 4) if support else None,
            "resistance": round(resistance, 4) if resistance else None,
            "high_20": round(max(float(item.high) for item in recent_20), 4) if recent_20 else None,
            "low_20": round(min(float(item.low) for item in recent_20), 4) if recent_20 else None,
            "high_60": round(max(float(item.high) for item in recent_60), 4) if recent_60 else None,
            "prior_high_60": round(max(float(item.high) for item in completed_60), 4) if completed_60 else None,
            "low_60": round(min(float(item.low) for item in recent_60), 4) if recent_60 else None,
            "gap": gap,
            "return_20": round(last_20_return, 2),
            "return_60": round(last_60_return, 2),
            "trend": trend,
        }

    def technical_signal_texts(self, code: str) -> dict[str, str]:
        profile = self.technical_profile(code)
        if profile.get("status") != "ok":
            return {
                "sample": str(profile.get("status") or "历史K采样中"),
                "ma": "-",
                "rsi": "-",
                "macd": "-",
                "kdj": "-",
                "volume": "-",
                "support": "-",
                "resistance": "-",
                "trend": "历史K采样中",
            }
        macd = profile.get("macd") or {}
        kdj = profile.get("kdj") or {}
        return {
            "sample": f"{profile.get('sample_count')}根 / {profile.get('last_date')}",
            "ma": str(profile.get("ma_status") or "-"),
            "rsi": f"RSI {profile.get('rsi14')} {profile.get('rsi_status')}",
            "macd": f"{macd.get('status')} DIF {macd.get('dif')} DEA {macd.get('dea')}",
            "kdj": f"{kdj.get('status')} K {kdj.get('k')} D {kdj.get('d')} J {kdj.get('j')}",
            "volume": f"{profile.get('volume_status')} {profile.get('volume_ratio_5_20') or '-'}",
            "support": str(profile.get("support") or "-"),
            "resistance": str(profile.get("resistance") or "-"),
            "trend": str(profile.get("trend") or "-"),
        }

    @staticmethod
    def _is_plausible_intraday_price(value: float, reference: float) -> bool:
        if value <= 0 or reference <= 0:
            return False
        return reference * 0.5 <= value <= reference * 1.5

    def intraday_profile(self, code: str) -> dict[str, Any]:
        norm = normalize_code(code) or code
        rows = self.intraday_cache.get(norm) or []
        if not rows:
            return {"status": "分时采样中", "code": norm, "sample_count": 0}
        prices = [float(item.price) for item in rows if item.price > 0]
        if not prices:
            return {"status": "分时采样中", "code": norm, "sample_count": len(rows)}
        latest = rows[-1]
        latest_price = float(latest.price)
        avg_candidates = [float(item.avg_price) for item in rows if item.avg_price > 0]
        latest_avg = float(latest.avg_price or 0)
        avg_price = latest_avg if self._is_plausible_intraday_price(latest_avg, latest_price) else 0.0
        avg_price_source = "接口均价线" if avg_price > 0 else ""
        if avg_price <= 0:
            avg_price = self.avg([value for value in avg_candidates if self._is_plausible_intraday_price(value, latest_price)])
            if avg_price > 0:
                avg_price_source = "均价线均值"
        if avg_price <= 0:
            avg_price = latest_price
            avg_price_source = "现价兜底"
        total_volume = sum(max(0.0, float(item.volume)) for item in rows)
        total_amount = sum(max(0.0, float(item.amount)) for item in rows)
        derived_candidates: list[float] = []
        if total_volume > 0 and total_amount > 0:
            derived_candidates.extend([total_amount / total_volume, total_amount / (total_volume * 100)])
        plausible_derived = [
            value for value in derived_candidates
            if self._is_plausible_intraday_price(value, latest_price)
        ]
        if avg_price > 0 and avg_price_source != "现价兜底":
            vwap = avg_price
            vwap_source = avg_price_source
        elif plausible_derived:
            vwap = min(plausible_derived, key=lambda value: abs(value - latest_price))
            vwap_source = "成交额/成交量估算"
        else:
            vwap = latest_price
            vwap_source = "现价兜底"

        def window_return(size: int) -> float | None:
            if len(prices) <= size or prices[-size - 1] <= 0:
                return None
            return prices[-1] / prices[-size - 1] * 100 - 100

        ret_5 = window_return(5)
        ret_15 = window_return(15)
        ret_30 = window_return(30)
        above_vwap = latest_price >= vwap
        above_avg = latest_price >= avg_price
        if above_vwap and ret_15 is not None and ret_15 > 0.4:
            status = "分时转强"
        elif (not above_vwap) and ret_15 is not None and ret_15 < -0.4:
            status = "分时转弱"
        elif above_vwap:
            status = "站上VWAP"
        else:
            status = "低于VWAP"

        tail_signal = "非尾盘"
        try:
            time_part = str(latest.time).split()[-1]
            pieces = [int(part) for part in time_part.split(":")[:2]]
            if len(pieces) >= 2 and dt.time(14, 30) <= dt.time(pieces[0], pieces[1]) <= dt.time(15, 0):
                if ret_15 is not None and ret_15 > 0.6 and above_vwap:
                    tail_signal = "尾盘抢筹"
                elif ret_15 is not None and ret_15 < -0.6:
                    tail_signal = "尾盘走弱"
                else:
                    tail_signal = "尾盘平稳"
        except Exception:
            pass

        return {
            "status": status,
            "code": norm,
            "sample_count": len(rows),
            "first_time": rows[0].time,
            "last_time": latest.time,
            "latest_price": round(latest_price, 4),
            "avg_price": round(avg_price, 4),
            "vwap": round(vwap, 4) if vwap else None,
            "vwap_source": vwap_source,
            "above_vwap": above_vwap,
            "above_avg_price": above_avg,
            "return_5m": round(ret_5, 2) if ret_5 is not None else None,
            "return_15m": round(ret_15, 2) if ret_15 is not None else None,
            "return_30m": round(ret_30, 2) if ret_30 is not None else None,
            "total_volume": round(total_volume, 2),
            "tail_signal": tail_signal,
        }

    def intraday_signal_text(self, code: str) -> str:
        profile = self.intraday_profile(code)
        if profile.get("sample_count", 0) <= 0:
            return str(profile.get("status") or "分时采样中")
        ret_15 = profile.get("return_15m")
        ret_text = f"{ret_15:+.2f}%" if isinstance(ret_15, (int, float)) else "-"
        return f"{profile.get('status')} / 15m {ret_text} / {profile.get('tail_signal')}"

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
        daily = self.technical_signal_texts(code)
        if daily.get("trend") and daily["trend"] != "历史K采样中":
            trend = f"{daily['trend']} / {trend}"
        rsi_text = daily["rsi"] if daily.get("rsi") and daily["rsi"] != "-" else self.rsi_signal(prices)
        return trend, rsi_text, self.risk_signal_for_code(code, quote)

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

    def strategy_enabled(self, strategy_id: str) -> bool:
        return self.store.is_strategy_enabled(strategy_id)

    def active_strategy_definitions(self) -> list[dict[str, Any]]:
        enabled_ids = set(self.store.enabled_strategy_ids())
        return [
            {
                **item,
                "enabled": str(item.get("id")) in enabled_ids,
            }
            for item in STRATEGY_LIBRARY
        ]

    def strategy_pack_context(self) -> dict[str, Any]:
        enabled = [item for item in self.active_strategy_definitions() if item.get("enabled")]
        disabled = [str(item.get("id")) for item in self.active_strategy_definitions() if not item.get("enabled")]
        return {
            "name": "本地缠论笔结构 + 独立趋势参考 + 执行风控",
            "version": APP_VERSION,
            "enabled_ids": [str(item.get("id")) for item in enabled],
            "disabled_ids": disabled,
            "enabled_definitions": enabled,
            "ai_onboarding": {
                "read_first": [
                    "先读 strategy_pack.enabled_definitions，确认用户启用哪些策略。",
                    "缠论笔结构候选见 local_structure；不把CAN SLIM近新高/均线强势要求强加给结构二买。",
                    "仅在用户启用时读取 market_gate，其颜色属于市场观察，不作为开仓否决。",
                    "只有用户启用 canslim_radar 时才读取其分桶和评分作为独立参考，不要求缠论信号同时满足它。",
                    "最后结合 risk_audit、pending_orders、cash、T+1 和每手规则形成候选指令。",
                ],
                "must_not": [
                    "不要只根据今日涨跌幅下单。",
                    "不要把缺失的 EPS、营收、ROE 或机构持仓数据编造成已验证事实。",
                    "不要将持仓、亏损、ST、涨幅或仓位比例用作额外下单限制。",
                    "候选指令必须给出有效委托价和明确股数；同一证券活动委托最多3条，不自动缩量。",
                ],
                "preferred_output": "结论、证据、操作、风险四段式；候选 JSON 指令只能作为待审批建议。",
            },
        }

    def strategy_code_universe(self) -> list[str]:
        seen: set[str] = set()
        codes: list[str] = []
        for code in list(self.store.watchlist) + list(self.store.positions().keys()):
            norm = normalize_code(code) or code
            if norm and norm not in seen:
                seen.add(norm)
                codes.append(norm)
        return codes

    def market_gate_profile(self, code: str | None = None) -> dict[str, Any]:
        enabled = self.strategy_enabled("market_gate")
        if not enabled:
            return {
                "enabled": False,
                "gate": "disabled",
                "label": "未启用",
                "score": 0,
                "new_long_allowed": True,
                "summary": "用户已关闭市场环境闸门。",
                "indices": [],
            }

        if code and code.startswith("hk"):
            return {
                "enabled": True,
                "market": "hk",
                "gate": "unknown",
                "label": "港股数据缺失",
                "score": 0,
                "new_long_allowed": True,
                "summary": "尚未接入港股基准指数，港股市场环境未验证；不使用 A 股指数作港股开仓的硬否决。",
                "indices": [],
            }

        index_rows: list[dict[str, Any]] = []
        scores: list[float] = []
        for code in MARKET_GATE_CODES:
            quote = self.quote_cache.get(code)
            technical = self.technical_profile(code)
            if not quote and technical.get("status") != "ok":
                continue
            score = 0.0
            evidence: list[str] = []
            if quote:
                if quote.change_pct >= 0.4:
                    score += 0.7
                    evidence.append(f"日内上涨 {quote.change_pct:+.2f}%")
                elif quote.change_pct <= -0.4:
                    score -= 0.7
                    evidence.append(f"日内下跌 {quote.change_pct:+.2f}%")
                else:
                    evidence.append(f"日内震荡 {quote.change_pct:+.2f}%")
            if technical.get("status") == "ok":
                ma_status = str(technical.get("ma_status") or "")
                trend = str(technical.get("trend") or "")
                return_20 = float(technical.get("return_20") or 0)
                volume_ratio = float(technical.get("volume_ratio_5_20") or 0)
                if "多头" in ma_status or trend == "日K偏强":
                    score += 1.0
                    evidence.append("日K偏强")
                elif "空头" in ma_status or trend == "日K偏弱":
                    score -= 1.0
                    evidence.append("日K偏弱")
                elif "站上MA20" in ma_status or trend == "日K修复":
                    score += 0.35
                    evidence.append("站上MA20/修复")
                elif "跌破MA20" in ma_status:
                    score -= 0.35
                    evidence.append("跌破MA20")
                if return_20 >= 3:
                    score += 0.35
                    evidence.append(f"20日 {return_20:+.1f}%")
                elif return_20 <= -3:
                    score -= 0.35
                    evidence.append(f"20日 {return_20:+.1f}%")
                if quote and quote.change_pct < -0.2 and volume_ratio >= 1.2:
                    score -= 0.45
                    evidence.append("下跌放量，疑似分歧")
            index_rows.append(
                {
                    "code": code,
                    "name": quote.name if quote else code,
                    "change_pct": round(float(quote.change_pct), 2) if quote else None,
                    "technical": technical,
                    "score": round(score, 2),
                    "evidence": evidence,
                }
            )
            scores.append(score)

        if not scores:
            return {
                "enabled": True,
                "gate": "unknown",
                "label": "黄灯",
                "score": 0,
                "new_long_allowed": True,
                "summary": "指数样本不足，市场环境未知，仅展示数据缺项。",
                "indices": [],
            }

        avg_score = sum(scores) / len(scores)
        if avg_score >= 0.55:
            gate = "green"
            label = "绿灯"
            summary = "市场环境偏支持，可继续筛选高质量买点。"
            new_long_allowed = True
        elif avg_score <= -0.45:
            gate = "red"
            label = "红灯"
            summary = "市场环境偏弱，仅作为指数趋势观察，不限制下单。"
            new_long_allowed = True
        else:
            gate = "yellow"
            label = "黄灯"
            summary = "市场环境一般，仅作为指数趋势观察，不限制下单股数。"
            new_long_allowed = True
        return {
            "enabled": True,
            "gate": gate,
            "label": label,
            "score": round(avg_score, 2),
            "new_long_allowed": new_long_allowed,
            "summary": summary,
            "indices": index_rows,
        }

    def relative_strength_percentile(self, code: str) -> float | None:
        values: list[tuple[str, float]] = []
        for candidate in self.strategy_code_universe():
            if candidate in MARKET_GATE_CODES:
                continue
            technical = self.technical_profile(candidate)
            if technical.get("status") != "ok":
                continue
            score = float(technical.get("return_60") or 0) * 0.65 + float(technical.get("return_20") or 0) * 0.35
            values.append((candidate, score))
        if len(values) < 2:
            return None
        values.sort(key=lambda item: item[1])
        for rank, (candidate, _score) in enumerate(values, 1):
            if candidate == code:
                return rank / len(values) * 100
        return None

    @staticmethod
    def clamp_score(value: float) -> int:
        return int(max(0, min(100, round(value))))

    def canslim_profile_for_code(self, code: str, quote: Quote | None, market_gate: dict[str, Any] | None = None) -> dict[str, Any]:
        norm = normalize_code(code) or code
        if not self.strategy_enabled("canslim_radar"):
            return {"enabled": False, "code": norm, "name": quote.name if quote else norm,
                    "score": None, "light": "未启用", "bucket": "未启用", "setup": "未启用",
                    "risk": "", "action": "用户未启用 CAN SLIM 参考", "components": {},
                    "warnings": [], "evidence": [], "missing": []}
        positions = self.store.positions()
        item = positions.get(norm) or {}
        qty = int(item.get("qty") or 0)
        technical = self.technical_profile(norm)
        intraday = self.intraday_profile(norm)
        flow = self.money_flow_cache.get(norm)
        market_gate = self.market_gate_profile(norm) if norm.startswith("hk") else (market_gate or self.market_gate_profile(norm))
        price = quote.price if quote else float(technical.get("last_close") or item.get("breakeven_cost") or item.get("avg_cost") or 0)
        name = quote.name if quote else str(item.get("name") or norm)
        is_st = "ST" in name.upper()
        buy_point_enabled = self.strategy_enabled("buy_point_discipline")
        sell_discipline_enabled = self.strategy_enabled("sell_discipline")
        intraday_enabled = self.strategy_enabled("intraday_vwap_execution")
        portfolio_enabled = self.strategy_enabled("portfolio_risk")

        missing = ["C/A 基本面未接入：EPS、营收、ROE 需人工或外部数据确认"]
        if norm.startswith("hk") and market_gate.get("gate") == "unknown":
            missing.append("M 港股基准指数未接入，不能根据 A 股指数判断港股市场环境")
        evidence: list[str] = []
        warning: list[str] = []

        gate = str(market_gate.get("gate") or "unknown")
        if gate == "green":
            market_score = 80
        elif gate == "yellow":
            market_score = 55
        elif gate == "red":
            market_score = 20
            warning.append("市场闸门红灯")
        else:
            market_score = 45
            warning.append("市场环境样本不足")

        if technical.get("status") == "ok":
            trend = str(technical.get("trend") or "")
            ma_status = str(technical.get("ma_status") or "")
            if "多头" in ma_status or trend == "日K偏强":
                technical_score = 85
                evidence.append("日K趋势偏强")
            elif trend == "日K修复" or "站上MA20" in ma_status:
                technical_score = 68
                evidence.append("日K修复/站上MA20")
            elif "空头" in ma_status or trend == "日K偏弱":
                technical_score = 25
                warning.append("日K偏弱")
            elif "跌破MA20" in ma_status:
                technical_score = 35
                warning.append("跌破MA20")
            else:
                technical_score = 52
                evidence.append("日K震荡")
        else:
            technical_score = 45
            warning.append("历史日K样本不足")

        rs = self.relative_strength_percentile(norm)
        if rs is None:
            relative_score = 50
            relative_text = "相对强弱样本不足"
        elif rs >= 80:
            relative_score = 88
            relative_text = f"相对强弱前列 {rs:.0f}"
            evidence.append(relative_text)
        elif rs >= 60:
            relative_score = 68
            relative_text = f"相对强弱中上 {rs:.0f}"
        elif rs <= 35:
            relative_score = 30
            relative_text = f"相对强弱落后 {rs:.0f}"
            warning.append(relative_text)
        else:
            relative_score = 50
            relative_text = f"相对强弱一般 {rs:.0f}"

        demand_score = 50
        if technical.get("status") == "ok":
            volume_ratio = float(technical.get("volume_ratio_5_20") or 0)
            if volume_ratio >= 1.4:
                demand_score += 15
                evidence.append(f"近5日较20日放量 {volume_ratio:.2f}x")
            elif 0 < volume_ratio <= 0.7:
                demand_score -= 10
                warning.append(f"缩量 {volume_ratio:.2f}x")
        if flow:
            if flow.main_pct >= 3:
                demand_score += 18
                evidence.append(f"主力流入 {flow.main_pct:+.1f}%")
            elif flow.main_pct > 0:
                demand_score += 8
                evidence.append(f"资金小幅流入 {flow.main_pct:+.1f}%")
            elif flow.main_pct <= -3:
                demand_score -= 18
                warning.append(f"主力流出 {flow.main_pct:+.1f}%")
            else:
                demand_score -= 5
        elif not norm.startswith("hk"):
            warning.append("A股资金流采样中")
        if intraday_enabled and intraday.get("sample_count", 0) > 0 and intraday.get("above_vwap"):
            demand_score += 8
            evidence.append("分时站上VWAP")
        elif intraday_enabled and intraday.get("sample_count", 0) > 0:
            demand_score -= 5
        demand_score = self.clamp_score(demand_score)

        setup_score = 50
        setup_text = "买点待观察"
        if not buy_point_enabled:
            setup_score = 55
            setup_text = "买点纪律未启用，仅展示候选强弱"
        elif technical.get("status") == "ok" and price > 0:
            high_60 = float(technical.get("prior_high_60") or 0)
            ma = technical.get("ma") if isinstance(technical.get("ma"), dict) else {}
            ma20 = float(ma.get("ma20") or 0)
            ma60 = float(ma.get("ma60") or 0)
            volume_ratio = float(technical.get("volume_ratio_5_20") or 0)
            near_high = bool(high_60 and price >= high_60 * 0.97)
            above_ma = bool((ma20 and price >= ma20) or (ma60 and price >= ma60))
            if high_60 and price > high_60 * 1.05:
                setup_score = 35
                setup_text = "距离近端高位偏远，谨慎追高"
                warning.append("可能偏离买点")
            elif near_high and volume_ratio >= 1.2:
                setup_score = 82
                setup_text = "接近60日高位且有量，关注突破/回踩买点"
            elif above_ma and ((not intraday_enabled) or intraday.get("above_vwap")):
                setup_score = 68
                setup_text = "均线修复，等待确认" if not intraday_enabled else "均线修复且分时站上VWAP，等待确认"
            elif ma20 and price < ma20:
                setup_score = 35
                setup_text = "低于MA20，等待修复"
            else:
                setup_score = 55
        else:
            setup_text = "买点样本不足"

        risk_score = 60
        risk_text = "无持仓，按候选观察"
        if is_st:
            risk_score -= 25
            warning.append("ST 风险票")
        if qty > 0:
            breakeven = float(item.get("breakeven_cost") or item.get("avg_cost") or 0)
            risk_text = "持仓观察"
            if not sell_discipline_enabled:
                risk_text = "卖出纪律未启用，仅展示基础持仓"
            elif breakeven > 0 and price > 0:
                drawdown = price / breakeven * 100 - 100
                if drawdown <= -8:
                    risk_score = 12
                    risk_text = f"较回本价 {drawdown:.1f}%，触发7%-8%止损复核"
                    warning.append("止损复核")
                elif drawdown <= -4:
                    risk_score = 32
                    risk_text = f"较回本价 {drawdown:.1f}%，持仓浮亏观察"
                    warning.append("亏损持仓")
                elif drawdown >= 20:
                    risk_score = 68
                    risk_text = f"较回本价 {drawdown:.1f}%，进入盈利保护区"
                    evidence.append("盈利保护")
                else:
                    risk_score = 58
            equity = self.account_equity_estimate()
            weight = price * qty / equity * 100 if equity and price else 0
            if portfolio_enabled:
                risk_text += f"；单票仓位 {weight:.1f}%"

        components = {
            "market": market_score,
            "technical": technical_score,
            "relative_strength": relative_score,
            "demand": demand_score,
            "setup": setup_score,
            "risk": self.clamp_score(risk_score),
        }
        weights = {
            "market": 0.15,
            "technical": 0.2,
            "relative_strength": 0.15,
            "demand": 0.15,
            "setup": 0.2,
            "risk": 0.15,
        }
        score = self.clamp_score(sum(components[key] * weights[key] for key in components))

        if is_st:
            bucket = "风险票"
        elif qty > 0 and components["risk"] <= 35:
            bucket = "持仓风控"
        elif score >= 75 and setup_score >= 65 and gate != "red":
            bucket = "近买点/领导者"
        elif score >= 65:
            bucket = "领导者观察"
        elif score >= 50:
            bucket = "观察"
        else:
            bucket = "弱势/剔除"

        if gate == "red":
            action = "市场环境偏弱，说明依据与数据缺项；不作为交易否决。"
            light = "红灯"
        elif components["risk"] <= 35 and qty > 0:
            action = "复核持仓盈亏和退出条件；继续买入仍按用户启用策略判断。"
            light = "红灯"
        elif score >= 75 and setup_score >= 65:
            action = "可列入近买点观察，成交需满足限价、资金、数量和T+1规则。"
            light = "绿灯"
        elif score >= 55:
            action = "继续观察，等待买点或分时确认。"
            light = "黄灯"
        else:
            action = "信号不足或偏弱，避免主动买入。"
            light = "红灯"

        return {
            "enabled": self.strategy_enabled("canslim_radar"),
            "code": norm,
            "name": name,
            "score": score,
            "light": light,
            "bucket": bucket,
            "market_gate": market_gate.get("label"),
            "relative_strength": round(rs, 1) if rs is not None else None,
            "setup": setup_text,
            "risk": risk_text,
            "action": action,
            "components": components,
            "evidence": evidence[:8],
            "warnings": warning[:8],
            "missing": missing,
        }

    def canslim_radar_rows(self) -> list[dict[str, Any]]:
        if not self.strategy_enabled("canslim_radar"):
            return []
        market_gate = self.market_gate_profile()
        rows = [
            self.canslim_profile_for_code(code, self.quote_cache.get(code), market_gate=market_gate)
            for code in self.strategy_code_universe()
        ]
        rows.sort(key=lambda item: (0 if int(item.get("score") or 0) >= 50 else 1, -int(item.get("score") or 0), str(item.get("code") or "")))
        return rows

    def risk_signal_for_code(self, code: str, quote: Quote | None) -> str:
        item = self.store.positions().get(code) or {}
        qty = int(item.get("qty") or 0)
        if not qty:
            return "无持仓"
        price = quote.price if quote else float(item.get("breakeven_cost") or item.get("avg_cost") or 0)
        equity = self.account_equity_estimate()
        weight = price * qty / equity * 100 if equity else 0.0
        return f"仓位 {weight:.0f}%"

    def agent_market_rows(self) -> list[dict[str, Any]]:
        positions = self.store.positions()
        codes = sorted(set(self.store.watchlist + list(positions.keys())))
        equity = self.account_equity_estimate()
        market_gate = self.market_gate_profile()
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
            technical = self.technical_profile(code)
            technical_text = self.technical_signal_texts(code)
            intraday = self.intraday_profile(code)
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
                    "technical": technical,
                    "technical_text": technical_text,
                    "intraday": intraday,
                    "intraday_text": self.intraday_signal_text(code),
                    "canslim": self.canslim_profile_for_code(code, quote, market_gate=market_gate),
                }
            )
        return rows

    def strategy_catalog_rows(self) -> list[dict[str, str]]:
        return [
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "status": "启用" if item.get("enabled") else "停用",
                "group": str(item.get("group") or ""),
                "definition": f"{item.get('definition') or ''} 作用：{item.get('purpose') or ''}",
                "inputs": str(item.get("inputs") or ""),
                "outputs": str(item.get("outputs") or ""),
                "usage": str(item.get("ai_usage") or ""),
                "hard_rules": "；".join(item.get("hard_rules") or []),
            }
            for item in self.active_strategy_definitions()
        ]

    def strategy_context(self) -> dict[str, Any]:
        curve_rows = self.account_curve_rows()
        latest_curve = curve_rows[-1] if curve_rows else {}
        max_drawdown = min((float(row.get("drawdown_pct") or 0) for row in curve_rows), default=0.0)
        return {
            "note": "These are deterministic local strategy/risk signals for the AI to analyze. They are not an AI-generated conclusion.",
            "generated_at": now_str(),
            "strategy_pack": self.strategy_pack_context(),
            "local_structure": self.local_strategy_panel.context(),
            "strategy_catalog": self.strategy_catalog_rows(),
            "historical_data": self.historical_data_summary(),
            "market_gate": self.market_gate_profile(),
            "canslim_radar": self.canslim_radar_rows(),
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

        gate = self.market_gate_profile()
        if gate.get("enabled"):
            gate_sign = 0.8 if gate.get("gate") == "green" else -0.7 if gate.get("gate") == "red" else 0.0
            add("市场闸门", str(gate.get("label") or "未知"), str(gate.get("summary") or ""), gate_sign)
        else:
            add("市场闸门", "未启用", "用户已关闭 CAN SLIM 市场环境闸门。", 0.0)

        reserved = float(summary.get("reserved") or 0)
        available_cash = float(summary.get("available_cash") or 0)
        equity = float(summary.get("equity") or 0)
        if reserved > 0:
            add("现金/冻结", "有冻结资金", f"可用 {money(available_cash)}，买入委托冻结 {money(reserved)}。", -0.2)
        else:
            add("现金/冻结", "可用余额", f"可用资金 {money(available_cash)}，按完整委托金额校验。", 0.0)

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
        add("持仓集中度", "比例观察", f"最高单票 {max_code or '-'} 仓位约 {max_weight:.1f}%，无比例上限。", 0.0)

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

        add("委托数量", "固定上限", "同一证券买卖活动委托合计最多3条；成交或撤单后释放名额。", 0.0)

        ai = self.store.data.get("ai") or {}
        if ai.get("api_key"):
            add("AI 接入", "已配置", f"模型 {ai.get('model') or '未设置'}，候选指令仍需预审和确认。", 0.6)
        else:
            add("AI 接入", "未配置", "未填写 API Key 时不会调用外部 AI，只能使用本地策略上下文。", 0.0)
        return rows

    def rebalance_suggestions(self) -> list[dict[str, Any]]:
        summary = self.account_summary()
        equity = float(summary.get("equity") or 0)
        rows: list[dict[str, Any]] = []

        def add(target: str, suggestion: str, reason: str, condition: str, usage: str, priority: float = 0.0) -> None:
            rows.append({"target": target, "suggestion": suggestion, "reason": reason,
                         "condition": condition, "usage": usage, "priority": priority})

        for code, item in self.store.positions().items():
            quote = self.quote_cache.get(code)
            price = quote.price if quote else float(item.get("breakeven_cost") or item.get("avg_cost") or 0)
            qty = int(item.get("qty") or 0)
            weight = price * qty / equity * 100 if equity else 0.0
            available = self.store.available_sell_qty(code)
            add(code, "持仓观察", f"持仓 {qty} 股，仓位 {weight:.1f}%，剩余可卖 {available} 股。",
                "根据启用策略和有效行情判断买卖条件。", "持仓比例、浮亏和 ST 标签不构成买入限制。")
        add("现金", "可用资金", f"可用 {money(summary.get('available_cash', 0))}；冻结 {money(summary.get('reserved', 0))}。",
            "按明确股数和限价校验足额资金，不自动缩量。", "实际资金不足时说明缺口。")
        active_orders = self.store.active_pending_orders()
        if active_orders:
            add("未成交委托", "持续待撮合", f"当前有 {len(active_orders)} 条活动委托，同一证券最多 3 条。",
                "达到限价且符合基本成交规则时撮合，用户可撤单或改单。", "修改委托应优先引用 order_id。")
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
        self.date_label.setText(today_str())
        self.date_label.setToolTip("A股今日买入须下一交易日卖出；港股可当日买卖。")

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
                str(order.get("wait_reason") or "等待成交"),
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
        self.local_strategy_panel.refresh_rows()
        catalog = self.strategy_catalog_rows()
        self.strategy_catalog_table.setRowCount(len(catalog))
        for row, item in enumerate(catalog):
            values = [
                str(item.get("name") or ""),
                str(item.get("status") or ""),
                str(item.get("group") or ""),
                str(item.get("definition") or ""),
                f"输入：{item.get('inputs') or ''}\n输出：{item.get('outputs') or ''}",
                str(item.get("usage") or ""),
            ]
            self._set_row(self.strategy_catalog_table, row, values, 0.0)
            for col in (2, 3, 4, 5):
                cell = self.strategy_catalog_table.item(row, col)
                if cell:
                    cell.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        rows = self.agent_market_rows()
        canslim_rows = [
            item.get("canslim") for item in rows
            if isinstance(item.get("canslim"), dict)
        ]
        canslim_rows.sort(key=lambda item: (0 if int(item.get("score") or 0) >= 50 else 1, -int(item.get("score") or 0), str(item.get("code") or "")))

        if hasattr(self, "strategy_canslim_table"):
            self.strategy_canslim_table.setRowCount(len(canslim_rows))
            for row, item in enumerate(canslim_rows):
                evidence = "；".join(item.get("evidence") or []) or "-"
                risk_bits = []
                if item.get("risk"):
                    risk_bits.append(str(item.get("risk")))
                risk_bits.extend(str(bit) for bit in (item.get("warnings") or [])[:3])
                missing = item.get("missing") or []
                if missing:
                    risk_bits.append(str(missing[0]))
                score = int(item.get("score") or 0)
                values = [
                    str(item.get("code") or ""),
                    str(item.get("name") or ""),
                    str(item.get("bucket") or ""),
                    str(score),
                    str(item.get("light") or ""),
                    str(item.get("market_gate") or ""),
                    str(item.get("relative_strength") if item.get("relative_strength") is not None else "样本不足"),
                    str(item.get("setup") or ""),
                    evidence,
                    "；".join(risk_bits) if risk_bits else "-",
                    str(item.get("action") or ""),
                ]
                self._set_row(self.strategy_canslim_table, row, values, score - 50)
                for col in range(2, self.strategy_canslim_table.columnCount()):
                    cell = self.strategy_canslim_table.item(row, col)
                    if cell:
                        cell.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.strategy_signal_table.setRowCount(len(rows))
        for row, item in enumerate(rows):
            sign = float(item.get("change_pct") or 0)
            technical_text = item.get("technical_text") if isinstance(item.get("technical_text"), dict) else {}
            values = [
                str(item.get("code") or ""),
                str(item.get("name") or ""),
                f"{float(item.get('price') or 0):.3f}" if item.get("price") is not None else "-",
                pct(float(item.get("change_pct") or 0)) if item.get("change_pct") is not None else "-",
                str(technical_text.get("sample") or "-"),
                str(item.get("trend") or ""),
                str(item.get("intraday_text") or ""),
                str(technical_text.get("ma") or "-"),
                str(item.get("rsi") or ""),
                str(technical_text.get("macd") or "-"),
                str(technical_text.get("kdj") or "-"),
                str(technical_text.get("volume") or "-"),
                str(technical_text.get("support") or "-"),
                str(technical_text.get("resistance") or "-"),
                str(item.get("money_flow") or ""),
                str(item.get("risk") or ""),
                pct(float(item.get("weight_pct") or 0)),
                str(item.get("pending_count") or 0),
            ]
            self._set_row(self.strategy_signal_table, row, values, sign)
            for col in (4, 5, 6, 7, 8, 9, 10, 11, 14, 15):
                cell = self.strategy_signal_table.item(row, col)
                if cell:
                    cell.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        preview = {
            "strategy_pack": self.strategy_pack_context(),
            "strategy_catalog": catalog,
            "historical_data": self.historical_data_summary(),
            "market_gate": self.market_gate_profile(),
            "canslim_radar": canslim_rows,
            "market_rows": rows,
            "kline_history_file": CODEX_KLINE_FILE,
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
              "输入里包含真实行情、全量历史日K技术画像、当日分时/VWAP画像、持仓、委托、风控配置，以及本地策略上下文 strategy_context。"
              "strategy_context 只是确定性策略/风控信号，供你参考，不是最终结论；最终多智能体分析必须由你完成。"
              "首次接入时必须先读取 strategy_context.strategy_pack.enabled_definitions，理解用户启用的策略定义、作用和硬规则。"
              "仅在相应策略启用时参考 market_gate 与 canslim_radar；市场颜色不否决开仓，CAN SLIM 基本面缺项不得编造。"
              "完整历史日K在 codex_bridge.kline_history_file，格式为 symbols[code].klines[]；不要误以为只有当日走势。"
              "不要只根据今日涨跌幅下结论；技术面至少参考 MA5/10/20/60/120/250、量能、支撑压力、MACD、KDJ、VWAP/均价线、近5/15/30分钟变化、尾盘信号和近期交易质量。"
              "科创板买入最低200股且1股递增；卖出时如果可卖余额不足200股，只能一次性卖出剩余余额。"
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
            "必须遵守 T+1、可用现金、冻结资金、申报数量和有效行情；同股活动委托最多3条。允许ST、持仓加买和手工重复提交；股数明确，不套仓位比例上限或暗中缩量。只允许快照内股票代码。"
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
                self.markdown_table(["代码", "名称", "持仓", "可卖", "当前持仓成本", "摊余回本价", "摊余回本成本"], position_rows),
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
                qty = parse_order_quantity(qty_value) if qty_value not in (None, "") else int(order.get("qty") or 0)
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
        stale = quote_freshness_error(quote, dt.datetime.now())
        if stale:
            return stale
        try:
            qty = parse_order_quantity(command.get("qty"))
            limit_price = float(command.get("limit_price") or 0)
        except Exception:
            return "数量或价格无效"
        if qty <= 0 or not math.isfinite(limit_price) or limit_price <= 0:
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
                available_qty = self.store.available_sell_qty(code)
                self.store.validate_sell_quantity(code, qty, available_qty)
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
                    "回答要基于当前账户、行情、全量历史日K技术画像、当日分时/VWAP画像、风险审计、策略上下文和最新多智能体报告。"
                    "不要只看今日涨跌幅；需要结合均线、量能、支撑压力、MACD、KDJ、VWAP/均价线、近5/15/30分钟变化、尾盘信号和近期交易质量。"
                    "科创板买入最低200股且1股递增；卖出时如果可卖余额不足200股，只能一次性卖出剩余余额。"
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
                str(log.get("filled") or 0),
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
        if not check_pending_limit:
            return []
        replace_id = str((replacing_order or {}).get("id") or "")
        active_count = sum(
            str(order.get("code") or "") == quote.code
            and str(order.get("id") or "") != replace_id
            for order in self.store.active_pending_orders()
        )
        if active_count >= MAX_PENDING_PER_CODE:
            return [f"{quote.code} 已有 {active_count} 条活动委托，同代码最多 {MAX_PENDING_PER_CODE} 条。"]
        return []

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
                "评分",
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
        stale = quote_freshness_error(quote, dt.datetime.now())
        if stale:
            return stale
        try:
            count = parse_order_quantity(qty if qty is not None else self.qty_spin.value())
        except ValueError as exc:
            return str(exc)
        if count <= 0:
            return "数量必须大于 0"
        if action.lower() == "buy":
            try:
                self.store.validate_buy_quantity(target, count)
            except Exception as exc:
                return str(exc)
        else:
            try:
                self.store.validate_sell_quantity(target, count, self.store.available_sell_qty(target))
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
                order["wait_reason"] = "缺少报价，等待刷新"
                changed = True
                continue
            stale = quote_freshness_error(quote, dt.datetime.now())
            if stale:
                order["wait_reason"] = stale
                changed = True
                continue
            order["last_price"] = round(float(quote.price), 4)
            action = str(order.get("action") or "").upper()
            try:
                qty = parse_order_quantity(order.get("qty"))
                limit_price = float(order.get("limit_price") or 0)
            except (TypeError, ValueError, OverflowError):
                order.update(status="FAILED", failed_at=now_str(), error="委托数量或价格无效")
                changed = True
                continue
            if action not in ("BUY", "SELL") or not math.isfinite(limit_price) or limit_price <= 0:
                order.update(status="FAILED", failed_at=now_str(), error="委托方向或价格无效")
                changed = True
                continue
            local_id = str(order.get("local_signal_id") or "")
            protective = action == "SELL" and (local_id.startswith("stop:") or ":stop:" in local_id)
            if local_id and not protective:
                try:
                    confirmed = dt.date.fromisoformat(str(order.get("signal_confirmed_at") or order.get("signal_date") or ""))
                except (TypeError, ValueError):
                    order["wait_reason"] = "本地信号缺少可核验的确认日期，等待修正"
                    changed = True
                    continue
                if confirmed >= dt.date.today():
                    order["wait_reason"] = "日线信号须在确认日之后成交；委托持续有效"
                    changed = True
                    continue
            triggered = quote.price <= limit_price if action == "BUY" else quote.price >= limit_price
            if not triggered:
                order["wait_reason"] = "委托价格尚未触发"
                changed = True
                continue
            time_error = trading_time_error(code)
            if time_error:
                order["wait_reason"] = time_error
                changed = True
                continue
            try:
                risk_errors = self.risk_violations_for_order(action, quote, qty, quote.price, order, check_pending_limit=False)
                if risk_errors:
                    order["status"] = "FAILED"
                    order["failed_at"] = now_str()
                    order["error"] = "风控拦截：" + "；".join(risk_errors)
                    changed = True
                    continue
                reason = f"限价委托触发，委托价 {limit_price:.3f}"
                if action == "BUY":
                    self.store.buy(quote, qty, str(order.get("operator") or "用户"), reason,
                                   pending_order_id=str(order.get("id") or ""))
                else:
                    self.store.sell(quote, qty, str(order.get("operator") or "用户"), reason,
                                    local_only=bool(order.get("local_signal_id")),
                                    pending_order_id=str(order.get("id") or ""))
                order["status"] = "FILLED"
                order.pop("wait_reason", None)
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
            except ValueError as exc:
                order["wait_reason"] = str(exc)
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
        stale = quote_freshness_error(quote, dt.datetime.now())
        if stale:
            return stale
        try:
            count = parse_order_quantity(qty if qty is not None else self.qty_spin.value())
        except ValueError as exc:
            return str(exc)
        try:
            risk_errors = self.risk_violations_for_order(action, quote, count, quote.price, check_pending_limit=False)
            if risk_errors:
                return "风控拦截：\n" + "\n".join(risk_errors)
            if action.lower() == "buy":
                self.store.buy(quote, count, operator, reason)
            else:
                self.store.validate_sell_quantity(target, count, self.store.available_sell_qty(target))
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
        daily_technical_profiles = {}
        intraday_profiles = {}
        for code in codes:
            trend, rsi, risk = self.strategy_signals(code, self.quote_cache.get(code))
            strategy_signals[code] = {"trend": trend, "rsi": rsi, "risk": risk}
            daily_technical_profiles[code] = self.technical_profile(code)
            intraday_profiles[code] = self.intraday_profile(code)
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
            "strategy_settings": self.store.strategy_config(),
            "ai_pipeline": self.store.ai_pipeline_config(),
            "historical_data": self.historical_data_summary(),
            "strategy_signals": strategy_signals,
            "daily_technical_profiles": daily_technical_profiles,
            "intraday_profiles": intraday_profiles,
            "strategy_context": self.strategy_context(),
            "latest_agent_report": {
                "id": latest_report.get("id"),
                "time": latest_report.get("time"),
                "summary": latest_report.get("summary"),
                "commands": latest_report.get("commands") or [],
            } if latest_report else None,
            "rules": "模拟交易；用户和 AI/Codex 下单均为限价委托，buy/sell 指令必须包含 limit_price；买入在实时价小于等于委托价时成交，卖出在实时价大于等于委托价时成交；A股按 T+1，今日买入不可卖出；港股支持当日买卖；买入数量按市场每手/最低申报规则校验；科创板买入最低200股且1股递增，卖出时可卖余额不足200股应一次性卖出；暂不计算手续费、印花税、汇率。",
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
            "首次接入先读 strategy_context.strategy_pack.enabled_definitions，仅参考用户启用的策略；禁用策略不得参与下单判断。"
            "同股活动委托最多3条；允许ST、持仓加买和手工重复提交，不设置仓位比例上限或自动缩量。CAN SLIM 缺少基本面数据时必须标记缺项，不能编造 EPS/营收/ROE。"
            "完整历史日K在 codex_bridge.kline_history_file，格式为 symbols[code].klines[]；不要误以为只有当日走势。"
            "不要只根据今日涨跌幅下单；必须参考快照里的 daily_technical_profiles、intraday_profiles、strategy_context.market_rows[].technical、strategy_context.market_rows[].intraday、均线、量能、支撑压力、MACD、KDJ、VWAP/均价线、近5/15/30分钟变化和风控。"
            "如果历史K或分时样本不足，要明确说样本不足，不能编造。"
            "科创板买入最低200股且1股递增；卖出时如果可卖余额不足200股，只能一次性卖出剩余余额。"
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

    def write_codex_snapshot(self, force: bool = False) -> None:
        try:
            now = dt.datetime.now()
            if not force and self._last_snapshot_write is not None:
                if (now - self._last_snapshot_write).total_seconds() < 10:
                    return
            snapshot = self.account_snapshot()
            snapshot["app"] = {"name": APP_NAME, "version": APP_VERSION}
            snapshot["codex_bridge"] = {
                "orders_file": CODEX_ORDER_FILE,
                "snapshot_file": CODEX_SNAPSHOT_FILE,
                "result_file": CODEX_RESULT_FILE,
                "kline_history_file": CODEX_KLINE_FILE,
                "kline_history_format": "JSON path: symbols[code].klines[]",
                "polling": True,
                "schema": snapshot.get("codex_order_schema"),
            }
            save_json(CODEX_SNAPSHOT_FILE, snapshot)
            self._last_snapshot_write = now
        except Exception:
            return

    def write_codex_kline_history(self) -> None:
        try:
            payload = {
                "time": now_str(),
                "source": "东方财富日K",
                "note": "软件尽量拉取接口返回的全部可用日K；codex_snapshot.json 只放技术摘要，完整K线在本文件。",
                "format": "symbols[code].klines[]",
                "usage_for_ai": "策略分析不要只看当日涨跌；请结合 codex_snapshot.json 的 daily_technical_profiles、strategy_context.historical_data，以及本文件 symbols[code].klines[] 中的完整历史日K。",
                "symbols": {
                    code: {
                        "sample_count": len(rows),
                        "first_date": rows[0].date if rows else "",
                        "last_date": rows[-1].date if rows else "",
                        "klines": [item.__dict__.copy() for item in rows],
                    }
                    for code, rows in self.daily_kline_cache.items()
                },
            }
            save_json(CODEX_KLINE_FILE, payload)
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
            request_id = str(data.get("request_id") or data.get("id") or now_str()) if isinstance(data, dict) else now_str()
            if not isinstance(orders, list) or not orders:
                save_json(
                    CODEX_RESULT_FILE,
                    {
                        "time": now_str(),
                        "request_id": request_id,
                        "status": "idle",
                        "source": "Codex 本地指令",
                        "summary": "当前无待处理指令",
                        "orders": [],
                        "snapshot_file": CODEX_SNAPSHOT_FILE,
                    },
                )
                return
            actionable = [item for item in orders if isinstance(item, dict) and str(item.get("action") or "hold").lower() != "hold"]
            if not actionable:
                save_json(CODEX_RESULT_FILE, {"time": now_str(), "request_id": request_id, "status": "idle", "source": "Codex 本地指令", "summary": "没有可执行指令", "orders": orders, "snapshot_file": CODEX_SNAPSHOT_FILE})
                save_json(CODEX_ORDER_FILE, [])
                self._codex_order_mtime = os.path.getmtime(CODEX_ORDER_FILE)
                self.store.append_ai_log(
                    {
                        "source": "Codex 本地指令",
                        "operator": "Codex",
                        "summary": "本轮未下单：没有可执行指令",
                        "submitted": 0,
                        "cancelled": 0,
                        "amended": 0,
                        "filled": 0,
                        "errors": [],
                        "request_id": request_id,
                        "commands": orders,
                    }
                )
                self.render_ai_logs()
                return
            result = self.execute_ai_orders(json.dumps(orders, ensure_ascii=False), "Codex", show_dialog=False)
            errors = result.get("errors") if isinstance(result, dict) else []
            save_json(
                CODEX_RESULT_FILE,
                {
                    "time": now_str(),
                    "request_id": request_id,
                    "status": "processed_with_errors" if errors else "processed",
                    "summary": (result or {}).get("message", "已处理 Codex 本地指令"),
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
                    "status": "error",
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
        hold_reasons: list[str] = []
        errors: list[str] = []
        for order in orders:
            if not isinstance(order, dict):
                errors.append(f"跳过无效指令：{order}")
                continue
            action = str(order.get("action") or "hold").lower()
            if action == "hold":
                reason = str(order.get("reason") or order.get("summary") or "")
                code = normalize_code(str(order.get("code") or "")) or str(order.get("code") or "")
                hold_reasons.append(f"{code + ': ' if code else ''}{reason or '保持观察'}")
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
                    qty = parse_order_quantity(qty_value) if qty_value not in (None, "") else None
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
                qty = parse_order_quantity(order.get("qty"))
            except Exception:
                qty = 0
            try:
                limit_price = float(order.get("limit_price"))
            except Exception:
                limit_price = 0.0
            if not code or qty <= 0 or action not in ("buy", "sell") or not math.isfinite(limit_price) or limit_price <= 0:
                errors.append(f"跳过无效指令：{order}")
                continue
            quote = self.quote_cache.get(code)
            if not quote:
                self.quote_cache.update(self.quotes.fetch([code]))
                quote = self.quote_cache.get(code)
            if not quote:
                errors.append(f"{code}: 暂时无法取得实时价格。")
                continue
            stale = quote_freshness_error(quote, dt.datetime.now())
            if stale:
                errors.append(f"{code}: {stale}")
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
        if not any([submitted, cancelled, updated, executed]) and hold_reasons and not errors:
            message = "本轮观察：未提交委托；" + "；".join(hold_reasons[:5])
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
                "hold_reasons": hold_reasons,
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
    configure_light_theme(app)
    if "--smoke-test" in sys.argv:
        from scripts.smoke_ui import run
        return run(app, sys.modules[__name__])
    icon_path = resource_path(ICON_FILE)
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    win = MainWindow()
    win.show_restored_window()
    return app.exec()


if __name__ == "__main__":
    # The panel imports application helpers lazily. Reuse this entry module so
    # frozen/script launches do not create a second set of runtime paths.
    sys.modules.setdefault("StockTradingSim", sys.modules[__name__])
    raise SystemExit(main())
