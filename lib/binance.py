"""Binance Futures API wrapper — 完整能力覆盖.

只做 API 传话，不含任何交易逻辑/策略。
决策由 Claude + Skills 负责，执行由 Binance 负责。

Paper Trading 模式: 设置 PAPER_TRADING=true
- 行情数据 (价格/K线/OI/funding) → 真实 Binance API
- 订单/持仓/PnL → 本地模拟 (lib/paper.py)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.request
import urllib.parse

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BASE_URL = "https://fapi.binance.com"

# Paper Trading 模式
PAPER_TRADING = os.getenv("PAPER_TRADING", "").lower() in ("true", "1", "yes")


# ─── 基础设施 ─────────────────────────────────────────────

def _sign(params: dict) -> dict:
    """Add timestamp and signature to params."""
    params["timestamp"] = int(time.time() * 1000)
    query = urllib.parse.urlencode(params)
    signature = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = signature
    return params


def _request(method: str, path: str, params: dict | None = None, signed: bool = False, retries: int = 3):
    """Make API request with retry."""
    params = params or {}
    if signed:
        params = _sign(params)

    url = f"{BASE_URL}{path}"
    last_error = None

    for attempt in range(retries):
        try:
            if method == "POST":
                req = urllib.request.Request(url)
                req.add_header("X-MBX-APIKEY", API_KEY)
                data = urllib.parse.urlencode(params).encode()
                resp = urllib.request.urlopen(req, data=data, timeout=10)
            elif method == "PUT":
                full_url = url + "?" + urllib.parse.urlencode(params) if params else url
                req = urllib.request.Request(full_url, method="PUT")
                req.add_header("X-MBX-APIKEY", API_KEY)
                resp = urllib.request.urlopen(req, timeout=10)
            elif method == "DELETE":
                full_url = url + "?" + urllib.parse.urlencode(params) if params else url
                req = urllib.request.Request(full_url, method="DELETE")
                req.add_header("X-MBX-APIKEY", API_KEY)
                resp = urllib.request.urlopen(req, timeout=10)
            else:  # GET
                full_url = url + "?" + urllib.parse.urlencode(params) if params else url
                req = urllib.request.Request(full_url)
                req.add_header("X-MBX-APIKEY", API_KEY)
                resp = urllib.request.urlopen(req, timeout=10)

            return json.loads(resp.read())

        except Exception as e:
            last_error = e
            if attempt < retries - 1:
                time.sleep(1 * (attempt + 1))  # 1s, 2s backoff

    raise last_error


# ─── 行情 (Public, 无需签名) ──────────────────────────────

def get_price(symbol: str) -> float:
    """获取当前价格."""
    data = _request("GET", "/fapi/v1/ticker/price", {"symbol": symbol})
    return float(data["price"])


def get_ticker_24h(symbol: str) -> dict:
    """获取 24h 行情统计."""
    return _request("GET", "/fapi/v1/ticker/24hr", {"symbol": symbol})


def get_all_tickers() -> list:
    """获取所有 24h 行情."""
    return _request("GET", "/fapi/v1/ticker/24hr")


def get_tradable_symbols(min_volume_usdt: float = 50_000_000,
                         top_n: int = 50,
                         quote_asset: str = "USDT") -> list[dict]:
    """动态筛选可交易标的 — 按 24h 成交量排序，过滤低流动性币种.

    筛选条件:
    - 仅 USDT 永续合约
    - 24h 成交额 > min_volume_usdt (默认 5000 万 USDT)
    - 排除稳定币对 (BUSDUSDT 等)
    - 按成交额降序，取 top_n 个

    返回: [{"symbol": "BTCUSDT", "price": 95000.0, "volume_usdt": 1e10,
             "change_pct": -1.2, "high": 96000, "low": 94000}, ...]
    """
    tickers = get_all_tickers()

    # 过滤
    stable_coins = {"BUSDUSDT", "USDCUSDT", "TUSDUSDT", "FDUSDUSDT", "DAIUSDT"}
    candidates = []
    for t in tickers:
        sym = t["symbol"]
        if not sym.endswith(quote_asset):
            continue
        if sym in stable_coins:
            continue
        vol = float(t.get("quoteVolume", 0))
        if vol < min_volume_usdt:
            continue
        # 过滤停盘/僵尸币 (高=低 → 完全不动)
        high = float(t.get("highPrice", 0))
        low = float(t.get("lowPrice", 0))
        if high > 0 and high == low:
            continue
        candidates.append({
            "symbol": sym,
            "price": float(t["lastPrice"]),
            "volume_usdt": vol,
            "change_pct": float(t["priceChangePercent"]),
            "high": float(t["highPrice"]),
            "low": float(t["lowPrice"]),
        })

    # 按成交额降序
    candidates.sort(key=lambda x: x["volume_usdt"], reverse=True)
    top = candidates[:top_n + 10]  # 多取一些，留余量给过滤

    # 二次过滤: 对可疑币检查 orderbook (振幅 > 50% 的币可能已停盘)
    verified = []
    for c in top:
        if c["high"] > 0 and c["low"] > 0 and c["price"] > 0:
            spread = (c["high"] - c["low"]) / c["price"]
            if spread > 0.5:
                try:
                    ob = get_order_book(c["symbol"], limit=5)
                    if not ob.get("bids") and not ob.get("asks"):
                        continue  # orderbook 空 → 已停盘
                except Exception:
                    pass
        verified.append(c)
        if len(verified) >= top_n:
            break

    return verified


def get_funding_rate(symbol: str) -> float:
    """获取当前 funding rate."""
    data = _request("GET", "/fapi/v1/fundingRate", {"symbol": symbol, "limit": 1})
    return float(data[0]["fundingRate"]) if data else 0.0


def get_mark_price(symbol: str) -> dict:
    """获取标记价格 + funding rate + 下次结算时间."""
    return _request("GET", "/fapi/v1/premiumIndex", {"symbol": symbol})


def get_klines(symbol: str, interval: str = "1h", limit: int = 100) -> list[list]:
    """获取 K 线数据.

    interval: 1m/3m/5m/15m/30m/1h/2h/4h/6h/8h/12h/1d/3d/1w/1M
    返回: [[open_time, open, high, low, close, volume, close_time,
            quote_volume, trades, taker_buy_base_vol, taker_buy_quote_vol, ignore], ...]
    """
    return _request("GET", "/fapi/v1/klines",
                    {"symbol": symbol, "interval": interval, "limit": limit})


def get_open_interest(symbol: str) -> dict:
    """获取当前持仓量 (Open Interest).

    返回: {"openInterest": "12345.678", "symbol": "BTCUSDT", "time": 1234567890}
    """
    return _request("GET", "/fapi/v1/openInterest", {"symbol": symbol})


def get_open_interest_hist(symbol: str, period: str = "1h", limit: int = 30) -> list:
    """获取持仓量历史.

    period: 5m/15m/30m/1h/2h/4h/6h/12h/1d
    返回: [{"sumOpenInterest": "...", "sumOpenInterestValue": "...", "timestamp": ...}, ...]
    最多回溯 30 天。
    """
    return _request("GET", "/futures/data/openInterestHist",
                    {"symbol": symbol, "period": period, "limit": limit})


def get_long_short_ratio(symbol: str, period: str = "1h", limit: int = 30) -> list:
    """获取全市场多空比 (账户数).

    返回: [{"longShortRatio": "1.5", "longAccount": "0.6", "shortAccount": "0.4", "timestamp": ...}, ...]
    """
    return _request("GET", "/futures/data/globalLongShortAccountRatio",
                    {"symbol": symbol, "period": period, "limit": limit})


def get_top_long_short_ratio(symbol: str, period: str = "1h", limit: int = 30) -> list:
    """获取大户多空比 (持仓量).

    返回: [{"longShortRatio": "1.2", "longAccount": "0.55", "shortAccount": "0.45", "timestamp": ...}, ...]
    """
    return _request("GET", "/futures/data/topLongShortPositionRatio",
                    {"symbol": symbol, "period": period, "limit": limit})


def get_taker_buy_sell_ratio(symbol: str, period: str = "1h", limit: int = 30) -> list:
    """获取主动买卖量比.

    返回: [{"buySellRatio": "0.95", "buyVol": "...", "sellVol": "...", "timestamp": ...}, ...]
    buySellRatio > 1 = 买方主导, < 1 = 卖方主导
    """
    return _request("GET", "/futures/data/takerlongshortRatio",
                    {"symbol": symbol, "period": period, "limit": limit})


def get_order_book(symbol: str, limit: int = 20) -> dict:
    """获取 Order Book 深度.

    limit: 5/10/20/50/100/500/1000
    返回: {"bids": [[price, qty], ...], "asks": [[price, qty], ...]}
    """
    return _request("GET", "/fapi/v1/depth", {"symbol": symbol, "limit": limit})


# ─── 订单 — 核心 (Signed) ─────────────────────────────────

def place_order(symbol: str, side: str, order_type: str, quantity: float = 0,
                price: float = 0, stop_price: float = 0, close_position: bool = False,
                callback_rate: float = 0, reduce_only: bool = False,
                time_in_force: str = "", working_type: str = "MARK_PRICE") -> dict:
    """下单 — 支持所有订单类型.

    order_type: MARKET, LIMIT, STOP_MARKET, TAKE_PROFIT_MARKET, TRAILING_STOP_MARKET
    side: BUY, SELL
    working_type: MARK_PRICE (默认, 推荐) 或 CONTRACT_PRICE
    """
    params = {
        "symbol": symbol,
        "side": side,
        "type": order_type,
    }

    if quantity > 0:
        params["quantity"] = quantity
    if price > 0:
        params["price"] = price
    if stop_price > 0:
        params["stopPrice"] = stop_price
    if close_position:
        params["closePosition"] = "true"
    if callback_rate > 0:
        params["callbackRate"] = callback_rate
    if reduce_only:
        params["reduceOnly"] = "true"
    if time_in_force:
        params["timeInForce"] = time_in_force
    if order_type in ("STOP_MARKET", "TAKE_PROFIT_MARKET", "TRAILING_STOP_MARKET"):
        params["workingType"] = working_type

    return _request("POST", "/fapi/v1/order", params, signed=True)


# ─── 订单 — 便捷函数 ──────────────────────────────────────

def open_long(symbol: str, quantity: float, leverage: int = 3) -> dict:
    """开多 — MARKET 单."""
    set_leverage(symbol, leverage)
    return place_order(symbol, "BUY", "MARKET", quantity=quantity)


def open_short(symbol: str, quantity: float, leverage: int = 3) -> dict:
    """开空 — MARKET 单."""
    set_leverage(symbol, leverage)
    return place_order(symbol, "SELL", "MARKET", quantity=quantity)


def close_long(symbol: str, quantity: float) -> dict:
    """平多."""
    return place_order(symbol, "SELL", "MARKET", quantity=quantity, reduce_only=True)


def close_short(symbol: str, quantity: float) -> dict:
    """平空."""
    return place_order(symbol, "BUY", "MARKET", quantity=quantity, reduce_only=True)


def place_stop_market(symbol: str, side: str, stop_price: float,
                      quantity: float = 0, close_position: bool = False) -> dict:
    """交易所端止损单 — 到价自动市价平仓.

    close_position=True: 不需要指定 quantity, 自动平掉该方向全部仓位
    """
    return place_order(symbol, side, "STOP_MARKET",
                       quantity=quantity, stop_price=stop_price,
                       close_position=close_position)


def place_take_profit_market(symbol: str, side: str, stop_price: float,
                             quantity: float = 0, close_position: bool = False) -> dict:
    """交易所端止盈单 — 到价自动市价平仓."""
    return place_order(symbol, side, "TAKE_PROFIT_MARKET",
                       quantity=quantity, stop_price=stop_price,
                       close_position=close_position)


def place_trailing_stop(symbol: str, side: str, callback_rate: float,
                        quantity: float = 0, activation_price: float = 0) -> dict:
    """追踪止损 — 价格回调 callback_rate% 时触发平仓.

    callback_rate: 0.1 ~ 5.0 (百分比)
    activation_price: 可选，到达此价格后才激活追踪
    """
    params = {
        "symbol": symbol,
        "side": side,
        "type": "TRAILING_STOP_MARKET",
        "callbackRate": callback_rate,
    }
    if quantity > 0:
        params["quantity"] = quantity
    if activation_price > 0:
        params["activationPrice"] = activation_price
    params["workingType"] = "MARK_PRICE"

    return _request("POST", "/fapi/v1/order", _sign(params))


def batch_orders(orders: list[dict]) -> list:
    """批量下单 — 最多 5 单一次.

    orders: [{"symbol":"BTCUSDT","side":"BUY","type":"MARKET","quantity":0.001}, ...]
    用于一次性下 开仓 + 止损 + 止盈 三连单。
    """
    params = {
        "batchOrders": json.dumps(orders),
    }
    return _request("POST", "/fapi/v1/batchOrders", params, signed=True)


# ─── 开仓三连 (开仓 + 止损 + 止盈, 一次性) ────────────────

LIMIT_PRICE_BUFFER_PCT = 0.05  # 限价单价格缓冲 0.05%
LIMIT_ORDER_TIMEOUT = 60       # 限价单等待超时 (秒)
LIMIT_ORDER_MAX_RETRIES = 3    # 最大重试次数
LIMIT_ORDER_POLL_INTERVAL = 5  # 轮询间隔 (秒)


def open_position_with_sl_tp(symbol: str, side: str, quantity: float,
                              stop_price: float, take_profit_price: float,
                              leverage: int = 3) -> list:
    """一键开仓: LIMIT 限价开仓 + STOP_MARKET 止损 + TAKE_PROFIT_MARKET 止盈.

    流程:
    1. 用当前价 ± 0.05% 下限价单
    2. 每 5 秒轮询，60 秒未成交 → 取消 → 用新价格重新挂单
    3. 最多重试 3 次，全部失败则放弃
    4. 成交后验证止损/止盈，失败则紧急平仓

    side: "long" 或 "short"
    """
    set_leverage(symbol, leverage)

    if side.lower() == "long":
        entry_side = "BUY"
        exit_side = "SELL"
    else:
        entry_side = "SELL"
        exit_side = "BUY"

    # ─── 限价单重试循环 ───
    fill_price = 0
    entry_ok = False

    for attempt in range(1, LIMIT_ORDER_MAX_RETRIES + 1):
        current_price = get_price(symbol)
        if entry_side == "BUY":
            limit_price = round(current_price * (1 + LIMIT_PRICE_BUFFER_PCT / 100), 8)
        else:
            limit_price = round(current_price * (1 - LIMIT_PRICE_BUFFER_PCT / 100), 8)

        # 下限价单
        try:
            entry_order = place_order(
                symbol, entry_side, "LIMIT",
                quantity=quantity, price=limit_price,
                time_in_force="GTC",
            )
        except Exception as e:
            _notify_warning(symbol, f"限价单下单失败 (尝试 {attempt}): {e}")
            if attempt < LIMIT_ORDER_MAX_RETRIES:
                time.sleep(2)
                continue
            return []

        order_id = entry_order.get("orderId")
        if not order_id:
            continue

        # 轮询等待成交
        waited = 0
        while waited < LIMIT_ORDER_TIMEOUT:
            time.sleep(LIMIT_ORDER_POLL_INTERVAL)
            waited += LIMIT_ORDER_POLL_INTERVAL
            try:
                status = _request("GET", "/fapi/v1/order",
                                  {"symbol": symbol, "orderId": order_id},
                                  signed=True)
                if status.get("status") == "FILLED":
                    fill_price = float(status.get("avgPrice", 0))
                    entry_ok = True
                    break
                elif status.get("status") in ("CANCELED", "EXPIRED", "REJECTED"):
                    break
            except Exception:
                continue

        if entry_ok:
            break

        # 未成交 → 取消，准备重试
        try:
            cancel_order(symbol, order_id)
        except Exception:
            pass

        if attempt < LIMIT_ORDER_MAX_RETRIES:
            _notify_warning(symbol,
                f"限价单 {attempt}/{LIMIT_ORDER_MAX_RETRIES} 未成交 "
                f"(限价 ${limit_price:.4f})，重新挂单...")
        else:
            _notify_warning(symbol,
                f"限价单 {LIMIT_ORDER_MAX_RETRIES} 次均未成交，放弃开仓")
            return []

    if not entry_ok:
        return []

    # ─── 成交后下止损 + 止盈 ───
    results = [{"type": "LIMIT", "status": "FILLED", "avgPrice": fill_price,
                "orderId": order_id}]
    sl_ok = False
    tp_ok = False

    # 止损 (必须成功，否则平仓)
    try:
        sl_result = place_stop_market(symbol, exit_side, stop_price, quantity)
        sl_ok = True
        results.append(sl_result)
    except Exception:
        # 重试一次
        try:
            time.sleep(1)
            sl_result = place_stop_market(symbol, exit_side, stop_price, quantity)
            sl_ok = True
            results.append(sl_result)
        except Exception:
            _emergency_close(symbol, exit_side, quantity, "止损下单失败，紧急平仓")
            return results

    # 止盈 (失败不平仓，止损已保护)
    try:
        tp_result = place_take_profit_market(symbol, exit_side, take_profit_price, quantity)
        tp_ok = True
        results.append(tp_result)
    except Exception:
        _notify_warning(symbol, "止盈下单失败，止损已在，手动补止盈")

    return results


def _emergency_close(symbol: str, close_side: str, quantity: float, reason: str):
    """紧急平仓 — 不留裸仓."""
    try:
        place_order(symbol, close_side, "MARKET", quantity=quantity, reduce_only=True)
        cancel_all_orders(symbol)
    except Exception:
        pass
    _notify_warning(symbol, f"🚨 紧急平仓: {reason}")


def _notify_warning(symbol: str, message: str):
    """发送告警通知."""
    try:
        from lib.notify import send
        send(f"⚠️ *{symbol}* — {message}")
    except Exception:
        pass


# ─── 订单管理 ─────────────────────────────────────────────

def cancel_order(symbol: str, order_id: int) -> dict:
    """撤销单个订单."""
    return _request("DELETE", "/fapi/v1/order",
                    {"symbol": symbol, "orderId": order_id}, signed=True)


def cancel_all_orders(symbol: str) -> dict:
    """撤销某个交易对的全部挂单."""
    return _request("DELETE", "/fapi/v1/allOpenOrders",
                    {"symbol": symbol}, signed=True)


def get_open_orders(symbol: str = "") -> list:
    """查询所有挂单 (含止损/止盈单).

    不传 symbol 返回所有交易对的挂单。
    """
    params = {}
    if symbol:
        params["symbol"] = symbol
    return _request("GET", "/fapi/v1/openOrders", params, signed=True)


def countdown_cancel_all(symbol: str, countdown_time: int = 1800000) -> dict:
    """死人开关 — N 毫秒内没有续命就自动撤销全部挂单.

    默认 30 分钟 (1800000ms)。
    每次 trade-loop 循环开头调用来续命。
    设为 0 关闭倒计时。

    注意: 只撤销挂单，不影响已持有的仓位。
    已有的 STOP_MARKET/TAKE_PROFIT_MARKET 止损止盈单也会被撤。
    所以死人开关主要保护 "未成交的限价开仓单"。
    """
    return _request("POST", "/fapi/v1/countdownCancelAll",
                    {"symbol": symbol, "countdownTime": countdown_time}, signed=True)


# ─── 账户 & 仓位 ──────────────────────────────────────────

def set_leverage(symbol: str, leverage: int) -> dict:
    """设置杠杆."""
    return _request("POST", "/fapi/v1/leverage",
                    {"symbol": symbol, "leverage": leverage}, signed=True)


def get_account() -> dict:
    """获取账户信息 — 余额、保证金、仓位等."""
    return _request("GET", "/fapi/v2/account", {}, signed=True)


def get_balance() -> list:
    """获取账户余额列表."""
    return _request("GET", "/fapi/v2/balance", {}, signed=True)


def get_usdt_balance() -> float:
    """获取 USDT 可用余额."""
    balances = get_balance()
    for b in balances:
        if b["asset"] == "USDT":
            return float(b["availableBalance"])
    return 0.0


def get_positions() -> list:
    """获取交易所端有仓位的品种 (从 account 接口)."""
    account = get_account()
    return [p for p in account.get("positions", []) if float(p.get("positionAmt", 0)) != 0]


def get_position_risk(symbol: str = "") -> list:
    """获取仓位详情 — 含浮动盈亏、强平价、标记价、杠杆等.

    返回字段包括:
    - symbol, positionAmt, entryPrice, markPrice, unRealizedProfit
    - liquidationPrice, leverage, marginType, isolatedMargin
    - notional, maxNotionalValue

    不传 symbol 返回所有有仓位的品种。
    """
    params = {}
    if symbol:
        params["symbol"] = symbol
    return _request("GET", "/fapi/v2/positionRisk", params, signed=True)


# ─── 交易历史 & 盈亏 ──────────────────────────────────────

def get_income_history(income_type: str = "", symbol: str = "",
                       start_time: int = 0, limit: int = 100) -> list:
    """获取盈亏历史 — 实现盈亏/Funding/手续费/全记录.

    income_type: REALIZED_PNL, FUNDING_FEE, COMMISSION, TRANSFER, 等
    不传 type 返回所有类型。
    默认返回最近 7 天数据，最远 3 个月。
    """
    params = {"limit": limit}
    if income_type:
        params["incomeType"] = income_type
    if symbol:
        params["symbol"] = symbol
    if start_time > 0:
        params["startTime"] = start_time
    return _request("GET", "/fapi/v1/income", params, signed=True)


def get_today_realized_pnl() -> float:
    """获取今日已实现盈亏总额 (用于熔断检查)."""
    # 今天 00:00 UTC 的时间戳
    import datetime
    today = datetime.datetime.now(datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start_ms = int(today.timestamp() * 1000)

    records = get_income_history(income_type="REALIZED_PNL", start_time=start_ms, limit=1000)
    return sum(float(r["income"]) for r in records)


def get_user_trades(symbol: str, limit: int = 50) -> list:
    """获取成交记录."""
    return _request("GET", "/fapi/v1/userTrades",
                    {"symbol": symbol, "limit": limit}, signed=True)


# ─── 技术指标 (纯数学, 从 klines 计算) ───────────────────

def _parse_closes(klines: list[list]) -> list[float]:
    """从 klines 提取收盘价序列."""
    return [float(k[4]) for k in klines]


def _parse_highs(klines: list[list]) -> list[float]:
    return [float(k[2]) for k in klines]


def _parse_lows(klines: list[list]) -> list[float]:
    return [float(k[3]) for k in klines]


def _parse_volumes(klines: list[list]) -> list[float]:
    return [float(k[5]) for k in klines]


def calc_ema(values: list[float], period: int) -> list[float]:
    """计算 EMA (指数移动平均).

    返回与 values 等长的列表，前 period-1 个元素用 SMA 填充。
    """
    if len(values) < period:
        return values[:]
    multiplier = 2 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append((v - ema[-1]) * multiplier + ema[-1])
    # 前面补齐
    result = [ema[0]] * (period - 1) + ema
    return result


def calc_sma(values: list[float], period: int) -> list[float]:
    """计算 SMA (简单移动平均)."""
    result = []
    for i in range(len(values)):
        if i < period - 1:
            result.append(sum(values[:i + 1]) / (i + 1))
        else:
            result.append(sum(values[i - period + 1:i + 1]) / period)
    return result


def calc_rsi(klines: list[list], period: int = 14) -> float:
    """从 K 线计算 RSI(period).

    返回最新一根的 RSI 值 (0-100)。
    """
    closes = _parse_closes(klines)
    if len(closes) < period + 1:
        return 50.0  # 数据不足返回中性值

    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))

    # Wilder's smoothing (EMA-style)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_bollinger(klines: list[list], period: int = 20, num_std: float = 2.0) -> dict:
    """从 K 线计算布林带.

    返回: {"upper": float, "middle": float, "lower": float, "bandwidth": float}
    """
    closes = _parse_closes(klines)
    if len(closes) < period:
        mid = closes[-1] if closes else 0
        return {"upper": mid, "middle": mid, "lower": mid, "bandwidth": 0}

    recent = closes[-period:]
    middle = sum(recent) / period
    variance = sum((c - middle) ** 2 for c in recent) / period
    std_dev = variance ** 0.5

    upper = middle + num_std * std_dev
    lower = middle - num_std * std_dev
    bandwidth = (upper - lower) / middle if middle > 0 else 0

    return {"upper": upper, "middle": middle, "lower": lower, "bandwidth": bandwidth}


def calc_atr(klines: list[list], period: int = 14) -> float:
    """从 K 线计算真实 ATR(period).

    比 24h 高低差更准确。
    """
    highs = _parse_highs(klines)
    lows = _parse_lows(klines)
    closes = _parse_closes(klines)

    if len(closes) < 2:
        return 0.0

    true_ranges = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return sum(true_ranges) / len(true_ranges) if true_ranges else 0.0

    # Wilder's smoothing
    atr = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def calc_macd(klines: list[list]) -> dict:
    """从 K 线计算 MACD (12, 26, 9).

    返回: {"macd": float, "signal": float, "histogram": float}
    """
    closes = _parse_closes(klines)
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)

    macd_line = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
    signal_line = calc_ema(macd_line, 9)

    return {
        "macd": macd_line[-1] if macd_line else 0,
        "signal": signal_line[-1] if signal_line else 0,
        "histogram": (macd_line[-1] - signal_line[-1]) if macd_line and signal_line else 0,
    }


def calc_vwap(klines: list[list]) -> float:
    """从 K 线计算 VWAP (当日).

    typical_price = (high + low + close) / 3
    vwap = sum(tp * vol) / sum(vol)
    """
    highs = _parse_highs(klines)
    lows = _parse_lows(klines)
    closes = _parse_closes(klines)
    volumes = _parse_volumes(klines)

    cum_tp_vol = 0
    cum_vol = 0
    for i in range(len(closes)):
        tp = (highs[i] + lows[i] + closes[i]) / 3
        cum_tp_vol += tp * volumes[i]
        cum_vol += volumes[i]

    return cum_tp_vol / cum_vol if cum_vol > 0 else closes[-1] if closes else 0


def get_signal_snapshot(symbol: str) -> dict:
    """一次性获取某个币种的全部增强信号数据.

    返回包含所有技术指标和市场微观结构数据的字典，供评分使用。
    调用 6 个 API，适合在 scan 时对每个币调用一次。
    """
    klines = get_klines(symbol, "1h", 100)
    ticker = get_ticker_24h(symbol)

    rsi = calc_rsi(klines)
    bb = calc_bollinger(klines)
    atr = calc_atr(klines)
    macd = calc_macd(klines)
    vwap = calc_vwap(klines[-24:])  # 最近 24h 的 VWAP

    ema12 = calc_ema(_parse_closes(klines), 12)
    ema26 = calc_ema(_parse_closes(klines), 26)

    price = float(ticker["lastPrice"])
    change_pct = float(ticker["priceChangePercent"])
    volume = float(ticker["quoteVolume"])

    # 市场微观结构
    try:
        oi = get_open_interest(symbol)
        oi_value = float(oi["openInterest"])
    except Exception:
        oi_value = 0

    try:
        ls = get_long_short_ratio(symbol, "1h", 1)
        ls_ratio = float(ls[0]["longShortRatio"]) if ls else 1.0
    except Exception:
        ls_ratio = 1.0

    try:
        taker = get_taker_buy_sell_ratio(symbol, "1h", 1)
        taker_ratio = float(taker[0]["buySellRatio"]) if taker else 1.0
    except Exception:
        taker_ratio = 1.0

    funding = get_funding_rate(symbol)

    return {
        "symbol": symbol,
        "price": price,
        "change_pct": change_pct,
        "volume_usdt": volume,
        "funding_rate": funding,
        # 技术指标
        "rsi": rsi,
        "ema12": ema12[-1] if ema12 else price,
        "ema26": ema26[-1] if ema26 else price,
        "ema_trend": "bullish" if (ema12 and ema26 and ema12[-1] > ema26[-1]) else "bearish",
        "bollinger": bb,
        "atr": atr,
        "macd": macd,
        "vwap": vwap,
        # 市场微观结构
        "open_interest": oi_value,
        "long_short_ratio": ls_ratio,
        "taker_buy_sell_ratio": taker_ratio,
    }


def get_realtime_context(symbol: str, price: float = 0) -> dict:
    """获取实时盘口上下文 — orderbook + OI 变化 + 多周期信号.

    专为 WebSocket 触发场景设计: 提供 AI 做决策需要的实时数据，
    补充 get_signal_snapshot 的滞后指标。
    """
    result = {}

    # 1. Orderbook 深度 — 买卖墙
    try:
        ob = get_order_book(symbol, limit=20)
        bids = [[float(p), float(q)] for p, q in ob.get("bids", [])[:10]]
        asks = [[float(p), float(q)] for p, q in ob.get("asks", [])[:10]]
        bid_total = sum(q for _, q in bids)
        ask_total = sum(q for _, q in asks)
        imbalance = bid_total / ask_total if ask_total > 0 else 1.0

        # 找买卖墙 (最大挂单)
        biggest_bid = max(bids, key=lambda x: x[1]) if bids else [0, 0]
        biggest_ask = max(asks, key=lambda x: x[1]) if asks else [0, 0]

        result["orderbook"] = {
            "bid_total": round(bid_total, 2),
            "ask_total": round(ask_total, 2),
            "imbalance": round(imbalance, 3),  # >1 买方强, <1 卖方强
            "bid_wall": {"price": biggest_bid[0], "qty": round(biggest_bid[1], 2)},
            "ask_wall": {"price": biggest_ask[0], "qty": round(biggest_ask[1], 2)},
            "spread_pct": round((asks[0][0] - bids[0][0]) / bids[0][0] * 100, 4) if bids and asks else 0,
        }
    except Exception:
        result["orderbook"] = None

    # 2. OI 背离分析
    try:
        result["oi_divergence"] = analyze_oi_divergence(symbol)
    except Exception:
        result["oi_divergence"] = None

    # 3. 短周期信号 (5m K线) — 补充 1h 的滞后性
    try:
        klines_5m = get_klines(symbol, "5m", 50)
        rsi_5m = calc_rsi(klines_5m)
        macd_5m = calc_macd(klines_5m)
        # 最近 5 根 5m K线的量能变化
        vols = [float(k[5]) for k in klines_5m[-5:]]
        vol_avg = sum(vols) / len(vols) if vols else 0
        vol_prev = [float(k[5]) for k in klines_5m[-10:-5]]
        vol_prev_avg = sum(vol_prev) / len(vol_prev) if vol_prev else vol_avg

        result["short_tf"] = {
            "rsi_5m": round(rsi_5m, 1),
            "macd_5m_hist": round(macd_5m.get("histogram", 0), 6),
            "volume_change": round((vol_avg / vol_prev_avg - 1) * 100, 1) if vol_prev_avg > 0 else 0,
        }
    except Exception:
        result["short_tf"] = None

    # 4. 近期爆仓估算 — 通过 OI 突降推断
    try:
        oi_hist = get_open_interest_hist(symbol, "5m", 12)  # 最近 1 小时
        if len(oi_hist) >= 2:
            oi_now = float(oi_hist[-1]["sumOpenInterestValue"])
            oi_1h_ago = float(oi_hist[0]["sumOpenInterestValue"])
            oi_1h_change = (oi_now - oi_1h_ago) / oi_1h_ago * 100 if oi_1h_ago > 0 else 0
            result["oi_1h_change_pct"] = round(oi_1h_change, 2)
        else:
            result["oi_1h_change_pct"] = 0
    except Exception:
        result["oi_1h_change_pct"] = 0

    return result


# ─── 市场状态识别 (Regime Detection) ────────────────────

def detect_regime(klines: list[list]) -> dict:
    """从 K 线判断当前市场状态 — 4 种状态分类.

    基于 ATR(14) 百分位 + EMA(26) 斜率判断:
    1. 低波趋势 (low_vol_trend)  — 顺势信号权重高
    2. 高波趋势 (high_vol_trend) — 追踪止损宽, 仓位减半
    3. 低波震荡 (low_vol_range)  — 逆向信号权重高
    4. 高波震荡 (high_vol_range) — 最危险, 评分门槛提高

    返回: {
        "regime": "low_vol_trend",
        "regime_cn": "低波趋势",
        "volatility": "low" | "high",
        "trend": "trending" | "ranging",
        "atr_percentile": 45.0,
        "ema_slope": 0.002,
        "score_threshold_adj": 0,   # 评分门槛调整
        "risk_multiplier": 1.0,     # 仓位风险乘数
        "strategy_hint": "..."
    }
    """
    if len(klines) < 50:
        return {
            "regime": "unknown", "regime_cn": "数据不足",
            "volatility": "unknown", "trend": "unknown",
            "atr_percentile": 50, "ema_slope": 0,
            "score_threshold_adj": 0, "risk_multiplier": 1.0,
            "strategy_hint": "数据不足，使用默认策略",
        }

    closes = _parse_closes(klines)
    highs = _parse_highs(klines)
    lows = _parse_lows(klines)

    # 1. 波动率: 计算滚动 ATR，看当前 ATR 在历史中的百分位
    true_ranges = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        true_ranges.append(tr)

    window = 14
    rolling_atrs = []
    for i in range(window, len(true_ranges) + 1):
        rolling_atrs.append(sum(true_ranges[i-window:i]) / window)

    if not rolling_atrs:
        current_atr = sum(true_ranges) / len(true_ranges) if true_ranges else 0
        atr_percentile = 50
    else:
        current_atr = rolling_atrs[-1]
        sorted_atrs = sorted(rolling_atrs)
        rank = sum(1 for a in sorted_atrs if a <= current_atr)
        atr_percentile = rank / len(sorted_atrs) * 100

    is_high_vol = atr_percentile > 60

    # 2. 趋势: EMA(26) 斜率 — 最近 10 根的变化率
    ema26 = calc_ema(closes, 26)
    if len(ema26) >= 10:
        ema_slope = (ema26[-1] - ema26[-10]) / ema26[-10] if ema26[-10] != 0 else 0
    else:
        ema_slope = 0

    # 价格是否在 EMA26 附近震荡 (距离 < 0.5 * ATR = ranging)
    price = closes[-1]
    distance_from_ema = abs(price - ema26[-1])
    is_trending = abs(ema_slope) > 0.005 or (current_atr > 0 and distance_from_ema > 1.5 * current_atr)

    # 3. 分类
    if not is_high_vol and is_trending:
        regime = "low_vol_trend"
        regime_cn = "低波趋势"
        adj = 0
        risk_mult = 1.0
        hint = "顺势信号优先: EMA交叉 +2, RSI 降权。适合追踪止损。"
    elif is_high_vol and is_trending:
        regime = "high_vol_trend"
        regime_cn = "高波趋势"
        adj = 0
        risk_mult = 0.5  # 仓位减半
        hint = "仓位减半! 止损放宽到 2x ATR。追踪止损回调率提高。"
    elif not is_high_vol and not is_trending:
        regime = "low_vol_range"
        regime_cn = "低波震荡"
        adj = 0
        risk_mult = 1.0
        hint = "逆向信号优先: RSI + 布林带 +2, EMA交叉降权。均值回归策略。"
    else:  # high_vol and ranging
        regime = "high_vol_range"
        regime_cn = "高波震荡"
        adj = 2  # 门槛提高 2 分
        risk_mult = 0.5
        hint = "最危险状态! 评分门槛 +2, 仓位减半。假突破频繁，建议观望。"

    return {
        "regime": regime,
        "regime_cn": regime_cn,
        "volatility": "high" if is_high_vol else "low",
        "trend": "trending" if is_trending else "ranging",
        "atr_percentile": round(atr_percentile, 1),
        "ema_slope": round(ema_slope, 5),
        "score_threshold_adj": adj,
        "risk_multiplier": risk_mult,
        "strategy_hint": hint,
    }


# ─── 支撑/阻力检测 (多周期 + 成交量密集区) ──────────────

def detect_support_resistance(klines: list[list], num_levels: int = 5) -> dict:
    """从 K 线检测关键支撑/阻力位.

    方法:
    1. 成交量密集区 (Volume Profile) — 按价格分桶，找高成交量区
    2. 枢轴点 (Pivot Points) — 前一周期的 High/Low/Close
    3. 多次触碰 — 价格多次到达但没突破的位置

    返回: {"supports": [价格...], "resistances": [价格...], "nearest_support": float, "nearest_resistance": float}
    """
    highs = _parse_highs(klines)
    lows = _parse_lows(klines)
    closes = _parse_closes(klines)
    volumes = _parse_volumes(klines)

    if not closes:
        return {"supports": [], "resistances": [], "nearest_support": 0, "nearest_resistance": 0}

    price = closes[-1]
    price_min = min(lows)
    price_max = max(highs)

    # 1. 成交量密集区 (Volume Profile)
    num_bins = 50
    if price_max <= price_min:
        bin_size = price * 0.001
    else:
        bin_size = (price_max - price_min) / num_bins

    volume_profile = {}
    for i in range(len(closes)):
        # 每根 K 线的典型价格
        tp = (highs[i] + lows[i] + closes[i]) / 3
        bin_idx = int((tp - price_min) / bin_size) if bin_size > 0 else 0
        bin_price = price_min + bin_idx * bin_size + bin_size / 2
        volume_profile[bin_price] = volume_profile.get(bin_price, 0) + volumes[i]

    # 找成交量最大的 N 个价格区
    sorted_bins = sorted(volume_profile.items(), key=lambda x: x[1], reverse=True)
    high_vol_levels = [p for p, v in sorted_bins[:num_levels * 2]]

    # 2. 枢轴点 — 最近 24 根 K 线
    recent = klines[-24:] if len(klines) >= 24 else klines
    pivot_high = max(float(k[2]) for k in recent)
    pivot_low = min(float(k[3]) for k in recent)
    pivot_close = float(recent[-1][4])
    pivot = (pivot_high + pivot_low + pivot_close) / 3
    r1 = 2 * pivot - pivot_low
    s1 = 2 * pivot - pivot_high

    # 3. 多次触碰检测 — 找价格多次接近但没突破的区域
    touch_levels = {}
    tolerance = price * 0.003  # 0.3% 容差
    for i in range(len(klines)):
        h = highs[i]
        l = lows[i]
        # 用整数分桶来检测多次触碰
        for test_price in [h, l]:
            bucket = round(test_price / tolerance) * tolerance
            touch_levels[bucket] = touch_levels.get(bucket, 0) + 1

    # 过滤: 触碰 >= 3 次的价格
    multi_touch = [p for p, count in touch_levels.items() if count >= 3]

    # 合并所有来源
    all_levels = set(high_vol_levels + [pivot, r1, s1] + multi_touch)
    supports = sorted([l for l in all_levels if l < price], reverse=True)[:num_levels]
    resistances = sorted([l for l in all_levels if l > price])[:num_levels]

    return {
        "supports": [round(s, 4) for s in supports],
        "resistances": [round(r, 4) for r in resistances],
        "nearest_support": round(supports[0], 4) if supports else 0,
        "nearest_resistance": round(resistances[0], 4) if resistances else 0,
        "pivot": round(pivot, 4),
        "r1": round(r1, 4),
        "s1": round(s1, 4),
    }


# ─── OI 背离优化 (百分位排名) ────────────────────────────

def analyze_oi_divergence(symbol: str) -> dict:
    """分析 OI 背离 — 带百分位排名过滤噪音.

    只有 OI 变化在历史前 20% (异常大) 时才算有效背离。

    返回: {
        "oi_change_pct": float,
        "oi_percentile": float,    # 0-100, 越高越异常
        "price_change_pct": float,
        "divergence": "bullish_squeeze" | "bearish_squeeze" | "none",
        "is_significant": bool,    # percentile > 80 才算显著
    }
    """
    try:
        oi_hist = get_open_interest_hist(symbol, "1h", 48)  # 48h 历史
    except Exception:
        return {"oi_change_pct": 0, "oi_percentile": 50, "price_change_pct": 0,
                "divergence": "none", "is_significant": False}

    if len(oi_hist) < 24:
        return {"oi_change_pct": 0, "oi_percentile": 50, "price_change_pct": 0,
                "divergence": "none", "is_significant": False}

    # 计算各时段 OI 变化率
    oi_values = [float(h["sumOpenInterestValue"]) for h in oi_hist]
    oi_changes = []
    for i in range(1, len(oi_values)):
        if oi_values[i - 1] > 0:
            oi_changes.append((oi_values[i] - oi_values[i - 1]) / oi_values[i - 1] * 100)

    if not oi_changes:
        return {"oi_change_pct": 0, "oi_percentile": 50, "price_change_pct": 0,
                "divergence": "none", "is_significant": False}

    # 最近 24h 的 OI 变化
    recent_oi_change = (oi_values[-1] - oi_values[-24]) / oi_values[-24] * 100 if oi_values[-24] > 0 else 0

    # 百分位排名 — 这个变化有多异常？
    abs_changes = sorted(abs(c) for c in oi_changes)
    rank = sum(1 for c in abs_changes if c <= abs(recent_oi_change))
    percentile = rank / len(abs_changes) * 100

    # 价格变化
    try:
        ticker = get_ticker_24h(symbol)
        price_change = float(ticker["priceChangePercent"])
    except Exception:
        price_change = 0

    # 背离判断 (仅 percentile > 80 才算)
    is_significant = percentile > 80
    divergence = "none"
    if is_significant:
        if recent_oi_change > 0 and price_change < -1:
            divergence = "bullish_squeeze"  # OI涨+价跌 → 空头挤压在酿
        elif recent_oi_change > 0 and price_change > 1:
            divergence = "bearish_squeeze"  # OI涨+价涨 → 多头过度

    return {
        "oi_change_pct": round(recent_oi_change, 2),
        "oi_percentile": round(percentile, 1),
        "price_change_pct": round(price_change, 2),
        "divergence": divergence,
        "is_significant": is_significant,
    }


# ─── 仓位相关性检查 ─────────────────────────────────────

def check_correlation(symbols: list[str], period: int = 72) -> dict:
    """检查多个币种的价格相关性.

    基于最近 period 根 1h K 线的收盘价收益率相关系数。

    返回: {"matrix": {(sym1,sym2): corr}, "high_corr_pairs": [(sym1,sym2,corr)], "avg_corr": float}
    """
    # 获取所有币种的收益率序列
    returns = {}
    for sym in symbols:
        try:
            klines = get_klines(sym, "1h", period)
            closes = _parse_closes(klines)
            rets = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
            returns[sym] = rets
        except Exception:
            continue

    if len(returns) < 2:
        return {"matrix": {}, "high_corr_pairs": [], "avg_corr": 0}

    # 计算相关系数矩阵
    syms = list(returns.keys())
    matrix = {}
    all_corrs = []

    for i in range(len(syms)):
        for j in range(i + 1, len(syms)):
            r1 = returns[syms[i]]
            r2 = returns[syms[j]]
            min_len = min(len(r1), len(r2))
            if min_len < 10:
                continue
            r1, r2 = r1[:min_len], r2[:min_len]

            # Pearson 相关系数
            n = min_len
            sum_r1 = sum(r1)
            sum_r2 = sum(r2)
            sum_r1r2 = sum(a * b for a, b in zip(r1, r2))
            sum_r1_sq = sum(a * a for a in r1)
            sum_r2_sq = sum(b * b for b in r2)

            num = n * sum_r1r2 - sum_r1 * sum_r2
            den = ((n * sum_r1_sq - sum_r1 ** 2) * (n * sum_r2_sq - sum_r2 ** 2)) ** 0.5

            corr = num / den if den > 0 else 0
            matrix[(syms[i], syms[j])] = round(corr, 3)
            all_corrs.append(corr)

    high_corr = [(s1, s2, c) for (s1, s2), c in matrix.items() if abs(c) > 0.7]
    avg_corr = sum(all_corrs) / len(all_corrs) if all_corrs else 0

    return {
        "matrix": matrix,
        "high_corr_pairs": high_corr,
        "avg_corr": round(avg_corr, 3),
    }


# ─── 仓位计算 (纯数学, 无 API 调用) ──────────────────────

def calc_quantity(symbol: str, capital: float, risk_pct: float,
                  entry: float, stop: float, leverage: int = 3) -> float:
    """根据风险计算仓位大小.

    risk_amount = capital * risk_pct  (如 $2000 * 1% = $20)
    quantity = risk_amount / |entry - stop|
    上限: capital * 5% * leverage 的名义值
    """
    risk_amount = capital * risk_pct
    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        return 0.0

    quantity = risk_amount / stop_distance
    notional = quantity * entry
    max_notional = capital * 0.05 * leverage

    if notional > max_notional:
        quantity = max_notional / entry

    return round(quantity, 3)


def calc_adaptive_risk_pct(score: int, regime: dict, base_risk: float = 0.01) -> float:
    """自适应风险百分比 — 评分越高仓位越大，市场状态影响仓位.

    score: 信号评分 (0-14)
    regime: detect_regime() 返回的状态字典
    base_risk: 基础风险百分比 (默认 1%)

    返回: 实际风险百分比 (0.005 ~ 0.015)
    """
    # 评分档位
    if score >= 12:
        score_mult = 1.5   # 高信心
    elif score >= 10:
        score_mult = 1.0   # 标准
    elif score >= 8:
        score_mult = 0.5   # 试探
    else:
        score_mult = 0     # 不开仓

    # 市场状态乘数
    regime_mult = regime.get("risk_multiplier", 1.0)

    risk_pct = base_risk * score_mult * regime_mult

    # 硬限制: 0.5% ~ 1.5%
    return max(0.005, min(0.015, risk_pct))


# ─── Paper Trading 模式切换 ──────────────────────────────
#
# PAPER_TRADING=true 时:
# - 行情函数不变 (get_price, get_klines, get_ticker_24h 等全走真实 API)
# - 写函数重定向到 lib/paper.py (订单/持仓/PnL 本地模拟)
# - 技术指标函数不变 (calc_rsi 等纯数学)
# - get_signal_snapshot 不变 (只读真实数据)

if PAPER_TRADING:
    from lib import paper as _paper

    # 保存真实的 get_price 给 paper 引擎用
    _real_get_price = get_price

    def _paper_place_order(symbol, side, order_type, quantity=0, price=0,
                           stop_price=0, close_position=False, callback_rate=0,
                           reduce_only=False, time_in_force="", working_type="MARK_PRICE"):
        current = _real_get_price(symbol)
        return _paper.place_order_paper(
            symbol, side, order_type, quantity=quantity, price=price,
            stop_price=stop_price, callback_rate=callback_rate,
            reduce_only=reduce_only, close_position=close_position,
            current_price=current)

    def _paper_open_long(symbol, quantity, leverage=3):
        return _paper_place_order(symbol, "BUY", "MARKET", quantity=quantity)

    def _paper_open_short(symbol, quantity, leverage=3):
        return _paper_place_order(symbol, "SELL", "MARKET", quantity=quantity)

    def _paper_close_long(symbol, quantity):
        return _paper_place_order(symbol, "SELL", "MARKET", quantity=quantity, reduce_only=True)

    def _paper_close_short(symbol, quantity):
        return _paper_place_order(symbol, "BUY", "MARKET", quantity=quantity, reduce_only=True)

    def _paper_place_stop_market(symbol, side, stop_price, quantity=0, close_position=False):
        return _paper_place_order(symbol, side, "STOP_MARKET",
                                  quantity=quantity, stop_price=stop_price, close_position=close_position)

    def _paper_place_take_profit_market(symbol, side, stop_price, quantity=0, close_position=False):
        return _paper_place_order(symbol, side, "TAKE_PROFIT_MARKET",
                                  quantity=quantity, stop_price=stop_price, close_position=close_position)

    def _paper_place_trailing_stop(symbol, side, callback_rate, quantity=0, activation_price=0):
        return _paper_place_order(symbol, side, "TRAILING_STOP_MARKET",
                                  quantity=quantity, callback_rate=callback_rate)

    def _paper_batch_orders(orders):
        results = []
        for o in orders:
            r = _paper_place_order(
                o["symbol"], o["side"], o["type"],
                quantity=float(o.get("quantity", 0)),
                stop_price=float(o.get("stopPrice", 0)),
            )
            results.append(r)
        return results

    def _paper_open_position_with_sl_tp(symbol, side, quantity, stop_price, take_profit_price, leverage=3):
        if side.lower() == "long":
            entry_side, exit_side = "BUY", "SELL"
        else:
            entry_side, exit_side = "SELL", "BUY"
        results = []
        results.append(_paper_place_order(symbol, entry_side, "MARKET", quantity=quantity))
        results.append(_paper_place_order(symbol, exit_side, "STOP_MARKET",
                                          quantity=quantity, stop_price=stop_price))
        results.append(_paper_place_order(symbol, exit_side, "TAKE_PROFIT_MARKET",
                                          quantity=quantity, stop_price=take_profit_price))
        return results

    def _paper_cancel_order(symbol, order_id):
        return _paper.cancel_order_paper(symbol, order_id)

    def _paper_cancel_all_orders(symbol):
        return _paper.cancel_all_orders_paper(symbol)

    def _paper_get_open_orders(symbol=""):
        return _paper.get_open_orders_paper(symbol)

    def _paper_countdown_cancel_all(symbol, countdown_time=1800000):
        return {"code": 200, "msg": "Paper mode: countdown ignored"}

    def _paper_set_leverage(symbol, leverage):
        return {"symbol": symbol, "leverage": leverage}

    def _paper_get_account():
        _paper.update_mark_prices(_real_get_price)
        return _paper.get_account_paper()

    def _paper_get_balance():
        return _paper.get_balance_paper()

    def _paper_get_usdt_balance():
        state = _paper.get_balance_state()
        return state["available_balance"]

    def _paper_get_positions():
        _paper.update_mark_prices(_real_get_price)
        positions = _paper.get_all_positions()
        return [p for p in positions if float(p.get("positionAmt", 0)) != 0]

    def _paper_get_position_risk(symbol=""):
        _paper.update_mark_prices(_real_get_price)
        # 先检查触发
        _paper.check_triggers(_real_get_price)
        return _paper.get_position_risk_paper(symbol)

    def _paper_get_income_history(income_type="", symbol="", start_time=0, limit=100):
        return _paper.get_income_history_paper(income_type, symbol, start_time, limit)

    def _paper_get_today_realized_pnl():
        return _paper.get_today_realized_pnl_paper()

    def _paper_get_user_trades(symbol, limit=50):
        return _paper.get_user_trades_paper(symbol, limit)

    # 覆盖写函数
    place_order = _paper_place_order
    open_long = _paper_open_long
    open_short = _paper_open_short
    close_long = _paper_close_long
    close_short = _paper_close_short
    place_stop_market = _paper_place_stop_market
    place_take_profit_market = _paper_place_take_profit_market
    place_trailing_stop = _paper_place_trailing_stop
    batch_orders = _paper_batch_orders
    open_position_with_sl_tp = _paper_open_position_with_sl_tp
    cancel_order = _paper_cancel_order
    cancel_all_orders = _paper_cancel_all_orders
    get_open_orders = _paper_get_open_orders
    countdown_cancel_all = _paper_countdown_cancel_all
    set_leverage = _paper_set_leverage
    get_account = _paper_get_account
    get_balance = _paper_get_balance
    get_usdt_balance = _paper_get_usdt_balance
    get_positions = _paper_get_positions
    get_position_risk = _paper_get_position_risk
    get_income_history = _paper_get_income_history
    get_today_realized_pnl = _paper_get_today_realized_pnl
    get_user_trades = _paper_get_user_trades


# ─── 快速测试 ─────────────────────────────────────────────

if __name__ == "__main__":
    mode = "PAPER" if PAPER_TRADING else "LIVE"
    print(f"[{mode}] BTC: ${get_price('BTCUSDT'):,.2f}")
    print(f"[{mode}] ETH: ${get_price('ETHUSDT'):,.2f}")
    print(f"[{mode}] BTC Funding: {get_funding_rate('BTCUSDT')*100:+.4f}%")
    print(f"[{mode}] USDT Balance: ${get_usdt_balance():,.2f}")
