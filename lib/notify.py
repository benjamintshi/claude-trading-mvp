"""Telegram notifications."""

import os
import urllib.request
import urllib.parse
import json

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def send(message: str):
    """Send a Telegram message."""
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


def notify_open(symbol, side, entry, stop, target, reason, quantity, score):
    """Send open position notification."""
    notional = entry * quantity
    risk = abs(entry - stop) * quantity
    reward = abs(target - entry) * quantity if target else 0
    ratio = reward / risk if risk > 0 else 0

    msg = f"""🟢 *MC 开仓*
━━━━━━━━━━━━━━━━
📊 `{symbol}` *{side.upper()}*
💰 入场: `${entry:.4f}`
🛑 止损: `${stop:.4f}`
🎯 目标: `${target:.4f}` ({ratio:.1f}:1)
📐 名义值: `${notional:.0f}` (qty: {quantity:.4f})
🎲 评分: {score}/10
💡 {reason}"""
    send(msg)


def notify_close(symbol, side, entry, exit_price, pnl, pnl_pct, duration_hours, reason):
    """Send close position notification."""
    emoji = "🟢" if pnl > 0 else "🔴"
    msg = f"""{emoji} *MC 平仓*
━━━━━━━━━━━━━━━━
📊 `{symbol}` *{side.upper()}*
💰 ${entry:.4f} → ${exit_price:.4f}
📈 盈亏: `${pnl:+.2f}` ({pnl_pct:+.1f}%)
⏱ 持仓: {duration_hours:.1f}h
💡 {reason}"""
    send(msg)


if __name__ == "__main__":
    send("🧪 Claude Trader test notification")
