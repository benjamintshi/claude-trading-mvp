全自动交易循环。每小时扫描市场、发现机会、自动开仓、管理持仓。

用法: /trade-loop（然后用 /loop 1h /trade-loop 持续运行）

## 每次执行的完整流程

### 1. 检查现有持仓 — 是否需要平仓？

```bash
psql trend_lab -c "
SELECT pr.id, ar.alpha_name, s.symbol, pr.side,
  round(pr.entry_price::numeric, 4) as entry,
  round(pr.stop_loss::numeric, 4) as stop,
  round(EXTRACT(EPOCH FROM (now() - pr.entry_time)) / 3600, 1) as hours
FROM position_record pr
JOIN alpha_run ar ON ar.id = pr.alpha_run_id
JOIN symbol s ON s.id = pr.symbol_id
WHERE pr.status = 'open'
ORDER BY pr.entry_time"
```

对每个持仓：
- 获取当前价格
- 检查是否触及止损 → 平仓
- 检查是否到达目标 → 平仓
- 检查是否持仓超过 48h → 评估是否平仓
- 检查市场条件是否改变（新闻突变、趋势反转）→ 评估是否提前平仓

### 2. 扫描市场 — 有没有新机会？

执行 /scan 的完整流程：
- 获取所有币种实时价格 + 24h 变动
- 获取 funding rate
- 获取 Fear & Greed
- 搜索最新新闻
- 分析市场形态

### 3. 判断机会 — 基于信号叠加

对每个潜在机会打分（满分 10 分）：

**做多信号：**
- 价格在关键支撑位附近 (+2)
- 24h 跌幅异常大于大盘（独立急跌 → 反弹）(+2)
- Funding rate 偏负（空头拥挤）(+1)
- Fear & Greed < 20（极度恐惧逆向）(+1)
- RSI < 30（超卖）(+1)
- 新闻面有利好催化剂 (+1)
- 成交量放大确认 (+1)
- 高时间框架趋势支持 (+1)

**做空信号：**
- 价格在关键阻力位附近 (+2)
- 24h 涨幅异常大于大盘（独立急涨 → 回调）(+2)
- Funding rate 偏正（多头拥挤）(+1)
- Fear & Greed > 80（极度贪婪逆向）(+1)
- RSI > 70（超买）(+1)
- 新闻面有利空催化剂 (+1)
- 成交量放大确认 (+1)
- 高时间框架趋势支持 (+1)

**规则：**
- 得分 ≥ 6 → 开仓（高确信）
- 得分 4-5 → 观察，不开仓
- 得分 < 4 → 忽略
- 同时不超过 5 个持仓
- 同方向不超过 3 个（最多 3 多 + 2 空）

### 4. 执行开仓

如果发现 ≥ 6 分的机会：
- 计算入场、止损、目标
- 风控检查（仓位数、暴露限制）
- 写入 DB
- 发送 Telegram 通知

### 5. 输出报告

```
⏰ 交易循环 — {时间}
━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 市场: BTC ${price} ({change}%) | F&G: {value}
📰 关键新闻: {headline}

📂 持仓管理:
  {symbol} {side}: ${entry} → ${current} ({pnl}%) — {保持/平仓/调整止损}

🎯 新机会:
  {symbol} {方向} — 得分 {X}/10 — {动作：开仓/观察}

💰 账户: 持仓 {N} 笔 | 已实现 ${pnl} | 胜率 {wr}%
```

### 6. 管理止损

对已持仓，动态调整止损：
- 盈利 > 1 ATR → 止损移到保本
- 盈利 > 2 ATR → 止损锁定 1 ATR 利润
- 持仓 > 24h 无进展 → 收紧止损
