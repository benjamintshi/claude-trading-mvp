#!/usr/bin/env python3
"""交易调度器 — 前台常驻，每 30 分钟自动扫描 + 止损管理.

在新终端窗口运行:
  python3 scripts/scheduler.py

继承当前终端的 Claude 登录态，不需要 API key。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent

# 加载 .env
ENV_FILE = PROJECT_DIR / ".env"
if ENV_FILE.exists():
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "1800"))  # 默认 30 分钟
POSITION_MGR_INTERVAL = 300  # 止损管理每 5 分钟
AI_BUDGET = os.getenv("SCAN_BUDGET", "0.50")

LOG_DIR = PROJECT_DIR / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_DIR / "scheduler.log", "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def run_position_manager():
    """止损管理 (纯代码)."""
    try:
        result = subprocess.run(
            [sys.executable, str(PROJECT_DIR / "scripts" / "position_manager.py")],
            capture_output=True, text=True, timeout=30,
            cwd=str(PROJECT_DIR),
        )
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                log(f"  止损: {line.strip()}")
    except Exception as e:
        log(f"  止损管理异常: {e}")


def run_ai_scan():
    """AI 市场扫描 + 交易 (用 claude -p)."""
    prompt = """执行交易循环。你是 MC，交易员。简洁输出。

1. 系统状态:
```bash
python3 -c "
import sys,os;sys.path.insert(0,'.')
for l in open('.env'):
 l=l.strip()
 if l and not l.startswith('#') and '=' in l:
  k,v=l.split('=',1);os.environ.setdefault(k.strip(),v.strip())
from lib.risk_gateway import get_system_status,check_circuit_breaker
print(get_system_status())
b=check_circuit_breaker()
if not b['can_trade']:print('BREAKER_TRIPPED')
"
```

如果 BREAKER_TRIPPED 则结束。

2. 持仓:
```bash
python3 -c "
import sys,os;sys.path.insert(0,'.')
for l in open('.env'):
 l=l.strip()
 if l and not l.startswith('#') and '=' in l:
  k,v=l.split('=',1);os.environ.setdefault(k.strip(),v.strip())
from lib.binance import get_position_risk,get_open_orders
for p in get_position_risk():
 amt=float(p.get('positionAmt',0))
 if amt==0:continue
 side='L' if amt>0 else 'S'
 o=get_open_orders(p['symbol'])
 sl='✅' if any(x['type'] in ('STOP_MARKET','TRAILING_STOP_MARKET') for x in o) else '❌'
 print(f'{p[\"symbol\"]} {side} e:{float(p[\"entryPrice\"]):.4f} m:{float(p[\"markPrice\"]):.4f} pnl:{float(p[\"unRealizedProfit\"]):+.2f} SL:{sl}')
"
```

3. 扫描 (只输出有异常的币):
```bash
python3 -c "
import sys,os;sys.path.insert(0,'.')
for l in open('.env'):
 l=l.strip()
 if l and not l.startswith('#') and '=' in l:
  k,v=l.split('=',1);os.environ.setdefault(k.strip(),v.strip())
from lib.binance import get_tradable_symbols,get_signal_snapshot
btc=get_signal_snapshot('BTCUSDT');bc=btc['change_pct']
print(f'BTC ${btc[\"price\"]:,.0f} ({bc:+.1f}%) RSI:{btc[\"rsi\"]:.0f} {btc[\"ema_trend\"]}')
for c in get_tradable_symbols(top_n=30):
 sym=c['symbol']
 if sym=='BTCUSDT':continue
 try:
  s=get_signal_snapshot(sym);vs=s['change_pct']-bc;f=s['funding_rate']*100
  flags=''
  if s['rsi']<30 or s['rsi']>70:flags+='⚡'
  if abs(vs)>3:flags+='📊'
  if s['long_short_ratio']>2 or s['long_short_ratio']<0.5:flags+='👥'
  if flags:print(f'{sym:12s} ${s[\"price\"]:>10.4f} {s[\"change_pct\"]:+.1f}% vs:{vs:+.1f}% RSI:{s[\"rsi\"]:.0f} F:{f:+.4f}% L/S:{s[\"long_short_ratio\"]:.2f} {s[\"ema_trend\"]} {flags}')
 except:pass
"
```

