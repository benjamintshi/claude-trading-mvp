"""Telegram 通知 — 交易全链路推送."""

import os
import time
import urllib.request
import urllib.parse
import json

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def send(message: str):
    """发送 Telegram 消息."""
    if not BOT_TOKEN or not CHAT_ID:
        print(f"[TG disabled] {message}")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }).encode()

    try:
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"[TG error] {e}")


def notify_open(symbol, side, entry, stop, target, reason, quantity, score=0,
                conviction="standard", regime="", risk_usd=0, risk_pct=0):
    """开仓通知."""
    notional = entry * quantity
    risk = abs(entry - stop) * quantity
    reward = abs(target - entry) * quantity if target else 0
    ratio = reward / risk if risk > 0 else 0
    stop_pct = abs(entry - stop) / entry * 100 if entry > 0 else 0

    conv_emoji = {"high": "🔴", "standard": "🟡", "probe": "🟢"}.get(conviction, "⚪")

    msg = f"""🟢 *MC 开仓*
━━━━━━━━━━━━━━━━━━━━━
📊 *{symbol}*  `{side.upper()}`
━━━━━━━━━━━━━━━━━━━━━
💰 入场: `${entry:.4f}`
🛑 止损: `${stop:.4f}` ({stop_pct:.1f}%)
🎯 目标: `${target:.4f}` (赔率 {ratio:.1f}:1)
━━━━━━━━━━━━━━━━━━━━━
📐 数量: `{quantity:.4f}`
💵 名义: `${notional:,.0f}`
⚠️ 风险: `${risk:.2f}` ({risk_pct:.2f}%)
{conv_emoji} 信心: *{conviction.upper()}*
🌊 市场: {regime if regime else 'N/A'}
━━━━━━━━━━━━━━━━━━━━━
💡 *理由:* {reason}"""
    send(msg)


def notify_close(symbol, side, entry, exit_price, pnl, pnl_pct,
                 duration_hours, reason):
    """平仓通知."""
    emoji = "💰" if pnl > 0 else "💸"
    result = "盈利" if pnl > 0 else "亏损"
    ts = time.strftime("%m/%d %H:%M")

    # 持仓时长格式化
    if duration_hours >= 24:
        duration_str = f"{duration_hours/24:.1f}d"
    else:
        duration_str = f"{duration_hours:.1f}h"

    msg = f"""{emoji} *MC 平仓 — {result}*
━━━━━━━━━━━━━━━━━━━━━
📊 *{symbol}*  `{side.upper()}`
━━━━━━━━━━━━━━━━━━━━━
💰 入场: `${entry:.4f}`
🏁 出场: `${exit_price:.4f}`
📈 盈亏: *${pnl:+.2f}* ({pnl_pct:+.1f}%)
⏱ 持仓: {duration_str}
━━━━━━━━━━━━━━━━━━━━━
💡 {reason}
🕐 {ts}"""
    send(msg)


def notify_trigger(symbol, trigger_type, price, detail, decision=""):
    """WebSocket 触发通知."""
    type_emoji = {
        "near_stop": "🚨",
        "near_tp": "🎯",
        "near_support": "📉",
        "near_resistance": "📈",
        "atr_breakout": "⚡",
    }.get(trigger_type, "🔔")

    type_cn = {
        "near_stop": "接近止损",
        "near_tp": "接近止盈",
        "near_support": "接近支撑",
        "near_resistance": "接近阻力",
        "atr_breakout": "ATR 突破",
    }.get(trigger_type, trigger_type)

    msg = f"""{type_emoji} *WS 触发: {type_cn}*
━━━━━━━━━━━━━━━━━━━━━
📊 *{symbol}*  `${price:.4f}`
📋 {detail}"""

    if decision:
        msg += f"""
━━━━━━━━━━━━━━━━━━━━━
🤖 *AI 决策:* {decision[:200]}"""

    send(msg)


def notify_scan_result(summary: str):
    """扫描结果通知."""
    msg = f"""🔍 *MC 市场扫描*
━━━━━━━━━━━━━━━━━━━━━
🕐 {time.strftime("%m/%d %H:%M")}
━━━━━━━━━━━━━━━━━━━━━
{summary[:800]}"""
    send(msg)


def notify_breaker(level: str, reasons: list):
    """熔断通知."""
    emoji = "🚨" if level == "emergency" else "🔴"
    msg = f"""{emoji} *熔断触发: {level.upper()}*
━━━━━━━━━━━━━━━━━━━━━
"""
    for r in reasons:
        msg += f"⚠️ {r}\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━\n🛑 *已暂停开新仓*"
    send(msg)


def notify_stop_moved(symbol, side, old_stop, new_stop, reason):
    """止损移动通知."""
    msg = f"""📐 *止损调整*
━━━━━━━━━━━━━━━━━━━━━
📊 *{symbol}*  `{side.upper()}`
🔄 `${old_stop:.4f}` → `${new_stop:.4f}`
💡 {reason}"""
    send(msg)


if __name__ == "__main__":
    send("🧪 Claude Trader test notification")
