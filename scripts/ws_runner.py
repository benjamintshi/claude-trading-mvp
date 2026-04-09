#!/usr/bin/env python3
"""WebSocket 实时价格监控 — 启动器.

用法:
  python3 scripts/ws_runner.py           # 前台运行
  python3 scripts/ws_runner.py --daemon  # 后台运行 (nohup)

架构:
  1. 每 60 秒检查持仓列表
  2. 有持仓时: 连接 WebSocket, 实时监控价格
  3. 价格进入警戒区 → 调用 claude -p 做 AI 评估
  4. 持仓全平 → 断开 WS, 回到轮询模式
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# 确保 lib 可导入
PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from lib.ws_monitor import (
    TriggerEngine, WatchConfig, TriggerEvent,
    build_eval_prompt, build_agent_prompts, build_coordinator_prompt,
)

# 加载 .env
ENV_FILE = PROJECT_DIR / ".env"
if ENV_FILE.exists():
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

PAPER_TRADING = os.getenv("PAPER_TRADING", "").lower() in ("true", "1", "yes")
LOCK_FILE = PROJECT_DIR / "data" / ".ws_eval.lock"
LOG_FILE = PROJECT_DIR / "data" / "logs" / "ws_monitor.log"
TRIGGER_LOG = PROJECT_DIR / "data" / "logs" / "ws_triggers.json"

# AI 评估配置
AI_MAX_BUDGET = float(os.getenv("WS_EVAL_MAX_BUDGET", "0.30"))
AI_TIMEOUT = int(os.getenv("WS_EVAL_TIMEOUT", "120"))
AGENT_TIMEOUT = int(os.getenv("WS_AGENT_TIMEOUT", "60"))  # 单个 agent 超时
POSITION_REFRESH_INTERVAL = 300  # 5 分钟刷新持仓配置
NO_POSITION_POLL_INTERVAL = 60   # 无持仓时 60 秒轮询
MULTI_AGENT = os.getenv("WS_MULTI_AGENT", "true").lower() in ("true", "1", "yes")


def log(msg: str):
    """日志输出."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def log_trigger(event: TriggerEvent):
    """记录触发事件到 JSON."""
    try:
        TRIGGER_LOG.parent.mkdir(parents=True, exist_ok=True)
        records = []
        if TRIGGER_LOG.exists():
            with open(TRIGGER_LOG) as f:
                records = json.load(f)
        records.append({
            "symbol": event.symbol,
            "type": event.trigger_type,
            "price": event.current_price,
            "threshold": event.threshold_price,
            "distance_pct": event.distance_pct,
            "urgency": event.urgency,
            "detail": event.detail,
            "time": event.timestamp,
        })
        # 只保留最近 500 条
        records = records[-500:]
        with open(TRIGGER_LOG, "w") as f:
            json.dump(records, f, indent=2)
    except Exception:
        pass


# ─── 持仓配置加载 ────────────────────────────────────────

def get_current_regime() -> str:
    """获取当前市场状态 (BTC 1h)."""
    try:
        from lib.binance import get_klines, detect_regime
        klines = get_klines("BTCUSDT", "1h", 100)
        regime = detect_regime(klines)
        return regime.get("regime_cn", "未知")
    except Exception:
        return ""


def load_watch_configs() -> dict[str, WatchConfig]:
    """从 Binance/Paper 获取当前持仓, 构建监控配置."""
    from lib.binance import (
        get_position_risk, get_open_orders, get_klines,
        detect_support_resistance, calc_atr,
    )

    configs = {}
    try:
        positions = get_position_risk()
        active = [p for p in positions if float(p.get("positionAmt", 0)) != 0]
    except Exception as e:
        log(f"获取持仓失败: {e}")
        return configs

    for p in active:
        symbol = p["symbol"]
        try:
            amt = float(p["positionAmt"])
            entry = float(p["entryPrice"])
            side = "long" if amt > 0 else "short"

            # 获取挂单 (止损/止盈价格)
            orders = get_open_orders(symbol)
            stop = 0.0
            tp = 0.0
            has_trailing = False
            for o in orders:
                otype = o.get("type", "")
                sp = float(o.get("stopPrice", 0))
                if otype == "STOP_MARKET" and sp > 0:
                    stop = sp
                elif otype == "TRAILING_STOP_MARKET":
                    has_trailing = True
                    callback = float(o.get("callbackRate", 1.5))
                    # 追踪止损位: 用 peak_price (Paper) 或 markPrice 估算
                    peak = float(o.get("peak_price", 0))
                    mark = float(p.get("markPrice", 0))
                    ref_price = peak if peak > 0 else mark
                    if side == "short" and ref_price > 0:
                        stop = round(ref_price * (1 + callback / 100), 4)
                    elif side == "long" and ref_price > 0:
                        stop = round(ref_price * (1 - callback / 100), 4)
                elif otype == "TAKE_PROFIT_MARKET" and sp > 0:
                    tp = sp

            # 获取 ATR 和支撑/阻力
            klines = get_klines(symbol, "1h", 100)
            atr = calc_atr(klines)
            sr = detect_support_resistance(klines)

            configs[symbol] = WatchConfig(
                symbol=symbol,
                side=side,
                entry_price=entry,
                stop_price=stop,
                take_profit_price=tp,
                atr=atr,
                supports=sr.get("supports", [])[:3],
                resistances=sr.get("resistances", [])[:3],
            )
            sl_label = f"TSL≈${stop:.2f}" if has_trailing else f"SL=${stop:.2f}"
            log(f"  监控: {symbol} {side} entry=${entry:.2f} {sl_label} TP=${tp:.2f} ATR=${atr:.2f}")

        except Exception as e:
            log(f"  加载 {symbol} 配置失败: {e}")

    return configs


