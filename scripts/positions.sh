#!/bin/bash
# Show current positions and stats
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
set -a; source .env 2>/dev/null; set +a

python3 -c "
import sys; sys.path.insert(0, '.')
from lib.db import get_open_positions, get_stats
from lib.binance import get_price

positions = get_open_positions()
print('📂 Open Positions')
print('━' * 70)

if not positions:
    print('  (none)')
else:
    total_pnl = 0
    for p in positions:
        pos_id, symbol, side, entry, qty, stop, target = p[0], p[1], p[2], p[3], p[4], p[5], p[6]
        try:
            current = get_price(symbol)
            if side == 'long':
                pnl = (current - entry) * qty
            else:
                pnl = (entry - current) * qty
            pnl_pct = pnl / (entry * qty) * 100
            total_pnl += pnl
            emoji = '🟢' if pnl > 0 else '🔴'
            print(f'  {emoji} {symbol:14s} {side:5s} entry:\${entry:.4f} now:\${current:.4f} PnL:\${pnl:+.2f} ({pnl_pct:+.1f}%)')
            print(f'     stop:\${stop:.4f} target:\${target or 0:.4f}')
        except:
            print(f'  ⚠️ {symbol} {side} entry:\${entry:.4f} (price fetch failed)')

    print(f'  ────────────────────────')
    print(f'  Unrealized: \${total_pnl:+.2f}')

print()
stats = get_stats()
if stats and stats[0]:
    total, wins, losses, pnl, avg = stats
    wr = wins/total*100 if total > 0 else 0
    print(f'📊 Stats: {total} trades | {wins}W/{losses}L ({wr:.0f}%) | PnL: \${pnl} | Avg: \${avg}')
else:
    print('📊 Stats: No closed trades yet')
"
