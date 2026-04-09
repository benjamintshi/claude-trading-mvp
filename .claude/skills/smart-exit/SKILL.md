---
name: smart-exit
description: >-
  AI 智能平仓决策。由 WebSocket 实时价格监控触发，当价格接近关键位时
  评估是否调整止损、部分平仓、全部平仓或让利润奔跑。
allowed-tools: Read, Bash
---

# 智能平仓决策

## 铁律

```
不是每次触发都要行动。数据不支持变更时，HOLD 是最好的决策。
```

## 触发来源

WebSocket 实时监控检测到以下情况之一:
1. **接近止损** (距离 < 1.5%) — 评估是否提前平仓避免滑点
2. **接近止盈** (距离 < 2%) — 评估是否让利润奔跑
3. **接近支撑/阻力** — 评估关键位有效性
4. **ATR 突破** (5min > 1.5x ATR) — 评估突破有效性

## 决策流程

### 1. 获取最新数据

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from lib.binance import get_signal_snapshot, get_position_risk, get_open_orders, get_klines, calc_atr, detect_regime

symbol = '{symbol}'
s = get_signal_snapshot(symbol)
print(f'RSI: {s[\"rsi\"]:.0f} | MACD柱: {s[\"macd\"][\"histogram\"]:+.4f} | EMA趋势: {s[\"ema_trend\"]}')
print(f'Funding: {s[\"funding_rate\"]*100:+.4f}% | 多空比: {s[\"long_short_ratio\"]:.2f} | Taker: {s[\"taker_buy_sell_ratio\"]:.2f}')

klines = get_klines('BTCUSDT', '1h', 100)
regime = detect_regime(klines)
print(f'市场状态: {regime[\"regime_cn\"]}')
"
```

### 2. 根据触发类型决策

#### 接近止损 → 应该提前平仓吗？

| 信号 | 提前平仓 | 继续持有 |
|------|---------|---------|
| RSI 进一步恶化 (多仓 RSI<25 / 空仓 RSI>75) | ✅ | |
| 成交量放大 + 价格加速向止损方向 | ✅ | |
| 支撑/阻力仍在 + 反转信号出现 | | ✅ |
| OI 增加 + 对手方拥挤 | | ✅ (轧空/轧多可能) |

#### 接近止盈 → 应该让利润跑吗？

| 信号 | 落袋为安 | 让利润跑 |
|------|---------|---------|
| RSI 极端 (>80 多 / <20 空) | ✅ | |
| 成交量萎缩 + 动量减弱 | ✅ | |
| 趋势强劲 + MACD 加速 | | ✅ 撤止盈→追踪止损 |
| 突破关键阻力/支撑 | | ✅ 上调目标 |

#### ATR 突破 → 有效突破还是假突破？

| 信号 | 假突破 (平仓/收紧) | 有效突破 (持有/加仓) |
|------|-------------------|-------------------|
| 成交量未放大 | ✅ | |
| 快速回撤 > 50% | ✅ | |
| OI 大幅增加 + 成交量放大 | | ✅ |
| 突破后价格在新区间稳定 | | ✅ |

### 3. 执行决策

| 决策 | 执行方式 |
|------|---------|
| **HOLD** | 不做任何操作 |
| **ADJUST_STOP** | `cancel_all_orders(symbol)` → 重新下止损单 |
| **PARTIAL_CLOSE** | 平掉 50% 仓位，剩余仓位收紧止损 |
| **FULL_CLOSE** | `/close {symbol} "触发原因"` |
| **LET_RUN** | 撤止盈 → `place_trailing_stop()` 追踪止损 |

### 4. 通知

决策完成后通过 Telegram 通知:
```
🔔 WS 智能平仓
{symbol} {side} — {决策}
触发: {trigger_type} @${price}
理由: {一句话}
```

## 规则
- 获取最新数据后再决策，不能只看触发时的价格
- **先判断市场状态 (regime)**，高波动下更积极保护利润
- HOLD 是默认选择，需要明确理由才行动
- 部分平仓至少 50%，不做 10% 20% 的微操
- 追踪止损回调率: 低波动 1%, 高波动 2%
- 每次决策必须记录理由

## 市场状态对决策的影响

| 状态 | 对 near_stop 决策 | 对 near_tp 决策 | 追踪回调率 |
|------|------------------|----------------|-----------|
| 低波趋势 | 可更耐心持有 | LET_RUN 优先 | 1% |
| 高波趋势 | 尽早保护 | 部分落袋 | 2% |
| 低波震荡 | 正常判断 | 落袋为安 | 1% |
| 高波震荡 | 积极平仓 | 落袋为安 | 2% |
