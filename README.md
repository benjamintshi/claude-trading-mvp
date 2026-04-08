# Claude Trader MVP

AI 驱动的加密期货交易系统。Claude 作为交易员，自主分析市场、发现机会、管理仓位。

## 架构

```
Claude（大脑）→ 分析市场 + 判断机会 + 决定交易
    ↓
Python（手）→ Binance API 下单 + DB 记录 + Telegram 通知
    ↓
Cron（心跳）→ 每 15 分钟自动执行交易循环
```

## 快速开始

```bash
# 1. 配置
cp .env.example .env
# 编辑 .env 填入 Binance API key、Telegram token、DB URL

# 2. 安装
./scripts/setup.sh

# 3. 手动交易
claude                    # 进入 Claude Code
/scan                     # 扫描市场
/open AVAXUSDT long 8.60 8.40 9.00 "急跌反弹"  # 开仓
/close AVAXUSDT "到达目标"  # 平仓
/positions                # 查看持仓

# 4. 自动交易（已通过 setup.sh 配置 cron）
# 每 15 分钟 Claude 自动：扫描 → 评估 → 交易 → 通知
```

## Skills

| 命令 | 功能 |
|------|------|
| `/scan` | 扫描 15 个币种，发现交易机会 |
| `/open` | 开仓（自动计算仓位、风控检查） |
| `/close` | 平仓（计算 PnL、记录交易） |
| `/trade-loop` | 完整交易循环（持仓管理 + 扫描 + 交易） |

## 信号评分系统（满分 10）

| 信号 | 分值 |
|------|------|
| 关键支撑/阻力位 | +2 |
| 24h 异常涨跌 | +2 |
| Funding rate 反向 | +1 |
| Fear & Greed 极值 | +1 |
| RSI 超买/超卖 | +1 |
| 新闻催化剂 | +1 |
| 成交量确认 | +1 |
| 高时间框架支持 | +1 |

**≥ 6 分开仓 | 4-5 观察 | < 4 忽略**

## 风控

- 本金: $2,000
- 单笔风险: 1% ($20)
- 最大持仓: 5 笔
- 杠杆: 3x
- 赔率要求: > 1.5:1

## 文件结构

```
claude-trading-mvp/
├── CLAUDE.md              # MC 身份 + 交易规则
├── .claude/commands/      # Skills
├── lib/
│   ├── binance.py         # Binance API
│   ├── db.py              # PostgreSQL
│   └── notify.py          # Telegram
├── scripts/
│   ├── trade.sh           # 自动交易（cron）
│   ├── setup.sh           # 初始化
│   └── positions.sh       # 查看持仓
└── data/
    ├── logs/              # 运行日志
    └── trades/            # 交易报告
```