# ─── AI 评估调用 (多 Agent 并行) ──────────────────────────

# 异步锁: 防止并发评估
_eval_lock = asyncio.Lock()


def _fetch_signal_snapshot(symbol: str) -> str:
    """获取最新市场数据快照，直接附在 prompt 里减少 AI 工具调用."""
    try:
        from lib.binance import get_signal_snapshot, get_realtime_context
        s = get_signal_snapshot(symbol)

        lines = [
            f"\n## 技术指标 (1h 周期)",
            f"- RSI(14): {s.get('rsi', 0):.1f}",
            f"- MACD 柱: {s.get('macd', {}).get('histogram', 0):+.4f}",
            f"- EMA 趋势: {s.get('ema_trend', 'N/A')}",
            f"- 布林带: upper={s.get('bollinger', {}).get('upper', 0):.2f} "
            f"lower={s.get('bollinger', {}).get('lower', 0):.2f}",
            f"- Funding: {s.get('funding_rate', 0)*100:+.4f}%",
            f"- 多空比: {s.get('long_short_ratio', 0):.2f}",
            f"- Taker 买卖比: {s.get('taker_buy_sell_ratio', 0):.2f}",
        ]

        # 实时盘口上下文
        try:
            ctx = get_realtime_context(symbol)

            ob = ctx.get("orderbook")
            if ob:
                lines.append(f"\n## 实时盘口")
                lines.append(f"- 买盘总量: {ob['bid_total']} | 卖盘总量: {ob['ask_total']}")
                lines.append(f"- 买卖力量比: {ob['imbalance']:.3f} ({'买方强' if ob['imbalance'] > 1.2 else '卖方强' if ob['imbalance'] < 0.8 else '均衡'})")
                lines.append(f"- 最大买墙: ${ob['bid_wall']['price']} ({ob['bid_wall']['qty']})")
                lines.append(f"- 最大卖墙: ${ob['ask_wall']['price']} ({ob['ask_wall']['qty']})")
                lines.append(f"- 价差: {ob['spread_pct']:.4f}%")

            stf = ctx.get("short_tf")
            if stf:
                lines.append(f"\n## 短周期信号 (5m)")
                lines.append(f"- RSI(5m): {stf['rsi_5m']}")
                lines.append(f"- MACD 柱(5m): {stf['macd_5m_hist']:+.6f}")
                lines.append(f"- 近期量能变化: {stf['volume_change']:+.1f}%")

            oid = ctx.get("oi_divergence")
            if oid:
                lines.append(f"\n## 持仓量变化")
                lines.append(f"- OI 24h 变化: {oid['oi_change_pct']:+.2f}% (异常度 {oid['oi_percentile']:.0f}%)")
                lines.append(f"- OI 1h 变化: {ctx.get('oi_1h_change_pct', 0):+.2f}%")
                if oid['divergence'] != 'none':
                    div_cn = "空头挤压酝酿中" if oid['divergence'] == 'bullish_squeeze' else "多头过度拥挤"
                    lines.append(f"- ⚠️ OI 背离: {div_cn}")

        except Exception:
            pass  # 实时数据获取失败不影响基础指标

        lines.append(f"\n数据已全部提供，不需要再调用任何 API。")
        return "\n".join(lines)

    except Exception as e:
        return f"\n## 市场数据获取失败: {e}\n"


