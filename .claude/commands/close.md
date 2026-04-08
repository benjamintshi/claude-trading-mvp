平仓交易。用法: /close AVAXUSDT "反弹到目标位"

参数: /close {symbol} {reason}
无参数时显示所有持仓供选择。

## 执行步骤

### 1. 查看当前持仓

```bash
psql trend_lab -c "
SELECT pr.id, ar.alpha_name, s.symbol, pr.side,
  round(pr.entry_price::numeric, 4) as entry,
  round(pr.stop_loss::numeric, 4) as stop,
  pr.entry_time
FROM position_record pr
JOIN alpha_run ar ON ar.id = pr.alpha_run_id
JOIN symbol s ON s.id = pr.symbol_id
WHERE pr.status = 'open'
ORDER BY pr.entry_time"
```

### 2. 获取当前价格

```bash
curl -s "https://fapi.binance.com/fapi/v1/ticker/price?symbol={SYMBOL}" | python3 -c "import sys,json; print(json.load(sys.stdin)['price'])"
```

### 3. 计算 PnL

```
对于做多: PnL = (current_price - entry_price) * quantity
对于做空: PnL = (entry_price - current_price) * quantity
扣除手续费: PnL - (entry_notional + exit_notional) * 0.00075
```

### 4. 更新 DB

```bash
psql trend_lab -c "
UPDATE position_record SET
  status = 'closed',
  exit_price = {current_price},
  pnl = {calculated_pnl},
  exit_time = now()
WHERE id = {position_id}
RETURNING id, round(pnl::numeric, 2) as pnl"
```

### 5. 发送 Telegram 通知

```bash
source .env
MSG="🔴 *MC 平仓*
━━━━━━━━━━━━━━━━
📊 {symbol} {side}
💰 入场: \${entry} → 出场: \${exit}
📈 盈亏: \${pnl} ({pnl_pct}%)
⏱ 持仓: {duration}
💡 理由: {reason}"

curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d chat_id="${TELEGRAM_CHAT_ID}" \
  -d text="$MSG" \
  -d parse_mode="Markdown"
```

### 6. 输出确认

```
✅ 平仓成功
  {symbol} {side}: ${entry} → ${exit}
  盈亏: ${pnl} ({pnl_pct}%)
  持仓时间: {duration}
  理由: {reason}
```
