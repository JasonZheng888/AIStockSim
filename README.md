
# AIStockSim - AI模拟炒股及摸鱼盯盘工具

当前版本：`3.1.0`

> `3.1.0` 修复历史日 K 刷新链路：手动“立即刷新行情”会同步刷新日线，自动刷新会补齐落后的日线缓存，启动后也会延迟检查并更新 `codex_kline_history.json`，避免 AI/Codex 读到过期 K 线。`3.0.0` 引入 CAN SLIM/《笑傲股市》启发的策略组合系统：用户可在设置里勾选策略，软件会生成市场环境闸门、CAN SLIM 纪律雷达和 AI 可读策略说明。

一个面向 Windows 的轻量 AI 模拟炒股及摸鱼盯盘工具：既能像透明盯盘小窗一样贴在屏幕角落看盘，也能在主界面里用真实行情练习虚拟买卖、复盘持仓、比较自己和 AI/Codex 的模拟操作。

适合需要 A 股/港股模拟交易、轻量复盘和低调盯盘的个人用户。项目不连接真实证券账户，只做本地模拟和行情展示；觉得有用的话，欢迎点 Star 支持。

## 核心亮点

* **A 股 + 港股行情**：支持沪深京股票和 `hk01810` 这类港股代码。
* **港股实时感更好**：港股优先使用东方财富行情源，实测没有新浪港股接口常见的 15 分钟延迟；失败时回退新浪 `rt_hk`。
* **限价委托撮合**：买入在 `现价 <= 委托价` 时成交，卖出在 `现价 >= 委托价` 时成交。
* **模拟交易规则**：支持 T+1、可卖数量、可用现金、买入委托资金冻结、A 股/港股每手数量校验。
* **持仓与账户复盘**：区分“当前持仓成本”和“摊余回本价”，同时记录账户曲线、回撤、操作者表现和交易质量提示。
* **策略信号**：行情表内置轻量趋势、RSI 采样、A 股主力资金流和风控提示，帮助用户快速判断自选股状态。
* **历史日 K 技术画像**：尽量拉取接口返回的全部可用日 K，计算 MA5/10/20/60/120/250、量能、支撑压力、缺口、MACD、KDJ 和 20/60 日收益。
* **日线自动补齐**：手动刷新会强制更新日 K；自动刷新和启动补齐会只拉取落后的股票，兼顾数据新鲜度和后台性能。
* **历史K缓存复用**：完整日 K 会写入 `codex_kline_history.json`；软件启动时会加载本地缓存，即使当次网络拉取失败，AI/Codex 快照也能继续使用历史技术画像。
* **分时/VWAP 画像**：拉取当日分时，提供 VWAP/均价线、近 5/15/30 分钟变化和尾盘强弱信号，供 AI 托管参考。
* **CAN SLIM 策略组合**：内置市场环境闸门、强势股雷达、买点纪律、卖出纪律、分时/VWAP 执行、组合仓位纪律和交易复盘策略。
* **策略可勾选**：在“设置 - 策略组合”中可启用/停用单项策略，每项都有定义、作用、输入、输出、AI 调用方式和硬规则说明。
* **CAN SLIM 纪律雷达**：按市场环境、日 K 趋势、相对强弱、资金需求、买点质量和卖出纪律给自选股/持仓评分并分桶；缺失 EPS、营收、ROE 等基本面数据时会明确提示。
* **AI 首次接入友好**：`strategy_context.strategy_pack` 会写入启用策略、详细定义、禁止事项和推荐输出格式，避免新 AI 靠猜测交易体系。
* **市场闸门风控**：软件自动参考上证指数、深证成指、创业板指；启用市场闸门后，大盘红灯会拦截新开多仓。
* **下单风控**：支持 ST 买入限制、不追高、亏损持仓只减不加、临近收盘禁止开新仓、单票最大仓位、单笔最大买入和同代码活动委托上限，用户和 AI/Codex 指令都会经过校验。
* **AI 多智能体分析**：填写 OpenAI-compatible API 后，由外部 AI 基于行情、A 股资金流、持仓、委托、复盘、风控和策略上下文生成技术面、CAN SLIM 纪律、资金情绪、风险经理和组合经理报告。
* **Markdown 报告落盘**：每次 AI 多智能体分析成功后，会在 `StockTradingSim.exe` 同目录生成带时间戳的 `.md` 报告，并同步更新 `AIStockSim_最新AI分析报告.md`。
* **内置策略上下文**：本地趋势、RSI、资金流、仓位风控和交易质量统计只作为 `strategy_context` 提供给 AI 参考，不再冒充 AI 结论。
* **2.x 工作台**：引入左侧导航、AI 工作台、报告中心、候选指令审批区和角色化 agent pipeline。
* **可配置 AI Pipeline**：可启用/停用技术面、资金流、新闻/情绪、风险经理、组合经理等 agent，并设置 AI 分析失败重试次数。
* **候选指令审批预审**：AI 候选 JSON 指令会先展示现金、T+1、每手数量、交易时段和风控预审结果，通过后仍需用户确认才能执行。
* **Agent Chatroom**：可围绕当前行情、持仓、风控审计、策略上下文和最新 AI 报告追问，AI 只输出解释和建议，不直接下单。
* **策略中心**：公开趋势、历史日 K、均线、RSI、MACD/KDJ、资金流、仓位风控、交易规则、交易质量和账户曲线等本地策略信号，并同步提供给 AI。
* **组合再平衡建议**：本地规则会把仓位集中、现金不足、ST 风险、T+1 和活动委托转成组合经理可参考的调整提示。
* **主界面 + 盯盘模式**：主界面做模拟交易，盯盘模式复用透明浮窗能力，支持拖动、右键指标开关、颜色、字体、K 线和设置面板。
* **AI/Codex 指令接入**：外部 AI 可生成 JSON 限价委托、撤单和改价；Codex 也可通过本地 JSON 文件接管模拟操作。
* **Codex 文件桥**：运行中自动读取 `codex_orders.json`，执行后写入带 `status` 和 `request_id` 的 `codex_result.json` 并清空指令；同时持续导出 `codex_snapshot.json` 供 Codex 分析账户状态。
* **Codex K 线文件**：完整历史日 K 单独写入 `codex_kline_history.json`，快照里保留技术摘要和文件路径，便于托管时深挖历史结构。
* **AI 托管日志**：每次 AI 建议、JSON 执行、风控失败和委托撮合都会记录到日志页，便于回看自动化到底做了什么。
* **总览工作台**：启动后先看账户、风险、自选策略信号、持仓快照和最新多智能体结论，再进入下单或复盘页面。
* **单文件免安装**：Release 提供打包好的单文件 `StockTradingSim.exe`，Windows 用户下载后可直接双击运行。
* **本机数据**：账户、持仓、委托和交易记录保存在本机 `%APPDATA%\StockTradingSim`，便于备份、迁移或清理。