async def run_single_agent(role: str, prompt: str, max_turns: int = 1,
                           timeout: int = None) -> str:
    """异步运行单个 claude -p Agent."""
    timeout = timeout or AGENT_TIMEOUT
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", "--max-turns", str(max_turns),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(PROJECT_DIR),
            env={**os.environ, "PAPER_TRADING": "true" if PAPER_TRADING else "false"},
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=prompt.encode()),
            timeout=timeout,
        )
        if proc.returncode == 0:
            return stdout.decode().strip()
        else:
            err = stderr.decode().strip() or stdout.decode().strip()
            return f"[{role} 错误]: {err[:300]}"
    except asyncio.TimeoutError:
        log(f"  {role} 超时 ({timeout}s)")
        try:
            proc.kill()
        except Exception:
            pass
        return f"[{role} 超时]"
    except FileNotFoundError:
        return f"[{role} 失败: claude 命令未找到]"
    except Exception as e:
        return f"[{role} 异常: {e}]"


async def multi_agent_evaluation(event: TriggerEvent, config: WatchConfig,
                                 regime: str = ""):
    """多 Agent 并行评估: 3 专家并行 → Coordinator 汇总决策."""
    snapshot = _fetch_signal_snapshot(event.symbol)

    # Phase 1: 3 个 Agent 并行 (分析, 不执行)
    prompts = build_agent_prompts(event, config, regime=regime, snapshot=snapshot)
    log(f"  🚀 启动 3 Agent 并行: Bull / Bear / Analyst")
    t0 = time.time()

    bull_result, bear_result, analyst_result = await asyncio.gather(
        run_single_agent("Bull", prompts["bull"], max_turns=1),
        run_single_agent("Bear", prompts["bear"], max_turns=1),
        run_single_agent("Analyst", prompts["analyst"], max_turns=1),
    )
    phase1_time = time.time() - t0
    log(f"  Phase 1 完成 ({phase1_time:.1f}s): "
        f"Bull {len(bull_result)}字 / Bear {len(bear_result)}字 / "
        f"Analyst {len(analyst_result)}字")

    # Phase 2: Coordinator 汇总决策 (可调用工具执行)
    coordinator_prompt = build_coordinator_prompt(
        event, config, regime, snapshot,
        bull=bull_result, bear=bear_result, analyst=analyst_result,
    )
    log(f"  🎯 Coordinator 汇总决策...")
    t1 = time.time()

    decision = await run_single_agent(
        "Coordinator", coordinator_prompt, max_turns=5, timeout=AI_TIMEOUT,
    )
    phase2_time = time.time() - t1
    total_time = time.time() - t0
    log(f"  Phase 2 完成 ({phase2_time:.1f}s) | 总耗时 {total_time:.1f}s")

    # 记录备忘录
    try:
        from lib.trade_memo import record_ws_decision
        record_ws_decision(
            symbol=event.symbol, trigger_type=event.trigger_type,
            price=event.current_price, bull_summary=bull_result,
            bear_summary=bear_result, analyst_summary=analyst_result,
            decision=decision, detail=event.detail,
        )
    except Exception:
        pass

    return decision


async def single_agent_evaluation(event: TriggerEvent, config: WatchConfig,
                                  regime: str = ""):
    """单 Agent 评估 (fallback 模式)."""
    prompt = build_eval_prompt(event, config, regime=regime)
    prompt += _fetch_signal_snapshot(event.symbol)
    prompt += "\n数据已提供，直接做出决策即可。不需要再调用 get_signal_snapshot。\n"
    return await run_single_agent("SingleAgent", prompt, max_turns=5, timeout=AI_TIMEOUT)


async def trigger_ai_evaluation(event: TriggerEvent, config: WatchConfig,
                                regime: str = ""):
    """触发 AI 评估 — 多 Agent 或单 Agent."""
    if _eval_lock.locked():
        log(f"  跳过: 另一个 AI 评估正在运行")
        return

    async with _eval_lock:
        mode = "多Agent" if MULTI_AGENT else "单Agent"
        log(f"  调用 AI 评估 [{mode}]: {event.symbol} {event.trigger_type}")

        try:
            if MULTI_AGENT:
                decision = await multi_agent_evaluation(event, config, regime)
            else:
                decision = await single_agent_evaluation(event, config, regime)

            output = decision[-500:]
            log(f"  AI 决策: {output[:200]}...")

            # 推送 Telegram 通知
            try:
                from lib.notify import notify_trigger
                notify_trigger(
                    event.symbol, event.trigger_type,
                    event.current_price, event.detail,
                    decision=output[:200],
                )
            except Exception:
                pass

        except Exception as e:
            log(f"  AI 评估异常: {e}")


