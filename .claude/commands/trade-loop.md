全自动交易循环。扫描市场、发现机会、自动开仓、管理持仓。

用法: /trade-loop

## 每次执行的完整流程

### 1. 检查现有持仓

```bash
cd ~/claude/claude-trading-mvp && python3 -c "
import sys; sys.path.insert(0, '.')
from lib.db import get_open_positions, get_stats
from lib.binance import get_price

positions = get_open_positions()
if positions:
    for p in positions:
        pos_id, symbol, side, entry, qty, stop, target = p[0], p[1], p[2], p[3], p[4], p[5], p[6]
        current = get_price(symbol)
        pnl = (current - entry) * qty if side == 'long' else (entry - current) * qty
        print(f'ID:{pos_id} {symbol} {side} entry:{entry} now:{current:.4f} PnL:\${pnl:+.2f} stop:{stop} target:{target}')
else:
    print('无持仓')
stats = get_stats()
if stats and stats[0]:
    print(f'历史: {stats[0]}笔 {stats[1]}W/{stats[2]}L PnL:\${stats[3]}')
"
```

对每个持仓判断：
- 触止损 → 平仓（用 /close）
- 到目标 → 平仓
- 持仓超 48h → 评估
- 市场条件变化 → 评估

### 2. 扫描市场

执行 /scan 的完整流程（获取价格、funding、F&G、搜索新闻）。

### 3. 信号叠加评分（满分 10）

**做多信号：**
- 关键支撑位 (+2)
- 24h 跌幅异常大于大盘 (+2)
- Funding 偏负（空头拥挤）(+1)
- Fear & Greed < 20 (+1)
- RSI < 30 (+1)
- 利好催化剂 (+1)
- 成交量放大 (+1)
- 高时间框架支持 (+1)

**做空信号：**
- 关键阻力位 (+2)
- 24h 涨幅异常大于大盘 (+2)
- Funding 偏正（多头拥挤）(+1)
- Fear & Greed > 80 (+1)
- RSI > 70 (+1)
- 利空催化剂 (+1)
- 成交量放大 (+1)
- 高时间框架支持 (+1)

**≥ 6 → 开仓 | 4-5 → 观察 | < 4 → 忽略**

### 4. 执行开仓

```bash
cd ~/claude/claude-trading-mvp && python3 -c "
import sys; sys.path.insert(0, '.')
from lib.binance import calc_quantity, get_price
from lib.db import open_position
from lib.notify import notify_open

symbol = 'XXXUSDT'
side = 'long'  # or 'short'
entry = get_price(symbol)
stop = 0.0   # 设止损
target = 0.0 # 设目标
reason = ''
score = 0

qty = calc_quantity(symbol, 2000, 0.01, entry, stop, 3)
pos_id = open_position(symbol, side, entry, stop, target, qty, reason, score)
notify_open(symbol, side, entry, stop, target, reason, qty, score)
"
```

### 5. 执行平仓

```bash
cd ~/claude/claude-trading-mvp && python3 -c "
import sys; sys.path.insert(0, '.')
from lib.db import close_position
from lib.notify import notify_close
result = close_position(POS_ID, EXIT_PRICE, '理由')
if result:
    notify_close(SYMBOL, SIDE, ENTRY, EXIT_PRICE, result['pnl'], result['pnl_pct'], result['duration_hours'], '理由')
"
```

### 6. 输出报告

```
⏰ 交易循环 — {时间}
━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 市场: BTC ${price} | F&G: {value}
📰 新闻: {headline}
📂 持仓: {N} 笔 | 操作: {开仓/平仓/维持}
🎯 机会: {symbol} {方向} 得分 {X}/10
💰 累计: ${pnl} | 胜率: {wr}%
```

### 规则
- 没有好机会不开仓
- 最多 5 笔持仓
- 同方向最多 3 笔
