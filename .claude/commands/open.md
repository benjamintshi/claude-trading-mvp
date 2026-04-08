开仓交易。用法: /open AVAXUSDT long 8.60 8.40 9.00 "急跌反弹机会"

参数: /open {symbol} {long|short} {entry} {stop} {target} {reason}

## 执行步骤

### 1. 风控检查

```bash
cd ~/claude/claude-trading-mvp && python3 -c "
import sys; sys.path.insert(0, '.')
from lib.db import get_open_positions, get_config
positions = get_open_positions()
print(f'当前持仓: {len(positions)} 笔')
max_pos = int(get_config('max_positions') or 5)
if len(positions) >= max_pos:
    print('❌ 持仓已满')
else:
    print('✅ 可以开仓')
"
```

风控规则:
- 最大同时持仓: 5 笔
- 单笔风险: $20 (1% of $2000)
- 止损距离: 0.5%-5%
- 赔率 > 1.5:1

### 2. 计算仓位并开仓

```bash
cd ~/claude/claude-trading-mvp && python3 -c "
import sys; sys.path.insert(0, '.')
from lib.binance import calc_quantity, get_price
from lib.db import open_position
from lib.notify import notify_open

symbol = '{symbol}'
side = '{direction}'
entry = float('{entry_price}')  # 或 get_price(symbol)
stop = float('{stop_loss}')
target = float('{target_price}')
reason = '{reason}'
score = 0  # 填入评分

qty = calc_quantity(symbol, 2000, 0.01, entry, stop, 3)
risk = abs(entry - stop) * qty
reward = abs(target - entry) * qty
ratio = reward / risk if risk > 0 else 0

print(f'仓位: {qty:.4f} {symbol}')
print(f'名义值: \${qty * entry:.0f}')
print(f'风险: \${risk:.2f} | 收益: \${reward:.2f} | 赔率: {ratio:.1f}:1')

if ratio < 1.5:
    print('❌ 赔率不足')
else:
    pos_id = open_position(symbol, side, entry, stop, target, qty, reason, score)
    notify_open(symbol, side, entry, stop, target, reason, qty, score)
    print(f'✅ 开仓成功 ID:{pos_id}')
"
```
