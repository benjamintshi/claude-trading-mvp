"""Paper Trading 模拟引擎 — 用真实行情，模拟执行.

所有行情数据走真实 Binance API，订单/持仓/PnL 本地模拟。
数据持久化到 JSON 文件，跨会话保持状态。

用法: 设置环境变量 PAPER_TRADING=true，binance.py 自动切换。
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

# 数据文件路径
DATA_DIR = Path(os.getenv("PAPER_DATA_DIR", "data/paper"))
POSITIONS_FILE = DATA_DIR / "positions.json"
ORDERS_FILE = DATA_DIR / "orders.json"
TRADES_FILE = DATA_DIR / "trades.json"
BALANCE_FILE = DATA_DIR / "balance.json"

# 初始余额
DEFAULT_BALANCE = float(os.getenv("PAPER_INITIAL_BALANCE", "2000"))


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(filepath: Path, default):
    if filepath.exists():
        with open(filepath) as f:
            return json.load(f)
    return default


def _save_json(filepath: Path, data):
    _ensure_data_dir()
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


# ─── 余额 ────────────────────────────────────────────────

def get_balance_state() -> dict:
    """获取余额状态."""
    default = {
        "total_balance": DEFAULT_BALANCE,
        "available_balance": DEFAULT_BALANCE,
        "unrealized_pnl": 0.0,
        "realized_pnl_today": 0.0,
        "today_date": _today_str(),
    }
    state = _load_json(BALANCE_FILE, default)
    # 日期翻转 → 重置当日 PnL
    if state.get("today_date") != _today_str():
        state["realized_pnl_today"] = 0.0
        state["today_date"] = _today_str()
        _save_json(BALANCE_FILE, state)
    return state


def _update_balance(realized_pnl: float = 0, margin_change: float = 0):
    """更新余额. realized_pnl: 已实现盈亏, margin_change: 保证金占用变化 (正=占用, 负=释放)."""
    state = get_balance_state()
    state["total_balance"] += realized_pnl
    state["available_balance"] += realized_pnl - margin_change
    state["realized_pnl_today"] += realized_pnl
    _save_json(BALANCE_FILE, state)
    return state


def _today_str() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


# ─── 订单 ────────────────────────────────────────────────

def get_all_orders() -> list:
    return _load_json(ORDERS_FILE, [])


def _save_orders(orders: list):
    _save_json(ORDERS_FILE, orders)


def place_order_paper(symbol: str, side: str, order_type: str,
                      quantity: float = 0, price: float = 0,
                      stop_price: float = 0, callback_rate: float = 0,
                      reduce_only: bool = False, close_position: bool = False,
                      current_price: float = 0) -> dict:
    """模拟下单.

    MARKET 单立即成交 (用 current_price)。
    STOP_MARKET / TAKE_PROFIT_MARKET / TRAILING_STOP_MARKET 挂单等待触发。
    """
    order_id = int(time.time() * 1000) + int(uuid.uuid4().int % 10000)
    now = int(time.time() * 1000)

    order = {
        "orderId": order_id,
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "quantity": quantity,
        "price": price,
        "stopPrice": stop_price,
        "callbackRate": callback_rate,
        "reduceOnly": reduce_only,
        "closePosition": close_position,
        "status": "NEW",
        "time": now,
        "updateTime": now,
    }

    if order_type == "MARKET":
        # 立即成交
        fill_price = current_price if current_price > 0 else price
        order["status"] = "FILLED"
        order["avgPrice"] = fill_price
        order["executedQty"] = quantity

        if not reduce_only and not close_position:
            _open_or_add_position(symbol, side, quantity, fill_price)
        else:
            _close_position_by_order(symbol, side, quantity, fill_price)
    else:
        # 挂单 — 存到 orders 列表等待 check_triggers
        orders = get_all_orders()
        orders.append(order)
        _save_orders(orders)

    return order


def cancel_order_paper(symbol: str, order_id: int) -> dict:
    orders = get_all_orders()
    for o in orders:
        if o["orderId"] == order_id and o["symbol"] == symbol:
            o["status"] = "CANCELED"
            _save_orders(orders)
            return o
    return {"code": -2011, "msg": "Order not found"}


def cancel_all_orders_paper(symbol: str) -> dict:
    orders = get_all_orders()
    canceled = 0
    for o in orders:
        if o["symbol"] == symbol and o["status"] == "NEW":
            o["status"] = "CANCELED"
            canceled += 1
    _save_orders(orders)
    return {"code": 200, "msg": f"Canceled {canceled} orders"}


def get_open_orders_paper(symbol: str = "") -> list:
    orders = get_all_orders()
    active = [o for o in orders if o["status"] == "NEW"]
    if symbol:
        active = [o for o in active if o["symbol"] == symbol]
    return active


# ─── 持仓 ────────────────────────────────────────────────

def get_all_positions() -> list:
    return _load_json(POSITIONS_FILE, [])


def _save_positions(positions: list):
    _save_json(POSITIONS_FILE, positions)


def _find_position(symbol: str) -> dict | None:
    for p in get_all_positions():
        if p["symbol"] == symbol and float(p["positionAmt"]) != 0:
            return p
    return None


def _open_or_add_position(symbol: str, side: str, quantity: float, fill_price: float):
    """开仓或加仓."""
    positions = get_all_positions()
    existing = None
    for p in positions:
        if p["symbol"] == symbol:
            existing = p
            break

    signed_qty = quantity if side == "BUY" else -quantity

    if existing and float(existing["positionAmt"]) != 0:
        # 加仓 — 计算均价
        old_amt = float(existing["positionAmt"])
        old_entry = float(existing["entryPrice"])
        new_amt = old_amt + signed_qty
        if abs(new_amt) > 0 and (old_amt * signed_qty > 0):
            # 同方向加仓
            new_entry = (old_entry * abs(old_amt) + fill_price * quantity) / abs(new_amt)
            existing["entryPrice"] = str(new_entry)
        existing["positionAmt"] = str(new_amt)
    else:
        # 新开仓
        if existing:
            existing["positionAmt"] = str(signed_qty)
            existing["entryPrice"] = str(fill_price)
        else:
            positions.append({
                "symbol": symbol,
                "positionAmt": str(signed_qty),
                "entryPrice": str(fill_price),
                "markPrice": str(fill_price),
                "unRealizedProfit": "0",
                "liquidationPrice": "0",
                "leverage": "3",
                "marginType": "cross",
                "isolatedMargin": "0",
                "notional": str(quantity * fill_price),
            })

    margin = quantity * fill_price / 3  # 3x leverage
    _update_balance(margin_change=margin)
    _save_positions(positions)


def _close_position_by_order(symbol: str, side: str, quantity: float, fill_price: float):
    """平仓."""
    positions = get_all_positions()
    for p in positions:
        if p["symbol"] != symbol:
            continue
        amt = float(p["positionAmt"])
        if amt == 0:
            continue

        entry = float(p["entryPrice"])
        close_qty = min(quantity, abs(amt))

        # 计算 PnL
        if amt > 0:  # long position
            pnl = (fill_price - entry) * close_qty
        else:  # short position
            pnl = (entry - fill_price) * close_qty

        # 手续费模拟 (0.075% 双边)
        commission = (entry * close_qty + fill_price * close_qty) * 0.00075
        net_pnl = pnl - commission

        # 更新持仓
        if amt > 0:
            new_amt = amt - close_qty
        else:
            new_amt = amt + close_qty
        p["positionAmt"] = str(new_amt)

        # 释放保证金 + 结算盈亏
        margin_released = close_qty * entry / 3
        _update_balance(realized_pnl=net_pnl, margin_change=-margin_released)

        # 记录成交
        _record_trade(symbol, "LONG" if amt > 0 else "SHORT", entry, fill_price,
                      close_qty, net_pnl, commission)
        break

    _save_positions(positions)


def _record_trade(symbol: str, side: str, entry: float, exit_price: float,
                  quantity: float, pnl: float, commission: float):
    """记录成交到 trades.json."""
    trades = _load_json(TRADES_FILE, [])
    trades.append({
        "symbol": symbol,
        "side": side,
        "entryPrice": entry,
        "exitPrice": exit_price,
        "quantity": quantity,
        "pnl": round(pnl, 4),
        "commission": round(commission, 4),
        "time": int(time.time() * 1000),
        "date": _today_str(),
    })
    _save_json(TRADES_FILE, trades)


# ─── 止损/止盈触发检查 ──────────────────────────────────

def check_triggers(price_fetcher) -> list:
    """检查挂单是否触发 — 每次 trade-loop 调用.

    price_fetcher: callable(symbol) -> float, 传入真实的 get_price 函数.
    返回: 触发的订单列表.
    """
    orders = get_all_orders()
    triggered = []

    for o in orders:
        if o["status"] != "NEW":
            continue

        symbol = o["symbol"]
        try:
            current_price = price_fetcher(symbol)
        except Exception:
            continue

        stop_price = float(o.get("stopPrice", 0))
        order_type = o["type"]
        side = o["side"]
        should_trigger = False

        if order_type == "STOP_MARKET" and stop_price > 0:
            # 止损: BUY 止损 → 价格 >= stopPrice, SELL 止损 → 价格 <= stopPrice
            if side == "BUY" and current_price >= stop_price:
                should_trigger = True
            elif side == "SELL" and current_price <= stop_price:
                should_trigger = True

        elif order_type == "TAKE_PROFIT_MARKET" and stop_price > 0:
            # 止盈: BUY 止盈 → 价格 <= stopPrice, SELL 止盈 → 价格 >= stopPrice
            if side == "BUY" and current_price <= stop_price:
                should_trigger = True
            elif side == "SELL" and current_price >= stop_price:
                should_trigger = True

        elif order_type == "TRAILING_STOP_MARKET":
            # 追踪止损: 简化处理 — 用 callback_rate 计算
            callback = float(o.get("callbackRate", 1.0))
            pos = _find_position(symbol)
            if pos:
                amt = float(pos["positionAmt"])
                # 记录最高/最低价 (存在 order 里)
                if "peak_price" not in o:
                    o["peak_price"] = current_price
                if amt > 0:  # long → 追踪高点
                    o["peak_price"] = max(o["peak_price"], current_price)
                    trigger_price = o["peak_price"] * (1 - callback / 100)
                    if current_price <= trigger_price:
                        should_trigger = True
                else:  # short → 追踪低点
                    o["peak_price"] = min(o["peak_price"], current_price)
                    trigger_price = o["peak_price"] * (1 + callback / 100)
                    if current_price >= trigger_price:
                        should_trigger = True

        if should_trigger:
            o["status"] = "FILLED"
            o["avgPrice"] = current_price
            qty = float(o.get("quantity", 0))

            # closePosition 模式
            if o.get("closePosition"):
                pos = _find_position(symbol)
                if pos:
                    qty = abs(float(pos["positionAmt"]))

            if qty > 0:
                _close_position_by_order(symbol, side, qty, current_price)

            triggered.append({
                "symbol": symbol,
                "type": order_type,
                "side": side,
                "trigger_price": current_price,
                "quantity": qty,
            })

    _save_orders(orders)
    return triggered


# ─── 模拟 Binance API 响应格式 ───────────────────────────

def get_position_risk_paper(symbol: str = "") -> list:
    """模拟 get_position_risk 返回格式，注入真实 markPrice."""
    positions = get_all_positions()
    result = []
    for p in positions:
        if symbol and p["symbol"] != symbol:
            continue
        result.append(p.copy())
    return result


def update_mark_prices(price_fetcher):
    """用真实价格更新所有持仓的 markPrice 和 unRealizedProfit."""
    positions = get_all_positions()
    changed = False
    for p in positions:
        amt = float(p["positionAmt"])
        if amt == 0:
            continue
        try:
            mark = price_fetcher(p["symbol"])
            p["markPrice"] = str(mark)
            entry = float(p["entryPrice"])
            if amt > 0:
                upnl = (mark - entry) * abs(amt)
            else:
                upnl = (entry - mark) * abs(amt)
            p["unRealizedProfit"] = str(round(upnl, 4))
            changed = True
        except Exception:
            pass

    if changed:
        _save_positions(positions)

    # 更新余额中的浮盈
    total_upnl = sum(float(p["unRealizedProfit"]) for p in positions
                     if float(p.get("positionAmt", 0)) != 0)
    state = get_balance_state()
    state["unrealized_pnl"] = round(total_upnl, 4)
    _save_json(BALANCE_FILE, state)


def get_account_paper() -> dict:
    """模拟 get_account 返回格式."""
    state = get_balance_state()
    positions = get_all_positions()
    active = [p for p in positions if float(p.get("positionAmt", 0)) != 0]

    total_margin = sum(
        abs(float(p["positionAmt"])) * float(p["entryPrice"]) / int(p.get("leverage", 3))
        for p in active
    )
    # 维持保证金 ≈ 持仓名义值 * 0.4% (简化)
    maint_margin = sum(
        abs(float(p["positionAmt"])) * float(p.get("markPrice", p["entryPrice"])) * 0.004
        for p in active
    )

    return {
        "totalWalletBalance": str(state["total_balance"]),
        "totalMarginBalance": str(state["total_balance"] + state["unrealized_pnl"]),
        "availableBalance": str(state["available_balance"]),
        "totalMaintMargin": str(round(maint_margin, 4)),
        "totalUnrealizedProfit": str(state["unrealized_pnl"]),
        "positions": positions,
    }


def get_balance_paper() -> list:
    """模拟 get_balance 返回格式."""
    state = get_balance_state()
    return [{
        "asset": "USDT",
        "balance": str(state["total_balance"]),
        "availableBalance": str(state["available_balance"]),
        "crossUnPnl": str(state["unrealized_pnl"]),
    }]


def get_income_history_paper(income_type: str = "", symbol: str = "",
                             start_time: int = 0, limit: int = 100) -> list:
    """模拟 get_income_history — 从 trades.json 生成."""
    trades = _load_json(TRADES_FILE, [])

    result = []
    for t in reversed(trades):  # 最新在前
        if start_time and t["time"] < start_time:
            continue
        if symbol and t["symbol"] != symbol:
            continue

        if not income_type or income_type == "REALIZED_PNL":
            result.append({
                "symbol": t["symbol"],
                "incomeType": "REALIZED_PNL",
                "income": str(t["pnl"]),
                "time": t["time"],
            })
        if not income_type or income_type == "COMMISSION":
            result.append({
                "symbol": t["symbol"],
                "incomeType": "COMMISSION",
                "income": str(-t["commission"]),
                "time": t["time"],
            })

        if len(result) >= limit:
            break

    return result[:limit]


def get_user_trades_paper(symbol: str, limit: int = 50) -> list:
    """模拟 get_user_trades."""
    trades = _load_json(TRADES_FILE, [])
    filtered = [t for t in trades if t["symbol"] == symbol]
    return filtered[-limit:]


def get_today_realized_pnl_paper() -> float:
    """模拟 get_today_realized_pnl."""
    state = get_balance_state()
    return state["realized_pnl_today"]


# ─── Paper Trading 统计 ──────────────────────────────────

def get_paper_stats() -> dict:
    """获取 paper trading 统计摘要."""
    trades = _load_json(TRADES_FILE, [])
    state = get_balance_state()

    if not trades:
        return {
            "total_trades": 0,
            "balance": state["total_balance"],
            "pnl": 0,
            "win_rate": 0,
        }

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    total_pnl = sum(t["pnl"] for t in trades)
    total_commission = sum(t["commission"] for t in trades)

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades) * 100 if trades else 0,
        "total_pnl": round(total_pnl, 2),
        "total_commission": round(total_commission, 2),
        "net_pnl": round(total_pnl, 2),
        "avg_win": round(sum(t["pnl"] for t in wins) / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(t["pnl"] for t in losses) / len(losses), 2) if losses else 0,
        "best_trade": round(max(t["pnl"] for t in trades), 2) if trades else 0,
        "worst_trade": round(min(t["pnl"] for t in trades), 2) if trades else 0,
        "balance": round(state["total_balance"], 2),
        "initial_balance": DEFAULT_BALANCE,
        "return_pct": round((state["total_balance"] - DEFAULT_BALANCE) / DEFAULT_BALANCE * 100, 2),
    }


def reset_paper():
    """重置 paper trading — 清除所有数据."""
    _ensure_data_dir()
    for f in [POSITIONS_FILE, ORDERS_FILE, TRADES_FILE, BALANCE_FILE]:
        if f.exists():
            f.unlink()
    return {"msg": "Paper trading reset. Balance back to ${:.0f}".format(DEFAULT_BALANCE)}
