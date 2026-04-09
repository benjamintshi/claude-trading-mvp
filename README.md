# Claude Trader MVP

AI 驱动的加密期货交易系统。Claude 作为交易员，自主分析市场、发现机会、管理仓位。

## 架构

```
Claude (大脑)  →  binance.py (薄 API 层)  →  Binance 交易所 (7×24 执行引擎)
   决策/判断          发送指令                   止损/止盈/追踪止损自动执行
       ↑                                              ↓
   Skills 体系                                   自动执行止损/止盈
   (风控/熔断/复盘)                               (Claude 离线也生效)
```

**核心设计：**
- **Claude = 大脑** — 分析市场、做出决策、管理风控
- **Binance = 执行引擎** — 止损止盈由交易所 7×24 自动执行，不依赖 Claude 在线
- **binance.py = 薄包装** — 只做签名和 HTTP 请求，不含业务逻辑
- **paper.py = 模拟引擎** — Paper Trading 模式下替代真实执行
- **DB = 备份** — 仓位数据以 Binance 交易所为准，PostgreSQL 为备份记录
- **Cron = 心跳** — 每 15 分钟触发交易循环

## 快速开始

```bash
# 1. 配置
cp .env.example .env
# 编辑 .env 填入 Binance API key、Telegram token、DB URL
# 默认 PAPER_TRADING=true (模拟模式, 不花真钱)

# 2. 安装
./scripts/setup.sh

# 3. 手动交易 (Paper 模式 — 真实行情, 模拟执行)
claude                    # 进入 Claude Code
/scan                     # 扫描市场 (增强版: 技术指标 + 微观结构)
/open AVAXUSDT long 8.60 8.40 9.00 "急跌反弹" 9  # 开仓
/close AVAXUSDT "到达目标"  # 平仓
/positions                # 查看持仓 + 挂单状态
/trade-loop               # 完整交易循环

# 4. 自动交易（已通过 setup.sh 配置 cron）
# 每 15 分钟 Claude 自动：熔断检查 → 持仓管理 → 扫描 → 评分 → 交易
```

## Commands

| 命令 | 功能 |
|------|------|
| `/scan` | 动态筛选全市场 Top 50 币种，采集全量信号 (价格/OI/多空比/RSI/EMA/布林带/MACD) |
| `/open` | 开仓 — 一键下 3 单 (开仓 + 交易所端止损 + 止盈) |
| `/close` | 平仓 — 撤挂单 + 市价平仓 + 强制复盘 |
| `/positions` | 查看持仓 + 挂单健康状态 + 账户概览 |
| `/trade-loop` | 完整交易循环 (熔断 → 持仓管理 → 扫描 → 评分 → 开仓) |

## 信号评分系统（满分 14）

### 核心信号 (高权重)

| 信号 | 分值 | 数据源 |
|------|------|--------|
| 关键支撑/阻力位 (布林带 + 历史高低点) | +2 | `get_klines()` → `calc_bollinger()` |
| 24h 异常涨跌偏离大盘 | +2 | `get_ticker_24h()` |
| OI + 价格背离 (持仓量上升但价格反向) | +2 | `get_open_interest()` |

### 市场微观结构

| 信号 | 分值 | 数据源 |
|------|------|--------|
| Funding rate 拥挤方向的反向 | +1 | `get_funding_rate()` |
| 多空比极值 (> 2.0 或 < 0.5) | +1 | `get_long_short_ratio()` |
| 主动买卖量不平衡 | +1 | `get_taker_buy_sell_ratio()` |

### 技术指标 + 宏观

| 信号 | 分值 | 数据源 |
|------|------|--------|
| RSI(14) 超买/超卖 | +1 | `calc_rsi()` |
| EMA 趋势确认 (EMA12 vs EMA26) | +1 | `calc_ema()` |
| Fear & Greed 极值逆向 | +1 | Alternative.me API |
| 新闻催化剂 | +1 | WebSearch |
| 成交量放大 | +1 | `get_ticker_24h()` |

**≥ 8 分开仓 | 6-7 观察 | < 6 忽略**

## WebSocket 实时监控 (多 Agent)

```bash
python3 scripts/ws_runner.py   # 启动实时价格监控 (多 Agent 模式)
```

独立长驻进程，连接 Binance WebSocket 获取实时 mark price (ccxt.pro)。
价格进入警戒区时启动 **多 Agent 并行评估**：

```
触发 → 3 Agent 并行 (Bull/Bear/Analyst, ~20s) → Coordinator 汇总决策 (~30s) → 执行
```

| 触发类型 | 条件 | 冷却 | AI 决策 |
|---------|------|------|--------|
| 接近止损 | 距离 < 1.5% | 5 min | 提前平仓 or 持有 |
| 接近止盈 | 距离 < 2% | 10 min | 落袋 or 让利润跑 |
| 接近支撑 | 距离 < 1% (多仓) | 15 min | 支撑有效性评估 |
| 接近阻力 | 距离 < 1% (空仓) | 15 min | 阻力有效性评估 |
| ATR 突破 | 5min > 1.5x ATR | 10 min | 真突破 or 假突破 |

