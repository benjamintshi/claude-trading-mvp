实时扫描市场，发现交易机会。

## 执行步骤

### 1. 获取实时数据

```bash
# BTC + 主要 altcoin 价格和 24h 变动
python3 -c "
import json, urllib.request
symbols = ['BTCUSDT','ETHUSDT','SOLUSDT','AVAXUSDT','SUIUSDT','ARBUSDT','RENDERUSDT','NEARUSDT','DOTUSDT','OPUSDT','LINKUSDT','ICPUSDT','HBARUSDT','FETUSDT','APTUSDT']
for sym in symbols:
    try:
        url = f'https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={sym}'
        d = json.loads(urllib.request.urlopen(url, timeout=5).read())
        price = float(d['lastPrice'])
        change = float(d['priceChangePercent'])
        vol_change = float(d['volume']) / float(d['quoteVolume']) if float(d['quoteVolume']) > 0 else 0
        print(f'{sym:14s} \${price:>10.4f}  24h:{change:+.1f}%')
    except: pass
"

# Funding rates (top 10)
python3 -c "
import json, urllib.request
for sym in ['BTCUSDT','ETHUSDT','SOLUSDT','AVAXUSDT','SUIUSDT','ARBUSDT']:
    try:
        d = json.loads(urllib.request.urlopen(f'https://fapi.binance.com/fapi/v1/fundingRate?symbol={sym}&limit=1', timeout=5).read())[0]
        print(f'{sym}: {float(d[\"fundingRate\"])*100:+.4f}%')
    except: pass
"

# Fear & Greed
curl -s "https://api.alternative.me/fng/?limit=1" | python3 -c "import sys,json; d=json.load(sys.stdin)['data'][0]; print(f'Fear & Greed: {d[\"value\"]} ({d[\"value_classification\"]})')"
```

### 2. 搜索最新新闻

用 WebSearch 搜索:
- "bitcoin crypto market today"
- "crypto altcoin news today"
- 如果有特定地缘事件，搜索相关影响

### 3. 分析并输出

**输出格式：**

```
📊 市场扫描 — {时间}

市场环境：
  BTC: ${价格} ({变动}%) | F&G: {值} | Funding: {值}
  关键新闻: {一句话概括}

🎯 发现的机会（按确信度排序）：

1. {币种} {做多/做空} — 确信度 {高/中/低}
   入场: ${价格}
   止损: ${价格} ({距离}%)
   目标: ${价格} ({距离}%)
   赔率: {X}:1
   理由: {为什么这个机会存在，谁在对面亏钱}

2. ...

❌ 不碰的：
  {币种}: {原因}

💡 整体判断：{一句话}
```

**规则：**
- 不是所有时候都有机会，没机会就说没有
- 每个机会必须有明确的止损和目标
- 赔率 < 1.5:1 不推荐
- 必须解释"谁在对面亏钱"
