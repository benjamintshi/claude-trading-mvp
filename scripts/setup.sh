#!/bin/bash
# Claude Trader — Setup script
# Run once to initialize DB and cron.

set -e
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "=== Claude Trader Setup ==="

# 1. Check dependencies
echo "Checking dependencies..."
which python3 > /dev/null || { echo "❌ python3 not found"; exit 1; }
which psql > /dev/null || { echo "❌ psql not found"; exit 1; }
which claude > /dev/null || { echo "❌ claude not found"; exit 1; }
which curl > /dev/null || { echo "❌ curl not found"; exit 1; }
echo "✅ All dependencies found"

# 2. Check .env
if [ ! -f .env ]; then
    echo "❌ .env not found. Copy .env.example and fill in your keys."
    exit 1
fi
echo "✅ .env found"

# 3. Load env
set -a; source .env; set +a

# 4. Create DB
echo "Creating database..."
createdb claude_trader 2>/dev/null || echo "  (database already exists)"
python3 -c "import sys; sys.path.insert(0, '.'); from lib.db import init_db; init_db()"
echo "✅ Database initialized"

# 5. Create directories
mkdir -p data/logs data/trades
echo "✅ Directories created"

# 6. Make scripts executable
chmod +x scripts/*.sh

# 7. Setup cron
echo "Setting up cron..."
CRON_CMD="*/15 * * * * cd $PROJECT_DIR && ./scripts/trade.sh"
(crontab -l 2>/dev/null | grep -v "claude-trading-mvp"; echo "$CRON_CMD") | crontab -
echo "✅ Cron: every 15 minutes"

# 8. Test
echo ""
echo "=== Testing ==="
python3 -c "
import sys; sys.path.insert(0, '.')
from lib.binance import get_price, get_funding_rate
print(f'BTC: \${get_price(\"BTCUSDT\"):,.2f}')
print(f'Funding: {get_funding_rate(\"BTCUSDT\")*100:+.4f}%')
"
echo "✅ Binance API working"

echo ""
echo "=== Setup Complete ==="
echo "Commands:"
echo "  /scan          — 扫描市场"
echo "  /open          — 开仓"
echo "  /close         — 平仓"
echo "  /positions     — 查看持仓"
echo "  /trade-loop    — 完整交易循环"
echo ""
echo "Auto trading runs every 15 minutes via cron."
echo "Telegram notifications will be sent for all trades."
