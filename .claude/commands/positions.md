查看所有持仓状态。用法: /positions

## 执行步骤

### 1. 获取持仓 + 挂单 + 账户概览

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from lib.binance import get_position_risk, get_open_orders, get_usdt_balance, get_today_realized_pnl, get_account, get_klines, calc_atr

# 账户概览
balance = get_usdt_balance()
pnl = get_today_realized_pnl()
account = get_account()
margin_ratio = float(account.get('totalMaintMargin', 0)) / max(float(account.get('totalMarginBalance', 1)), 0.01) * 100

print(f'💰 余额: \${balance:,.2f} | 当日 PnL: \${pnl:+.2f} | 保证金率: {margin_ratio:.1f}%')
print('━' * 50)

# 持仓详情
positions = get_position_risk()
active = [p for p in positions if float(p.get('positionAmt', 0)) != 0]

if not active:
    print('📂 无持仓')
else:
    total_upnl = 0
    for p in active:
        symbol = p['symbol']
        amt = float(p['positionAmt'])
        side = 'LONG' if amt > 0 else 'SHORT'
        entry = float(p['entryPrice'])
        mark = float(p['markPrice'])
        upnl = float(p['unRealizedProfit'])
        liq = float(p.get('liquidationPrice', 0))
        leverage = p.get('leverage', '?')
        total_upnl += upnl
        
        # 真实 ATR(14)
        try:
            klines = get_klines(symbol, '1h', 100)
            atr = calc_atr(klines)
        except:
            atr = entry * 0.03
        
        profit_distance = (mark - entry) if amt > 0 else (entry - mark)
        atr_multiple = profit_distance / atr if atr > 0 else 0
        pnl_pct = (profit_distance / entry) * 100
        
        emoji = '🟢' if upnl >= 0 else '🔴'
        print(f'{emoji} {symbol} {side} {leverage}x')
        print(f'  入场: \${entry:.4f} | 现价: \${mark:.4f} | PnL: \${upnl:+.2f} ({pnl_pct:+.1f}%)')
        print(f'  数量: {abs(amt)} | ATR倍数: {atr_multiple:.1f}x | 强平: \${liq:.2f}')
        
        # 挂单检查
        orders = get_open_orders(symbol)
        has_stop = False
        has_tp = False
        for o in orders:
            otype = o['type']
            if otype in ('STOP_MARKET', 'TRAILING_STOP_MARKET'):
                has_stop = True
                stop_price = float(o.get('stopPrice', 0))
                print(f'  └ 止损: {otype} @\${stop_price:,.4f} ✅')
            elif otype == 'TAKE_PROFIT_MARKET':
                has_tp = True
                tp_price = float(o.get('stopPrice', 0))
                print(f'  └ 止盈: @\${tp_price:,.4f} ✅')
        
        if not has_stop:
            print(f'  └ ❌ 无止损单! 需要立即补单')
        if not has_tp:
            print(f'  └ ⚠️ 无止盈单')
        print()
    
    print(f'📊 持仓: {len(active)}/5 | 总浮盈: \${total_upnl:+.2f}')
"
```

### 规则
- 数据以 Binance 交易所为准
- 无止损单的仓位需要立即处理
- 如需管理持仓（移动止损等），使用 `/trade-loop`
