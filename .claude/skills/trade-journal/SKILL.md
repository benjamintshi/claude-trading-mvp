---
name: trade-journal
description: >-
  Use after every position close. Automatically analyzes the trade: why it won or lost,
  what signals were right/wrong, and records lessons. Iron law: no close without review.
allowed-tools: Read, Bash, Write, Grep
disable-model-invocation: true
---

# 交易复盘

## 铁律

```
每次平仓后必须复盘，记录到交易日志
```

## 流程

### 1. 收集交易数据

平仓后立即从 Binance 获取真实数据：

```python
from lib.binance import get_user_trades, get_income_history

# 成交记录 — 真实成交价和手续费
trades = get_user_trades(symbol, limit=10)

# 盈亏记录 — 真实 PnL (含手续费和 funding)
income = get_income_history(symbol=symbol)
# 过滤: REALIZED_PNL + FUNDING_FEE + COMMISSION
```

### 2. 分析

回答以下问题：

**如果赢了：**
- 哪个信号是最关键的？（价格行为？funding？新闻？）
- 入场时机好不好？（有没有更好的入场点？）
- 止盈位合不合适？（到了目标还是提前出的？）
- 持仓时间合理吗？
- 有没有吃到 funding fee？(做空高 funding 的品种 = 额外收益)

**如果亏了：**
- 入场理由是什么？现在看对不对？
- 哪个信号误导了你？
- 止损设得合不合适？（太紧被扫？太松亏太多？）
- 是不是逆势交易？（大盘走反方向）
- 有没有忽略某个警告信号？

**无论输赢：**
- 开仓时的评分 (score) 事后看合理吗？
- 同方向同时间的其他币表现如何？（选择偏差检查）
- 风控规则执行了吗？（止损移动了吗？追踪止损开了吗？）

### 3. 记录

写入 `specs/trade-journal.md`（追加模式）：

```markdown
## {日期} {symbol} {side} — {结果 WIN/LOSS}

**进出:** ${entry} → ${exit} | PnL: ${pnl} ({pnl_pct}%) | 持仓: {hours}h
**评分:** {score}/10
**入场理由:** {reason_open}
**平仓理由:** {reason_close}

**复盘:**
- 关键信号: {最重要的信号是什么}
- 信号准确度: {哪些对了，哪些错了}
- 止损执行: {移了保本吗？追踪止损开了吗？}
- 改进: {下次类似情况应该怎么做}

**Funding 收益:** ${funding_total}
**手续费:** ${commission_total}

---
```

### 4. 模式识别

每 10 笔交易后，回顾 trade-journal.md 寻找模式：

- **高胜率信号组合** — 哪些信号叠加最容易赢？
- **亏损模式** — 反复在什么情况下亏？（逆大盘？追涨？止损太紧？）
- **时间模式** — 什么时间段开仓胜率高/低？
- **币种偏好** — 哪些币更适合当前市场？
- **funding 收益** — funding fee 对总 PnL 的贡献

将发现记录到 `specs/trading-patterns.md`。

## 输出

每次复盘后输出简短总结：
```
📝 交易复盘: AVAXUSDT LONG — WIN
━━━━━━━━━━━━━━━━
💰 $8.60 → $9.00 | +$X (+X.X%) | 12.5h
🎯 关键信号: 支撑位反弹 + funding 负值
📚 教训: 止盈设在整数关口效果好
已记录到 specs/trade-journal.md
```

## 下一步
- 需要看整体统计? → `get_income_history()` 拿全量数据
- 发现反复亏损模式? → 记录到 `/knowledge`
- 需要调整策略? → 更新 CLAUDE.md 交易规则
