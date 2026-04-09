平仓交易。用法: /close AVAXUSDT "反弹到目标位"

参数: /close {symbol} {reason}
无参数时显示所有持仓供选择。

## 执行步骤

### 1. 查看持仓 (从 Binance 获取真实数据)

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from lib.binance import get_position_risk, get_open_orders

# 从交易所获取真实仓位
positions = get_position_risk()
active = [p for p in positions if float(p.get('positionAmt', 0)) != 0]

if not active:
    print('无持仓')
else:
    for p in active:
        symbol = p['symbol']
        amt = float(p['positionAmt'])
        side = 'LONG' if amt > 0 else 'SHORT'
        entry = float(p['entryPrice'])
        mark = float(p['markPrice'])
        pnl = float(p['unRealizedProfit'])
        liq = float(p.get('liquidationPrice', 0))
        print(f'{symbol} {side} qty:{abs(amt)} entry:\${entry:.4f} mark:\${mark:.4f} PnL:\${pnl:+.2f} 强平:\${liq:.2f}')
        
        # 该仓位的挂单
        orders = get_open_orders(symbol)
        for o in orders:
            print(f'  └ {o[\"type\"]} {o[\"side\"]} @\${float(o[\"stopPrice\"]):,.4f}' if o.get('stopPrice') and float(o['stopPrice']) > 0 else f'  └ {o[\"type\"]} {o[\"side\"]}')
"
```

### 2. 平仓 (撤挂单 + 市价平仓)

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from lib.binance import cancel_all_orders, close_long, close_short, get_price, get_position_risk
from lib.db import close_position, get_open_positions
from lib.notify import notify_close

symbol = '{symbol}'
reason = '{reason}'

# 1. 撤销该 symbol 全部挂单 (止损/止盈)
cancel_all_orders(symbol)
print(f'已撤销 {symbol} 全部挂单')

# 2. 获取仓位信息
positions = get_position_risk(symbol)
pos = [p for p in positions if float(p.get('positionAmt', 0)) != 0]
if not pos:
    print('❌ 无仓位')
else:
    p = pos[0]
    amt = float(p['positionAmt'])
    entry = float(p['entryPrice'])
    exit_price = get_price(symbol)
    
    # 3. 市价平仓
    if amt > 0:
        close_long(symbol, abs(amt))
        side = 'long'
    else:
        close_short(symbol, abs(amt))
        side = 'short'
    
    # 4. 计算 PnL
    if side == 'long':
        pnl = (exit_price - entry) * abs(amt)
    else:
        pnl = (entry - exit_price) * abs(amt)
    commission = (entry * abs(amt) + exit_price * abs(amt)) * 0.00075
    pnl -= commission
    pnl_pct = pnl / (entry * abs(amt)) * 100
    
    print(f'✅ 平仓成功 {symbol} {side} PnL:\${pnl:+.2f} ({pnl_pct:+.1f}%)')
    
    # 5. 更新 DB + 通知
    db_positions = get_open_positions()
    for dp in db_positions:
        if dp[1] == symbol:
            close_position(dp[0], exit_price, reason)
            break
    notify_close(symbol, side, entry, exit_price, pnl, pnl_pct, 0, reason)
"
```

### 3. 记录信号反馈 + 强制复盘

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from lib.feedback import record_trade_signals

symbol = '{symbol}'
side = '{side}'  # long/short
score = {开仓时的评分}
result = '{'win' if pnl > 0 else 'loss'}'
pnl_value = {pnl的数值}

# 记录开仓时哪些信号触发了 (从开仓记录/trade-journal 回顾)
signals = {
    'support_resistance': {True/False},
    'abnormal_divergence': {True/False},
    'oi_divergence': {True/False},
    'funding_rate': {True/False},
    'long_short_ratio': {True/False},
    'taker_ratio': {True/False},
    'rsi_extreme': {True/False},
    'ema_trend': {True/False},
    'fear_greed': {True/False},
    'news_catalyst': {True/False},
    'volume_expansion': {True/False},
}

entry = record_trade_signals(symbol, side, score, signals, result, pnl_value)
print(f'✅ 信号反馈已记录: {result} \${pnl_value:+.2f}')
print(f'  累计 {len(signals)} 个信号触发情况已存储，每 10 笔自动更新权重')
"
```

### 4. 记录交易备忘录 (必须)

平仓后**必须**记录你的分析思路:

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from lib.trade_memo import record_close
path = record_close(
    symbol='{symbol}', side='SIDE',
    entry=ENTRY, exit_price=EXIT,
    pnl=PNL, pnl_pct=PNL_PCT,
    duration_hours=HOURS,
    reason='{reason}',
    analysis='''你的复盘分析:
- 入场判断是否正确
- 止损/止盈设置是否合理
- 持仓期间市场发生了什么
- AI 决策质量如何''',
    lessons='''经验教训:
- 下次类似情况应该怎么做
- 有什么可以改进的''',
)
print(f'备忘录: {path}')
"
```

### 规则
- 平仓前先撤掉该 symbol 的全部挂单
- 平仓后必须记录交易备忘录 (trade_memo.record_close)
- 复盘必须包含: 分析 + 教训，不能只写"到目标了"