**多 Agent 架构：**
- **Bull Agent** — 只分析做多/持有的论据 (技术面支持、趋势延续证据)
- **Bear Agent** — 只分析做空/平仓的论据 (风险信号、动量衰竭)
- **Analyst** — 中立技术分析 (趋势、动量、波动率、概率判断)
- **Coordinator** — 综合三方观点，用决策规则做最终判断

**实时数据喂入 AI：**
- 1h 技术指标: RSI/MACD/EMA/布林带
- 5m 短周期信号: RSI/MACD/量能变化
- 实时盘口: Orderbook 买卖墙、买卖力量比
- OI 背离: 持仓量变化 + 异常度百分位

冷却: regime 自适应 (高波动缩短, 低波动延长)，每小时最多 6 次，同一 symbol 至少间隔 3 分钟。
`WS_MULTI_AGENT=false` 可回退单 Agent 模式。

## 开仓验证链

每次开仓必须按顺序通过 6 步验证:

```
regime-detect → bull-bear-debate → reasoning-audit → risk-check → correlation-check → adaptive-sizing → 执行
```

| 步骤 | Skill | 功能 | 拦截条件 |
|------|-------|------|---------|
| 1 | `regime-detect` | 识别 4 种市场状态 | 高波震荡 → 评分门槛 +2 |
| 2 | `bull-bear-debate` | 牛熊对辩 | 牛方 ≤ 熊方 + 2 → 不开仓 |
| 3 | `reasoning-audit` | 三角一致性检查 | 证据→推理→决策不一致 → 不开仓 |
| 4 | `risk-check` | 7 项硬门槛 | 任一项不通过 → 不开仓 |
| 5 | correlation-check | 持仓相关性 | >0.7 → 警告 (不硬拦) |
| 6 | adaptive-sizing | `calc_adaptive_risk_pct()` | 评分+状态→自适应仓位 |

## 信号反馈回路

- 平仓后自动记录每个信号的触发情况和胜负 (`record_trade_signals()`)
- 每 10 笔交易自动更新信号权重 (胜率>60% → +1, 胜率<40% → -1)
- `get_feedback_summary()` 查看信号胜率和权重变化
- 数据存储: `data/feedback/signal_history.json`

## Skills 体系

### 交易决策 Skills (自动触发)

| Skill | 触发时机 | 功能 |
|-------|---------|------|
| `regime-detect` | 扫描/循环开头 | 4 种市场状态识别，影响评分权重和仓位大小 |
| `bull-bear-debate` | 每次开仓前 | 牛熊对辩，牛方 > 熊方 + 3 才开仓 |
| `reasoning-audit` | 每次开仓前 | 三角一致性: 证据→推理→决策 + LLM 记忆偏误检测 |
| `smart-exit` | WebSocket 触发 | 多 Agent 智能平仓: Bull/Bear/Analyst→Coordinator 决策 |

### 交易风控 Skills (自动触发)

| Skill | 触发时机 | 功能 |
|-------|---------|------|
| `risk-check` | 每次开仓前 | 7 项强制检查 (HARD-GATE): 熔断/持仓数/余额/赔率/止损/评分/重复 |
| `correlation-check` | 每次开仓前 | 持仓相关性检查: >0.7 仓位减半，>0.9 建议放弃 |
| `adaptive-sizing` | 每次开仓前 | 评分+状态+相关性 → 自适应仓位 (0.25%-1.5%) |
| `circuit-breaker` | 每次循环开头 | 熔断器: 日亏>$100 / 余额<$500 / 保证金>80% / 连亏5笔 |
| `position-management` | 每次循环 | ATR 止损移动: 1ATR→保本, 2ATR→锁利, 3ATR→追踪 |
| `trade-journal` | 每次平仓后 | 复盘: 信号分析 + 时间衰减反馈 (每 10 笔更新权重) |

### 开发 Skills

| Skill | 功能 |
|-------|------|
| `tdd` | 测试驱动开发 |
| `test-gen` | 为已有代码补测试 |
| `bug-fix` | 系统化调试 |
| `code-review` | 代码审查 |
| `skill-router` | 自动发现和调用 Skills |

## Paper Trading (模拟交易)

```bash
# .env 设置
PAPER_TRADING=true        # 开启模拟模式
PAPER_INITIAL_BALANCE=2000  # 初始虚拟余额 (可选, 默认 $2000)
```

**工作原理：**
- 行情数据 (价格/K线/OI/funding) → 真实 Binance API
- 订单/持仓/PnL → 本地模拟 (存储在 `data/paper/`)
- 止损/止盈 → 每次 trade-loop 自动检查价格触发
- 所有 Command 和 Skill 零改动，自动适配

**模拟能力：**
- 市价单立即成交 (用真实价格)
- 止损单/止盈单/追踪止损 → 挂单等待触发
- 手续费模拟 (0.075% 双边)
- 保证金计算 (3x 杠杆)
- 每日 PnL 自动重置
- 完整交易记录 (`data/paper/trades.json`)

