开仓交易。用法: /open AVAXUSDT long 8.60 8.40 9.00 "急跌反弹" high

参数: /open {symbol} {long|short} {entry} {stop} {target} {reason} {conviction}

conviction: high / standard / probe — 你的信心水平，决定仓位大小

## 执行步骤

### 1. 代码风控自动检查 (硬门槛，不可跳过)

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from lib.risk_gateway import pre_trade_check, format_check_result

result = pre_trade_check('{symbol}', '{direction}', float('{entry}'), float('{stop}'), float('{target}'))
print(format_check_result(result))

if not result['pass']:
    print()
    print('🚫 风控拦截，不能开仓。')
else:
    print()
    print('✅ 风控通过，进入 AI 判断环节。')
"
```

**如果风控拦截 → 停止，不开仓，告诉用户原因。**

### 2. 牛熊辩论 (AI 判断 — 你来做)

你必须真诚地做这个辩论，不是走形式：

**🐂 牛方 (为什么应该做这笔交易):**
- 列出 3 个最强论据
- 用数据支撑，不是"感觉"
- 打分 0-10

**🐻 熊方 (为什么不应该做这笔交易):**
- 列出 3 个最强反对理由
- 站在对手方角度思考
- 打分 0-10

**判定:** 牛方 > 熊方 + 3 → 继续。否则 → 不开仓。

### 3. 推理审计 (AI 判断 — 你来做)

三角一致性检查:
- ✅ 证据→推理: 你的论据真的支撑你的结论吗？
- ✅ 推理→决策: 你的结论足够强到值得用真金白银下注吗？
- ✅ 数据驱动: 你是基于今天的数据做判断，还是在套历史模式？

三项都通过 → 继续。任一项 ❌ → 不开仓。

### 4. 执行开仓

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from lib.risk_gateway import pre_trade_check, calc_position_size, detect_regime
from lib.binance import open_position_with_sl_tp, get_price
from lib.db import open_position
from lib.notify import notify_open

symbol = '{symbol}'
side = '{direction}'
entry = get_price(symbol)
stop = float('{stop}')
target = float('{target}')
reason = '{reason}'
conviction = '{conviction}'

# 再次检查 + 计算仓位
result = pre_trade_check(symbol, side, entry, stop, target)
if not result['pass']:
    print(result['reason'])
    sys.exit(1)

regime = result['regime']
corr = result['correlation']
ps = result['details']['circuit_breaker']

size = calc_position_size(
    entry, stop, regime,
    correlation_penalty=corr['penalty'],
    breaker_multiplier=ps['size_multiplier'],
    conviction=conviction,
)
qty = size['quantity']

print(f'开仓: {symbol} {side.upper()}')
print(f'  入场: \${entry:.4f} | 止损: \${stop} | 目标: \${target}')
print(f'  仓位: {qty:.4f} (名义 \${size[\"notional\"]:.2f})')
print(f'  风险: \${size[\"risk_usd\"]:.2f} ({size[\"risk_pct\"]:.2f}%)')
print(f'  信心: {conviction} | 市场: {regime[\"regime_cn\"]}')

# 一键三单
result = open_position_with_sl_tp(symbol, side, qty, stop, target, leverage=3)
print(f'Binance: {result}')

# 记录
try:
    open_position(symbol, side, entry, stop, target, qty, reason, 0)
    notify_open(symbol, side, entry, stop, target, reason, qty, 0)
except Exception:
    pass

print(f'✅ 开仓完成 — 止损止盈由 Binance 7x24 自动执行')
"
```

### 5. 记录交易备忘录

开仓成功后，调用 trade_memo 记录完整分析思路:

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from lib.trade_memo import record_open
path = record_open(
    symbol='{symbol}', side='{direction}',
    entry=ENTRY, stop=float('{stop}'), target=float('{target}'),
    conviction='{conviction}', regime='REGIME',
    bull_case='''你的牛方论据''',
    bear_case='''你的熊方论据''',
    bull_score=BULL_SCORE, bear_score=BEAR_SCORE,
    reasoning_audit='''推理审计结果''',
    reason='{reason}',
    market_snapshot='''关键市场数据''',
    risk_usd=RISK_USD, risk_pct=RISK_PCT, quantity=QTY,
)
print(f'备忘录: {path}')
"
```

### 规则
- 第 1 步 (代码风控) 不通过 → 绝对不开仓，无例外
- 第 2 步 (牛熊辩论) 牛方没有压倒性优势 → 不开仓
- 第 3 步 (推理审计) 任何一项不通过 → 不开仓
- 必须说清楚"谁在对面亏钱"
- conviction 决定仓位: high=1.5% / standard=1.0% / probe=0.5%
