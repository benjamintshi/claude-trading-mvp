开仓交易。用法: /open AVAXUSDT long 8.60 8.40 9.00 "急跌反弹机会"

参数: /open {symbol} {long|short} {entry} {stop} {target} {reason}

## 执行步骤

### 1. 验证参数

解析用户输入的参数：symbol, direction, entry_price, stop_loss, target, reason。
如果参数不全，用 scan 结果或当前市场价格填充。

### 2. 风控检查

```bash
# 当前 BTC 价格
curl -s "https://fapi.binance.com/fapi/v1/ticker/price?symbol=BTCUSDT" | python3 -c "import sys,json; print(f'BTC: \${float(json.load(sys.stdin)[\"price\"]):,.0f}')"

# 当前持仓数
psql trend_lab -c "SELECT count(*) as open_positions FROM position_record WHERE status='open'"

# 账户状态
psql trend_lab -c "SELECT round(sum(pnl::numeric), 0) as total_pnl FROM position_record WHERE status='closed'"
```

风控规则:
- 最大同时持仓: 5 笔
- 单笔最大亏损: $60 (3% of $2000)
- 止损距离必须 > 0.5% 且 < 5%
- 赔率 (target距离/stop距离) 必须 > 1.5

### 3. 计算仓位

```
本金: $2,000
风险: 1% = $20/笔
止损距离: |entry - stop| / entry
仓位名义值: $20 / 止损距离
杠杆: 3x
保证金: 仓位名义值 / 3
```

### 4. 写入 DB（Paper 模式）

```bash
psql trend_lab -c "
-- 确保 alpha_run 存在
INSERT INTO alpha_run (alpha_name, started_at)
SELECT 'mc_manual', now()
WHERE NOT EXISTS (SELECT 1 FROM alpha_run WHERE alpha_name = 'mc_manual')
ON CONFLICT DO NOTHING;

-- 开仓
INSERT INTO position_record (alpha_run_id, symbol_id, side, entry_price, quantity, stop_loss, status, entry_time)
SELECT
  ar.id,
  s.id,
  '{direction}',
  {entry_price},
  {quantity},
  {stop_loss},
  'open',
  now()
FROM alpha_run ar, symbol s
WHERE ar.alpha_name = 'mc_manual' AND s.symbol = '{symbol}'
RETURNING id;
"
```

### 5. 发送 Telegram 通知

```bash
# 通知开仓
source .env
MSG="🟢 *MC 开仓*
━━━━━━━━━━━━━━━━
📊 {symbol} {direction}
💰 入场: \${entry}
🛑 止损: \${stop} ({stop_pct}%)
🎯 目标: \${target} ({target_pct}%)
📐 赔率: {ratio}:1
💡 理由: {reason}"

curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d chat_id="${TELEGRAM_CHAT_ID}" \
  -d text="$MSG" \
  -d parse_mode="Markdown"
```

### 6. 输出确认

```
✅ 开仓成功
  {symbol} {long/short} @ ${entry}
  止损: ${stop} | 目标: ${target}
  仓位: ${notional} 名义值 (${margin} 保证金)
  赔率: {X}:1
  理由: {reason}
  DB ID: {id}
```
