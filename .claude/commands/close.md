平仓交易。用法: /close AVAXUSDT "反弹到目标位"

参数: /close {symbol} {reason}
无参数时显示所有持仓供选择。

## 执行步骤

### 1. 查看持仓 + 当前价格

```bash
cd ~/claude/claude-trading-mvp && python3 -c "
import sys; sys.path.insert(0, '.')
from lib.db import get_open_positions
from lib.binance import get_price

positions = get_open_positions()
if not positions:
    print('无持仓')
else:
    for p in positions:
        pos_id, symbol, side, entry, qty, stop, target = p[0], p[1], p[2], p[3], p[4], p[5], p[6]
        try:
            current = get_price(symbol)
            pnl = (current - entry) * qty if side == 'long' else (entry - current) * qty
            pnl_pct = pnl / (entry * qty) * 100
            print(f'ID:{pos_id} {symbol} {side} entry:\${entry:.4f} now:\${current:.4f} PnL:\${pnl:+.2f} ({pnl_pct:+.1f}%)')
        except:
            print(f'ID:{pos_id} {symbol} {side} entry:\${entry:.4f}')
"
```

### 2. 平仓

```bash
cd ~/claude/claude-trading-mvp && python3 -c "
import sys; sys.path.insert(0, '.')
from lib.db import close_position, get_open_positions
from lib.binance import get_price
from lib.notify import notify_close

pos_id = {position_id}
exit_price = get_price('{symbol}')
reason = '{reason}'

result = close_position(pos_id, exit_price, reason)
if result:
    # 获取原始持仓信息用于通知
    notify_close('{symbol}', '{side}', {entry_price}, exit_price,
                 result['pnl'], result['pnl_pct'], result['duration_hours'], reason)
    print(f'✅ 平仓成功 PnL:\${result[\"pnl\"]:+.2f} ({result[\"pnl_pct\"]:+.1f}%)')
else:
    print('❌ 平仓失败（持仓不存在或已关闭）')
"
```
