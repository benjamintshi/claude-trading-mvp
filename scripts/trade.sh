#!/bin/bash
# Claude Trader — Autonomous trading cycle
# Runs via cron every 15 minutes.

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

TIMESTAMP=$(date -u '+%Y-%m-%d %H:%M UTC')
echo "[$TIMESTAMP] Trade cycle starting..." >> data/logs/trade.log

# Load env
set -a; source "$PROJECT_DIR/.env" 2>/dev/null; set +a

claude -p --dangerously-skip-permissions --max-budget-usd 0.50 "
你是 MC，加密交易员。执行一次交易循环。

## 1. 检查持仓
\`\`\`bash
cd $PROJECT_DIR && python3 -c \"
import sys; sys.path.insert(0, '.')
from lib.db import get_open_positions, get_stats
positions = get_open_positions()
if positions:
    for p in positions:
        print(f'ID:{p[0]} {p[1]} {p[2]} entry:{p[3]} stop:{p[5]} target:{p[6]} hours:{round(((__import__(\"datetime\").datetime.now(__import__(\"datetime\").timezone.utc) - p[8]).total_seconds()/3600) if p[8] else 0, 1)}h')
else:
    print('无持仓')
stats = get_stats()
if stats and stats[0]:
    print(f'统计: {stats[0]}笔 {stats[1]}胜/{stats[2]}负 PnL:\${stats[3]}')
\"
\`\`\`

对每个持仓获取当前价格判断是否需要平仓：
\`\`\`bash
python3 -c \"
import json, urllib.request
for sym in ['BTCUSDT','AVAXUSDT']:  # 替换为实际持仓币种
    d = json.loads(urllib.request.urlopen(f'https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}', timeout=5).read())
    print(f'{sym}: \${float(d[\"price\"]):,.4f}')
\"
\`\`\`

如果触止损或到目标，用 lib/db.py 平仓：
\`\`\`bash
python3 -c \"
import sys; sys.path.insert(0, '.')
from lib.db import close_position
from lib.notify import notify_close
# close_position(pos_id, exit_price, 'reason')
\"
\`\`\`

## 2. 扫描市场
\`\`\`bash
python3 -c \"
import json, urllib.request
symbols = ['BTCUSDT','ETHUSDT','SOLUSDT','AVAXUSDT','SUIUSDT','ARBUSDT','RENDERUSDT','NEARUSDT','DOTUSDT','OPUSDT','LINKUSDT','ICPUSDT','HBARUSDT','FETUSDT','APTUSDT']
for sym in symbols:
    try:
        d = json.loads(urllib.request.urlopen(f'https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={sym}', timeout=5).read())
        print(f'{sym:14s} \${float(d[\"lastPrice\"]):>10.4f}  24h:{float(d[\"priceChangePercent\"]):+.1f}%')
    except: pass
\"
\`\`\`

获取 funding 和 Fear&Greed：
\`\`\`bash
python3 -c \"
import json, urllib.request
for sym in ['BTCUSDT','ETHUSDT','SOLUSDT']:
    d = json.loads(urllib.request.urlopen(f'https://fapi.binance.com/fapi/v1/fundingRate?symbol={sym}&limit=1', timeout=5).read())[0]
    print(f'{sym}: {float(d[\"fundingRate\"])*100:+.4f}%')
\"
curl -s 'https://api.alternative.me/fng/?limit=1' | python3 -c \"import sys,json; d=json.load(sys.stdin)['data'][0]; print(f'F&G: {d[\"value\"]} ({d[\"value_classification\"]})')\"
\`\`\`

## 3. 搜索新闻（用 WebSearch）
搜索 'bitcoin crypto market today' 获取最新动态。

## 4. 评分判断
对每个潜在机会用 10 分制评估。≥ 6 分开仓。

## 5. 执行
如需开仓：
\`\`\`bash
python3 -c \"
import sys; sys.path.insert(0, '.')
from lib.db import open_position
from lib.binance import calc_quantity, get_price
from lib.notify import notify_open

symbol = 'XXXUSDT'
side = 'long'
entry = get_price(symbol)
stop = entry * 0.97  # 示例
target = entry * 1.03
qty = calc_quantity(symbol, 2000, 0.01, entry, stop, 3)

pos_id = open_position(symbol, side, entry, stop, target, qty, '理由', score=7)
notify_open(symbol, side, entry, stop, target, '理由', qty, 7)
print(f'开仓成功 ID:{pos_id}')
\"
\`\`\`

如需平仓：
\`\`\`bash
python3 -c \"
import sys; sys.path.insert(0, '.')
from lib.db import close_position
from lib.notify import notify_close
result = close_position(POS_ID, EXIT_PRICE, '理由')
if result:
    notify_close('SYMBOL', 'SIDE', ENTRY, EXIT_PRICE, result['pnl'], result['pnl_pct'], result['duration_hours'], '理由')
\"
\`\`\`

## 6. 写报告
\`\`\`bash
cat > $PROJECT_DIR/data/trades/$(date -u '+%Y%m%d-%H%M').md << 'REPORT'
# 交易报告内容
REPORT
\`\`\`

## 规则
- 没有好机会不开仓
- 每笔必须有止损和目标
- 赔率 > 1.5:1
- 最多 5 笔持仓
" >> data/logs/trade_output.log 2>&1

echo "[$TIMESTAMP] Trade cycle complete" >> data/logs/trade.log