**查看统计：**
```python
from lib.paper import get_paper_stats, reset_paper
print(get_paper_stats())  # 胜率/总 PnL/最佳交易 等
reset_paper()             # 重置, 从头开始
```

**切换到实盘：**
```bash
PAPER_TRADING=false  # .env 改这一行即可
```

## 风控

| 参数 | 值 |
|------|---|
| 本金 | $2,000 |
| 单笔风险 | 自适应: 0.5%-1.5% (评分+状态决定) |
| 最大持仓 | 5 笔 |
| 同方向最多 | 3 笔 |
| 杠杆 | 3x |
| 赔率要求 | > 3:1 |
| 日亏熔断 | -$100 |
| 余额熔断 | < $500 |

## 技术指标 (纯 Python, 无第三方依赖)

全部从 Binance K 线数据计算：

| 指标 | 函数 | 用途 |
|------|------|------|
| RSI(14) | `calc_rsi()` | 超买超卖判断 |
| EMA(12/26) | `calc_ema()` | 趋势方向 + MACD |
| 布林带(20,2) | `calc_bollinger()` | 支撑阻力 + 波动率 |
| ATR(14) | `calc_atr()` | 止损距离 + 仓位管理 |
| MACD(12,26,9) | `calc_macd()` | 动量变化 |
| VWAP | `calc_vwap()` | 机构买卖压力 |
| `get_signal_snapshot()` | 聚合函数 | 一次调用返回全部 1h 信号 |
| `get_realtime_context()` | 实时上下文 | 盘口深度 + 5m 信号 + OI 背离 |

## 文件结构

```
claude-trading-mvp/
├── CLAUDE.md                          # MC 身份 + 交易规则 + 架构
├── README.md                          # 本文件
├── .claude/
│   ├── commands/                      # 交易命令
│   │   ├── scan.md                    #   扫描市场 (增强版)
│   │   ├── open.md                    #   开仓 (一键三单)
│   │   ├── close.md                   #   平仓 (撤单+平仓+复盘)
│   │   ├── positions.md               #   查看持仓
│   │   └── trade-loop.md              #   完整交易循环
│   ├── skills/                        # AI Skills
│   │   ├── regime-detect/             #   市场状态识别 (4种状态)
│   │   ├── bull-bear-debate/          #   牛熊对辩 (开仓前)
│   │   ├── reasoning-audit/           #   推理审计 (三角一致性)
│   │   ├── risk-check/                #   开仓前风控 (HARD-GATE)
│   │   ├── circuit-breaker/           #   熔断器
│   │   ├── position-management/       #   持仓止损管理
│   │   ├── trade-journal/             #   交易复盘
│   │   ├── smart-exit/                 #   WebSocket 智能平仓
│   │   ├── skill-router/              #   技能路由
│   │   ├── tdd/                       #   测试驱动
│   │   └── test-gen/                  #   测试生成
│   ├── hooks/                         # 安全钩子
│   │   ├── dangerous-command-blocker.py
│   │   ├── trading-safety-guard.py
│   │   └── quality-gate.py
│   ├── rules/                         # 行为规则
│   │   ├── python-conventions.md
│   │   ├── trading-safety.md
│   │   └── context-engineering.md
│   └── settings.json                  # 权限配置
├── lib/
│   ├── binance.py                     # Binance API 薄包装 (行情/订单/指标/信号/实时盘口)
│   ├── ws_monitor.py                  # WebSocket 触发引擎 + 多 Agent prompt 模板
│   ├── paper.py                       # Paper Trading 模拟引擎
│   ├── feedback.py                    # 信号反馈回路 (胜率统计+时间衰减+动态权重)
│   ├── db.py                          # PostgreSQL (备份)
│   └── notify.py                      # Telegram 通知
├── specs/
│   ├── trade-journal.md               # 交易日志 (自动追加)
│   └── trading-patterns.md            # 模式发现 (每 10 笔更新)
├── scripts/
│   ├── trade.sh                       # 自动交易 (cron)
│   ├── ws_runner.py                   # WebSocket 多 Agent 实时监控
│   └── setup.sh                       # 初始化
└── data/
    ├── paper/                         # Paper Trading 数据
    │   ├── positions.json             #   模拟持仓
    │   ├── orders.json                #   模拟挂单
    │   ├── trades.json                #   成交记录
    │   └── balance.json               #   虚拟余额
    ├── feedback/                      # 信号反馈数据
    │   ├── signal_history.json        #   每笔交易信号记录
    │   └── signal_weights.json        #   动态信号权重
    ├── logs/                          # 运行日志
    └── trades/                        # 交易报告
```

## 交易标的

Binance USDT 永续合约，**动态筛选**（不硬编码币种列表）：

```python
get_tradable_symbols(min_volume_usdt=50_000_000, top_n=50)
```

- 从全市场按 24h 成交额自动筛选 Top 50
- 新上热门币自动纳入，冷门币自动排除
- 排除稳定币对 (BUSD/USDC/TUSD/FDUSD/DAI)
