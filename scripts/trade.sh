#!/bin/bash
# Claude Trader — 自动交易循环 (每 30 分钟)
# 架构: 代码做风控 → AI 做判断 → 代码执行

export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/v24.14.1/bin:/usr/local/bin:$PATH"

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

TIMESTAMP=$(date -u '+%Y-%m-%d %H:%M UTC')
LOG_DIR="$PROJECT_DIR/data/logs"
mkdir -p "$LOG_DIR"

echo "[$TIMESTAMP] Trade cycle starting..." >> "$LOG_DIR/trade.log"

# 加载环境变量
set -a; source "$PROJECT_DIR/.env" 2>/dev/null; set +a

# 先跑止损管理 (纯代码, 不需要 AI)
python3 "$PROJECT_DIR/scripts/position_manager.py" >> "$LOG_DIR/position_mgr.log" 2>&1

# AI 交易循环 (需要 ANTHROPIC_API_KEY，没有则跳过)
if ! command -v claude &>/dev/null || [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "[$TIMESTAMP] 跳过 AI 扫描 (无 API key，止损管理已执行)" >> "$LOG_DIR/trade.log"
    exit 0
fi

claude -p --dangerously-skip-permissions --max-budget-usd 0.50 "
执行交易循环。你是 MC，交易员。

1. 跑系统状态检查:
python3 -c \"
import sys,os;sys.path.insert(0,'$PROJECT_DIR')
for l in open('$PROJECT_DIR/.env'):
 l=l.strip()
 if l and not l.startswith('#') and '=' in l:
  k,v=l.split('=',1);os.environ.setdefault(k.strip(),v.strip())
from lib.risk_gateway import get_system_status,check_circuit_breaker
print(get_system_status())
b=check_circuit_breaker()
if not b['can_trade']:print('BREAKER_TRIPPED')
\"

如果输出 BREAKER_TRIPPED，输出报告后结束，不扫描。

2. 扫描市场 (top 30 按成交量):
python3 -c \"
import sys,os;sys.path.insert(0,'$PROJECT_DIR')
for l in open('$PROJECT_DIR/.env'):
 l=l.strip()
 if l and not l.startswith('#') and '=' in l:
  k,v=l.split('=',1);os.environ.setdefault(k.strip(),v.strip())
from lib.binance import get_tradable_symbols,get_signal_snapshot
btc=get_signal_snapshot('BTCUSDT');bc=btc['change_pct']
print(f'BTC \${btc[\"price\"]:,.2f} ({bc:+.1f}%) RSI:{btc[\"rsi\"]:.0f} Fund:{btc[\"funding_rate\"]*100:+.4f}% {btc[\"ema_trend\"]} L/S:{btc[\"long_short_ratio\"]:.2f}')
for c in get_tradable_symbols(top_n=30):
 sym=c['symbol']
 if sym=='BTCUSDT':continue
 try:
  s=get_signal_snapshot(sym);vs=s['change_pct']-bc;f=s['funding_rate']*100
  flags=''
  if s['rsi']<30 or s['rsi']>70:flags+='⚡'
  if abs(vs)>3:flags+='📊'
  if s['long_short_ratio']>2 or s['long_short_ratio']<0.5:flags+='👥'
  if flags:print(f'{sym:14s} \${s[\"price\"]:>10.4f} {s[\"change_pct\"]:+.1f}% vs:{vs:+.1f}% RSI:{s[\"rsi\"]:.0f} Fund:{f:+.4f}% L/S:{s[\"long_short_ratio\"]:.2f} {s[\"ema_trend\"]} {flags}')
 except:pass
\"

3. 获取 Fear & Greed:
curl -s 'https://api.alternative.me/fng/?limit=1'

4. 用你的判断力决定有没有机会。不要打分。
   如果有机会: 做牛熊辩论 (牛>熊+3)，推理审计通过后，跑风控检查再开仓。
   如果没有: 说没有，结束。

开仓时用这个:
python3 -c \"
import sys,os;sys.path.insert(0,'$PROJECT_DIR')
for l in open('$PROJECT_DIR/.env'):
 l=l.strip()
 if l and not l.startswith('#') and '=' in l:
  k,v=l.split('=',1);os.environ.setdefault(k.strip(),v.strip())
from lib.risk_gateway import pre_trade_check,calc_position_size
from lib.binance import open_position_with_sl_tp,get_price
sym='SYMBOL';side='SIDE';conv='CONVICTION'
entry=get_price(sym);stop=STOP;target=TARGET
r=pre_trade_check(sym,side,entry,stop,target)
if not r['pass']:print(r['reason']);sys.exit(1)
s=calc_position_size(entry,stop,r['regime'],r['correlation']['penalty'],r['details']['circuit_breaker']['size_multiplier'],conv)
q=round(s['quantity'],4)
open_position_with_sl_tp(sym,side,q,stop,target,3)
print(f'OK {sym} {side.upper()} qty={q} risk=\${s[\"risk_usd\"]:.2f}')
\"

规则: 风控硬门槛不可绕过 | conviction决定仓位 | 没机会不做
" >> "$LOG_DIR/trade_output.log" 2>&1

echo "[$TIMESTAMP] Trade cycle complete" >> "$LOG_DIR/trade.log"
