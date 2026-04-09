#!/usr/bin/env python3
"""持仓止损管理 — 纯代码自动执行，不需要 AI.

用法:
  python3 scripts/position_manager.py          # 单次运行
  在 cron 中每 5 分钟运行一次

规则:
  盈利 > 1 ATR → 止损移保本
  盈利 > 2 ATR → 锁定 1 ATR 利润
  盈利 > 3 ATR → 启用追踪止损 (回调率 1.5%)
  持仓 > 24h 无进展 (盈利 < 0.5 ATR) → 收紧止损 50%
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

# 加载 .env
ENV_FILE = PROJECT_DIR / ".env"
if ENV_FILE.exists():
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

TRAILING_CALLBACK_RATE = 1.5  # 追踪止损回调率 %


def log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def manage_positions():
    """检查所有持仓，按 ATR 规则管理止损."""
    from lib.binance import (
        get_position_risk, get_open_orders, get_klines,
        calc_atr, cancel_order, place_stop_market, place_trailing_stop,
    )

    try:
        positions = get_position_risk()
        active = [p for p in positions if float(p.get("positionAmt", 0)) != 0]
    except Exception as e:
        log(f"获取持仓失败: {e}")
        return

    if not active:
        log("无持仓")
        return

    for p in active:
        symbol = p["symbol"]
        amt = float(p["positionAmt"])
        entry = float(p["entryPrice"])
        mark = float(p["markPrice"])
        side = "long" if amt > 0 else "short"

        try:
            # 计算 ATR
            klines = get_klines(symbol, "1h", 20)
            atr = calc_atr(klines)
            if atr <= 0:
                continue

            # 计算浮盈 (以 ATR 为单位)
            if side == "long":
                profit_distance = mark - entry
            else:
                profit_distance = entry - mark
            profit_atr = profit_distance / atr

            # 获取当前止损单
            orders = get_open_orders(symbol)
            current_stop = None
            stop_order_ids = []  # 可能有多个止损单
            has_trailing = False
            for o in orders:
                otype = o.get("type", "")
                if otype == "TRAILING_STOP_MARKET":
                    has_trailing = True
                elif otype == "STOP_MARKET" and float(o.get("stopPrice", 0)) > 0:
                    sp = float(o["stopPrice"])
                    stop_order_ids.append(o.get("orderId"))
                    # 取最接近当前价的止损 (最新的那个)
                    if current_stop is None:
                        current_stop = sp
                    elif side == "long" and sp > current_stop:
                        current_stop = sp
                    elif side == "short" and sp < current_stop:
                        current_stop = sp

            # ─── 止损缺失检查 ───
            if current_stop is None and not has_trailing:
                log(f"⚠️ {symbol} {side} 没有止损单！需要手动处理")
                continue

            # ─── 已有追踪止损，不再调整 ───
            if has_trailing:
                log(f"  {symbol} {side} 追踪止损生效中, 盈利 {profit_atr:.1f} ATR")
                continue

            # ─── ATR 规则 ───
            close_side = "SELL" if side == "long" else "BUY"
            qty = abs(amt)

            def _cancel_all_stops():
                """取消所有止损单."""
                for oid in stop_order_ids:
                    try:
                        cancel_order(symbol, oid)
                    except Exception:
                        pass

            if profit_atr >= 3.0:
                # 盈利 > 3 ATR → 启用追踪止损
                log(f"  {symbol} {side} 盈利 {profit_atr:.1f} ATR → 启用追踪止损 ({TRAILING_CALLBACK_RATE}%)")
                _cancel_all_stops()
                place_trailing_stop(symbol, close_side, TRAILING_CALLBACK_RATE, qty)

            elif profit_atr >= 2.0:
                # 盈利 > 2 ATR → 锁定 1 ATR 利润
                if side == "long":
                    new_stop = entry + atr
                else:
                    new_stop = entry - atr
                new_stop = round(new_stop, 4)

                if current_stop is None or (side == "long" and new_stop > current_stop) or \
                   (side == "short" and new_stop < current_stop):
                    log(f"  {symbol} {side} 盈利 {profit_atr:.1f} ATR → 止损移至 ${new_stop} (锁 1ATR)")
                    _cancel_all_stops()
                    place_stop_market(symbol, close_side, new_stop, qty)
                else:
                    log(f"  {symbol} {side} 盈利 {profit_atr:.1f} ATR, 止损已在 ${current_stop} (无需调整)")

            elif profit_atr >= 1.0:
                # 盈利 > 1 ATR → 止损移保本
                new_stop = round(entry, 4)
                if current_stop is None or (side == "long" and new_stop > current_stop) or \
                   (side == "short" and new_stop < current_stop):
                    log(f"  {symbol} {side} 盈利 {profit_atr:.1f} ATR → 止损移保本 ${new_stop}")
                    _cancel_all_stops()
                    place_stop_market(symbol, close_side, new_stop, qty)
                else:
                    log(f"  {symbol} {side} 盈利 {profit_atr:.1f} ATR, 止损已在 ${current_stop}")

            else:
                log(f"  {symbol} {side} 盈利 {profit_atr:.1f} ATR, 止损 ${current_stop} (不调整)")

        except Exception as e:
            log(f"  {symbol} 处理异常: {e}")


if __name__ == "__main__":
    log("=== 持仓止损管理 ===")
    manage_positions()
    log("=== 完成 ===")