# ─── 主监控循环 ──────────────────────────────────────────

async def monitor_loop():
    """主监控循环: WebSocket 实时价格 → 触发检测 → AI 评估."""
    from ccxt.pro import binanceusdm

    engine = TriggerEngine()
    configs: dict[str, WatchConfig] = {}
    last_config_refresh = 0
    current_regime = ""

    while True:
        # 1. 刷新持仓配置 + 市场状态
        now = time.time()
        if now - last_config_refresh > POSITION_REFRESH_INTERVAL or not configs:
            log("刷新持仓配置...")
            configs = load_watch_configs()
            current_regime = get_current_regime()
            if current_regime:
                log(f"  市场状态: {current_regime}")
                engine.cooldown.set_regime(current_regime)
            last_config_refresh = now

            if not configs:
                log(f"无持仓, {NO_POSITION_POLL_INTERVAL}s 后重试")
                await asyncio.sleep(NO_POSITION_POLL_INTERVAL)
                continue

        # 2. 连接 WebSocket
        exchange = binanceusdm({"enableRateLimit": True})
        symbols = [_to_ccxt_symbol(s) for s in configs.keys()]
        log(f"连接 WebSocket: {list(configs.keys())}")

        try:
            while True:
                # 检查是否需要刷新配置
                if time.time() - last_config_refresh > POSITION_REFRESH_INTERVAL:
                    break  # 跳出内循环去刷新

                # 监听多个 symbol 的 mark price
                for ccxt_sym in symbols:
                    try:
                        ticker = await asyncio.wait_for(
                            exchange.watch_mark_price(ccxt_sym),
                            timeout=5.0,
                        )
                        binance_sym = ticker["symbol"].replace("/", "").replace(":USDT", "")
                        price = ticker["markPrice"]

                        if binance_sym not in configs:
                            continue

                        # 记录价格
                        engine.on_price_update(binance_sym, price)

                        # 检查触发
                        events = engine.check_triggers(binance_sym, price, configs[binance_sym])

                        if events:
                            for event in events:
                                log(f"🔔 触发: {event.symbol} {event.trigger_type} "
                                    f"price=${event.current_price:.2f} → {event.detail}")
                                log_trigger(event)
                                engine.record_triggers([event])
                                # 异步启动 AI 评估 (不阻塞 WS 循环)
                                asyncio.create_task(
                                    trigger_ai_evaluation(
                                        event, configs[binance_sym],
                                        regime=current_regime,
                                    )
                                )

                    except asyncio.TimeoutError:
                        continue
                    except Exception as e:
                        log(f"WS 消息处理异常: {e}")
                        continue

        except Exception as e:
            log(f"WebSocket 连接异常: {e}, 5s 后重连")
            await asyncio.sleep(5)
        finally:
            try:
                await exchange.close()
            except Exception:
                pass


def _to_ccxt_symbol(binance_symbol: str) -> str:
    """BTCUSDT → BTC/USDT:USDT (ccxt 格式)."""
    base = binance_symbol.replace("USDT", "")
    return f"{base}/USDT:USDT"


# ─── Paper 模式增强 ──────────────────────────────────────

async def paper_price_callback(symbol: str, price: float):
    """Paper 模式下用 WS 实时价格驱动 check_triggers."""
    if not PAPER_TRADING:
        return
    try:
        from lib import paper
        from lib.binance import get_price as _get_price
        triggered = paper.check_triggers(
            lambda s: price if s == symbol else _get_price(s)
        )
        if triggered:
            for t in triggered:
                log(f"📋 Paper 触发: {t['symbol']} {t['type']} @${t['trigger_price']:.2f}")
    except Exception:
        pass


# ─── 入口 ────────────────────────────────────────────────

def main():
    mode = "PAPER" if PAPER_TRADING else "LIVE"
    agent_mode = "多Agent (Bull/Bear/Analyst→Coordinator)" if MULTI_AGENT else "单Agent"
    log(f"=" * 50)
    log(f"WebSocket 监控启动 [{mode}]")
    log(f"  AI 模式: {agent_mode}")
    log(f"  AI 预算: ${AI_MAX_BUDGET}/次 | 超时: {AI_TIMEOUT}s")
    log(f"  冷却: 最多 {TriggerEngine().cooldown.MAX_HOURLY_CALLS} 次/小时")
    log(f"=" * 50)

    try:
        asyncio.run(monitor_loop())
    except KeyboardInterrupt:
        log("WebSocket 监控停止 (用户中断)")
    except Exception as e:
        log(f"WebSocket 监控异常退出: {e}")
        raise


if __name__ == "__main__":
    main()