```bash
curl -s 'https://api.alternative.me/fng/?limit=1' | python3 -c "import sys,json;d=json.load(sys.stdin)['data'][0];print(f'F&G:{d[\"value\"]} {d[\"value_classification\"]}')"
```

4. 用判断力决定有没有机会。没有就说没有。
   有机会: 牛熊辩论(牛>熊+3) → 推理审计 → 风控检查 → 开仓。

开仓:
```bash
python3 -c "
import sys,os;sys.path.insert(0,'.')
for l in open('.env'):
 l=l.strip()
 if l and not l.startswith('#') and '=' in l:
  k,v=l.split('=',1);os.environ.setdefault(k.strip(),v.strip())
from lib.risk_gateway import pre_trade_check,calc_position_size
from lib.binance import open_position_with_sl_tp,get_price
sym='SYM';side='SIDE';conv='CONV'
entry=get_price(sym);stop=STOP;target=TARGET
r=pre_trade_check(sym,side,entry,stop,target)
if not r['pass']:print(r['reason']);sys.exit(1)
s=calc_position_size(entry,stop,r['regime'],r['correlation']['penalty'],r['details']['circuit_breaker']['size_multiplier'],conv)
q=round(s['quantity'],4)
open_position_with_sl_tp(sym,side,q,stop,target,3)
print(f'OK {sym} {side.upper()} qty={q} risk=${s[\"risk_usd\"]:.2f}')
"
```

规则: 风控硬门槛不可绕过 | 赔率>=3:1 | conviction决定仓位 | 没机会不做 | 简洁输出"""

    log("🔍 启动 AI 扫描...")
    try:
        result = subprocess.run(
            ["claude", "-p", "--dangerously-skip-permissions",
             "--max-budget-usd", AI_BUDGET],
            input=prompt,
            capture_output=True, text=True,
            timeout=300,  # 5 分钟超时
            cwd=str(PROJECT_DIR),
            env=os.environ.copy(),
        )
        output = result.stdout.strip()
        if output:
            # 取最后 500 字
            summary = output[-500:]
            log(f"📊 扫描结果: {summary[:300]}...")
            # 推送 Telegram
            try:
                from lib.notify import notify_scan_result
                notify_scan_result(summary[:500])
            except Exception:
                pass
        if result.returncode != 0:
            err = result.stderr.strip() or result.stdout.strip()
            log(f"⚠️ 扫描异常 (rc={result.returncode}): {err[:200]}")
    except subprocess.TimeoutExpired:
        log("⚠️ AI 扫描超时 (300s)")
    except FileNotFoundError:
        log("❌ claude 命令未找到")
    except Exception as e:
        log(f"❌ 扫描异常: {e}")


def main():
    log("=" * 50)
    log(f"交易调度器启动")
    log(f"  扫描间隔: {SCAN_INTERVAL}s ({SCAN_INTERVAL//60}min)")
    log(f"  止损管理: 每 {POSITION_MGR_INTERVAL}s")
    log(f"  AI 预算: ${AI_BUDGET}/次")
    log("=" * 50)

    last_scan = 0
    last_pos_mgr = 0

    while True:
        now = time.time()

        # 止损管理 (每 5 分钟)
        if now - last_pos_mgr >= POSITION_MGR_INTERVAL:
            log("📐 止损管理...")
            run_position_manager()
            last_pos_mgr = now

        # AI 扫描 (每 30 分钟)
        if now - last_scan >= SCAN_INTERVAL:
            run_ai_scan()
            last_scan = now

        # 睡 60 秒检查一次
        time.sleep(60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("调度器停止 (用户中断)")
