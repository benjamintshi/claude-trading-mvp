"""Binance Futures API wrapper."""

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


def _sign(params: dict) -> dict:
    """Add timestamp and signature to params."""
    params["timestamp"] = int(time.time() * 1000)
    query = urllib.parse.urlencode(params)
    signature = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = signature
    return params


def _request(method, path, params=None, signed=False):
    """Make API request."""
    params = params or {}
    if signed:
        params = _sign(params)

    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(url, method=method)
    req.add_header("X-MBX-APIKEY", API_KEY)

    if method == "POST" and params:
        req = urllib.request.Request(url)
        req.add_header("X-MBX-APIKEY", API_KEY)
        data = urllib.parse.urlencode(params).encode()
        resp = urllib.request.urlopen(req, data=data, timeout=10)
    else:
        resp = urllib.request.urlopen(req, timeout=10)

    return json.loads(resp.read())


# ─── Public endpoints (no auth needed) ─────────────────────

def get_price(symbol: str) -> float:
    """Get current price."""
    data = _request("GET", "/fapi/v1/ticker/price", {"symbol": symbol})
    return float(data["price"])


def get_ticker_24h(symbol: str) -> dict:
    """Get 24h ticker stats."""
    return _request("GET", "/fapi/v1/ticker/24hr", {"symbol": symbol})


def get_funding_rate(symbol: str) -> float:
    """Get current funding rate."""
    data = _request("GET", "/fapi/v1/fundingRate", {"symbol": symbol, "limit": 1})
    return float(data[0]["fundingRate"]) if data else 0.0


def get_all_tickers() -> list:
    """Get all 24h tickers."""
    return _request("GET", "/fapi/v1/ticker/24hr")


# ─── Authenticated endpoints ───────────────────────────────

def set_leverage(symbol: str, leverage: int):
    """Set leverage for a symbol."""
    return _request("POST", "/fapi/v1/leverage",
                    {"symbol": symbol, "leverage": leverage}, signed=True)


def place_order(symbol: str, side: str, quantity: float, reduce_only: bool = False):
    """Place a MARKET order."""
    params = {
        "symbol": symbol,
        "side": side,  # "BUY" or "SELL"
        "type": "MARKET",
        "quantity": quantity,
    }
    if reduce_only:
        params["reduceOnly"] = "true"
    return _request("POST", "/fapi/v1/order", params, signed=True)


def open_long(symbol: str, quantity: float, leverage: int = 3):
    """Open a long position."""
    set_leverage(symbol, leverage)
    return place_order(symbol, "BUY", quantity)


def open_short(symbol: str, quantity: float, leverage: int = 3):
    """Open a short position."""
    set_leverage(symbol, leverage)
    return place_order(symbol, "SELL", quantity)


def close_long(symbol: str, quantity: float):
    """Close a long position (sell)."""
    return place_order(symbol, "SELL", quantity, reduce_only=True)


def close_short(symbol: str, quantity: float):
    """Close a short position (buy)."""
    return place_order(symbol, "BUY", quantity, reduce_only=True)


def get_account():
    """Get account info."""
    return _request("GET", "/fapi/v2/account", {}, signed=True)


def get_positions():
    """Get open positions from exchange."""
    account = get_account()
    return [p for p in account.get("positions", []) if float(p["positionAmt"]) != 0]


# ─── Helper ────────────────────────────────────────────────

def calc_quantity(symbol: str, capital: float, risk_pct: float, entry: float, stop: float, leverage: int = 3):
    """Calculate position size based on risk."""
    risk_amount = capital * risk_pct  # e.g., $2000 * 0.01 = $20
    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        return 0.0

    quantity = risk_amount / stop_distance
    notional = quantity * entry
    max_notional = capital * 0.05 * leverage  # 5% of capital * leverage

    if notional > max_notional:
        quantity = max_notional / entry

    return round(quantity, 3)


if __name__ == "__main__":
    # Quick test
    print(f"BTC: ${get_price('BTCUSDT'):,.2f}")
    print(f"ETH: ${get_price('ETHUSDT'):,.2f}")
    print(f"BTC Funding: {get_funding_rate('BTCUSDT')*100:+.4f}%")
