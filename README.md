# AIStockSim - AI模拟炒股及摸鱼盯盘工具

一个面向 Windows 的轻量 AI 模拟炒股及摸鱼盯盘工具：既能像透明盯盘小窗一样贴在屏幕角落看盘，也能在主界面里用真实行情练习虚拟买卖、复盘持仓、比较自己和 AI/Codex 的模拟操作。

如果你想找一个不连接真实证券账户、但尽量贴近交易纪律的 A 股/港股模拟盘，同时又想保留一个低调的摸鱼盯盘浮窗，欢迎试用。觉得有用的话，点个 Star 就是最好的鼓励。

## 核心亮点

* **A 股 + 港股行情**：支持沪深京股票和 `hk01810` 这类港股代码。
* **港股实时感更好**：港股优先使用东方财富行情源，实测没有新浪港股接口常见的 15 分钟延迟；失败时回退新浪 `rt_hk`。
* **限价委托撮合**：买入在 `现价 <= 委托价` 时成交，卖出在 `现价 >= 委托价` 时成交。
* **模拟交易规则**：支持 T+1、可卖数量、可用现金、买入委托资金冻结、A 股/港股每手数量校验。
* **持仓复盘**：区分“交易均价”和“摊余回本价”，适合复盘真实交易中历史亏损摊到剩余持仓后的回本目标。
* **主界面 + 盯盘模式**：主界面做模拟交易，盯盘模式复用透明浮窗能力，支持拖动、右键指标开关、颜色、字体、K 线和设置面板。
* **AI/Codex 指令接入**：OpenAI-compatible API 或 Codex 可以生成 JSON 限价委托，软件负责按交易规则撮合并留痕。
* **本机隐私**：账户、持仓、委托和交易记录只保存在本机 `%APPDATA%\StockTradingSim`，源码仓库不包含任何个人持仓数据。

## 适合谁

* 想练习交易纪律，但不想拿真金白银试错。
* 想用真实行情做轻量模拟盘，而不是复杂回测平台。
* 想盯 A 股和港股，尤其需要港股更及时的价格显示。
* 想比较“自己操作”和“AI/Codex 模拟操作”的结果。

## 使用方式

右侧 Releases 如果有打包好的 Windows 版 `StockTradingSim.exe`，可直接下载运行。

通过源码运行：

```powershell
pip install PySide6 requests
python .\StockTradingSim.py
```

打包：

```powershell
pip install pyinstaller
python -m PyInstaller .\StockTradingSim.spec --clean --noconfirm
```

## 配置文件

模拟账户数据：

```text
%APPDATA%\StockTradingSim\portfolio.json
```

Codex 本地指令文件：

```text
%APPDATA%\StockTradingSim\codex_orders.json
```

这些文件不会随源码仓库上传。`.gitignore` 也会忽略同名本地导出文件，避免误提交账户数据。

## AI/Codex 指令格式

```json
[
  {
    "action": "buy",
    "code": "hk01810",
    "qty": 200,
    "limit_price": 28.0,
    "reason": "回调到目标价后模拟买入"
  },
  {
    "action": "sell",
    "code": "sh688270",
    "qty": 100,
    "limit_price": 95.5,
    "reason": "反弹到目标价后模拟卖出"
  }
]
```

`action` 支持 `buy`、`sell`、`hold`。`hold` 不执行交易。`buy` 和 `sell` 必须提供 `limit_price`。

## 当前规则边界

* 这是模拟交易软件，不连接真实证券账户。
* 当前版本暂不计算手续费、印花税、滑点和汇率。
* 港股每手股数保存在 `board_lots` 配置里；已预置部分常见代码，未知港股先按 100 股一手处理。
* A 股与港股资金暂按同一个模拟资金池计算，适合用于策略对比和练习，不适合做精确回测。

## 致谢

本项目的透明盯盘浮窗能力基于 [sbr0574/StockWidget](https://github.com/sbr0574/StockWidget) 的开源实现继续扩展。感谢原作者提供轻量、实用的 Windows 股票浮窗基础。