## 效果展示

盯盘模式可以低调贴在屏幕角落，适合在不打断当前工作的情况下查看价格和涨跌幅。
<img width="1848" height="894" alt="盯盘模式效果" src="https://github.com/user-attachments/assets/5027a52e-6e77-4f78-a833-4d0d97a3f550" />

## 适合谁

* 想练习交易纪律，但不想拿真金白银试错。
* 想用真实行情做轻量模拟盘，而不是复杂回测平台。
* 想盯 A 股和港股，尤其需要港股更及时的价格显示。
* 想比较“自己操作”和“AI/Codex 模拟操作”的结果。

## 使用方式

右侧 Releases 有打包好的单文件 `StockTradingSim.exe`，Windows 用户可直接下载，双击运行。

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

Codex 账户快照文件：

```text
%APPDATA%\StockTradingSim\codex_snapshot.json
```

Codex 执行结果文件：

```text
%APPDATA%\StockTradingSim\codex_result.json
```

Codex 完整历史日 K 文件：

```text
%APPDATA%\StockTradingSim\codex_kline_history.json
```

软件运行时会自动轮询 `codex_orders.json`。Codex 或其它自动化只需要读取 `codex_snapshot.json` 和 `codex_kline_history.json`，写入 `codex_orders.json`，软件就会按模拟盘规则执行，随后把结果写入 `codex_result.json` 并清空指令文件，避免重复下单。

这些文件包含模拟账户、交易记录和 AI 配置等个人数据。公开分享截图、压缩包或反馈问题时，请避免附带真实账户配置文件。

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
    "code": "sh600000",
    "qty": 100,
    "limit_price": 12.5,
    "reason": "反弹到目标价后模拟卖出"
  }
]
```

`action` 支持 `buy`、`sell`、`hold`、`cancel`、`amend`。`hold` 不执行交易。`buy` 和 `sell` 必须提供 `limit_price`。

撤单和改价示例：

```json
[
  {
    "action": "amend",
    "code": "sh600000",
    "side": "sell",
    "qty": 100,
    "limit_price": 12.8,
    "reason": "调整未成交卖单价格"
  },
  {
    "action": "cancel",
    "code": "sh600000",
    "side": "sell",
    "reason": "取消旧委托"
  }
]
```

如果同一代码、同一方向存在多条活动委托，请使用 `order_id` 精确匹配，避免误撤或误改。

## 当前规则边界

* 这是模拟交易软件，不连接真实证券账户。
* 当前版本暂不计算手续费、印花税、滑点和汇率。
* 港股每手股数保存在 `board_lots` 配置里；已预置部分常见代码，未知港股先按 100 股一手处理。
* A 股与港股资金暂按同一个模拟资金池计算，适合用于策略对比和练习，不适合做精确回测。

## 致谢

本项目的透明盯盘浮窗能力基于 [sbr0574/StockWidget](https://github.com/sbr0574/StockWidget) 的开源实现继续扩展。感谢原作者提供轻量、实用的 Windows 股票浮窗基础。
