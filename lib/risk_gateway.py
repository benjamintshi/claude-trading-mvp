"""风控网关 — 所有确定性风控检查的代码化.

AI 提交开仓请求时自动运行，不通过就拦截。
不需要 AI 判断力的规则全部在这里，硬编码执行。

用法:
    from lib.risk_gateway import pre_trade_check, get_system_status

    # 开仓前一键检查
    result = pre_trade_check(symbol, side, entry, stop, target)
    if not result["pass"]:
        print(result["reason"])  # 被拦截的原因

    # 获取系统状态 (regime + 熔断 + 持仓概览)
    status = get_system_status()
"""

from __future__ import annotations

import os
import time

# ─── 常量 ────────────────────────────────────────────────

CAPITAL = float(os.getenv("PAPER_INITIAL_BALANCE", "2000"))
LEVERAGE = 3
MAX_POSITIONS = 5
MAX_SAME_DIRECTION = 3
MAX_DAILY_LOSS = -100.0       # 日亏熔断
MIN_BALANCE = 500.0           # 余额熔断
MAX_MARGIN_RATIO = 0.50       # 保证金率熔断
EMERGENCY_MARGIN_RATIO = 0.80
MIN_RR_RATIO = 3.0            # 最低赔率 (1:3)
STOP_PCT_RANGE = (0.005, 0.05)  # 止损幅度 0.5%-5%
RISK_PCT_RANGE = (0.0025, 0.015)  # 风险比例 0.25%-1.5%
CONSECUTIVE_LOSS_DOWNGRADE = 3
CONSECUTIVE_LOSS_BREAKER = 5


# ─── 市场状态 (Regime) ──────────────────────────────────

def detect_regime() -> dict:
    """识别当前市场状态 — 纯代码，4 种状态."""
    from lib.binance import get_klines, detect_regime as _detect
    try:
        klines = get_klines("BTCUSDT", "1h", 100)
        return _detect(klines)
    except Exception:
        return {
            "regime": "unknown", "regime_cn": "未知",
            "volatility": "unknown", "trend": "unknown",
            "score_threshold_adj": 0, "risk_multiplier": 1.0,
            "strategy_hint": "无法获取市场数据",
        }


# ─── 熔断器 ────────────────────────────────────────────

def check_circuit_breaker() -> dict:
    """熔断器检查 — 返回 {status, level, reasons}.

    level: "normal" / "downgrade" / "breaker" / "emergency"
    """
    from lib.binance import get_today_realized_pnl, get_usdt_balance, get_account, get_user_trades

    reasons = []
    level = "normal"

    # 1. 日亏
    try:
        daily_pnl = get_today_realized_pnl()
        if daily_pnl < MAX_DAILY_LOSS:
            reasons.append(f"日亏 ${daily_pnl:.2f} 超过限额 ${MAX_DAILY_LOSS}")
            level = "breaker"
    except Exception:
        pass

    # 2. 余额
    try:
        balance = get_usdt_balance()
        if balance < MIN_BALANCE:
            reasons.append(f"余额 ${balance:.2f} 低于安全线 ${MIN_BALANCE}")
            level = "breaker"
    except Exception:
        pass

    # 3. 保证金率
    try:
        account = get_account()
        total_margin = float(account.get("totalMaintMargin", 0))
        total_balance = float(account.get("totalMarginBalance", 1))
        margin_ratio = total_margin / total_balance if total_balance > 0 else 0
        if margin_ratio > EMERGENCY_MARGIN_RATIO:
            reasons.append(f"保证金率 {margin_ratio:.0%} 超过紧急线 {EMERGENCY_MARGIN_RATIO:.0%}")
            level = "emergency"
        elif margin_ratio > MAX_MARGIN_RATIO:
            reasons.append(f"保证金率 {margin_ratio:.0%} 超过警戒线 {MAX_MARGIN_RATIO:.0%}")
            level = "breaker"
    except Exception:
        pass

    # 4. 连续亏损
    try:
        # 取最近 5 笔平仓记录
        trades = get_user_trades("", limit=10)  # 跨币种
        # Paper 模式下用文件
        if os.getenv("PAPER_TRADING", "").lower() in ("true", "1", "yes"):
            from lib.paper import _load_paper_data
            paper_trades = _load_paper_data("trades", [])
            recent = paper_trades[-5:] if paper_trades else []
            consecutive_losses = 0
            for t in reversed(recent):
                if t.get("pnl", 0) < 0:
                    consecutive_losses += 1
                else:
                    break
            if consecutive_losses >= CONSECUTIVE_LOSS_BREAKER:
                reasons.append(f"连续 {consecutive_losses} 笔亏损")
                level = max(level, "breaker", key=["normal", "downgrade", "breaker", "emergency"].index)
            elif consecutive_losses >= CONSECUTIVE_LOSS_DOWNGRADE:
                reasons.append(f"连续 {consecutive_losses} 笔亏损，仓位减半")
                if level == "normal":
                    level = "downgrade"
    except Exception:
        pass

    return {
        "pass": level in ("normal", "downgrade"),
        "level": level,
        "reasons": reasons,
        "can_trade": level in ("normal", "downgrade"),
        "size_multiplier": 0.5 if level == "downgrade" else 1.0,
    }


# ─── 持仓检查 ──────────────────────────────────────────

def check_positions(symbol: str, side: str) -> dict:
    """检查持仓数量限制和重复仓位."""
    from lib.binance import get_position_risk

    try:
        positions = get_position_risk()
        active = [p for p in positions if float(p.get("positionAmt", 0)) != 0]
    except Exception:
        return {"pass": True, "reasons": [], "active_count": 0}

    reasons = []
    active_count = len(active)

    # 总持仓数
    if active_count >= MAX_POSITIONS:
        reasons.append(f"持仓数 {active_count} 已达上限 {MAX_POSITIONS}")

    # 同方向持仓数
    same_dir = sum(1 for p in active
                   if (side == "long" and float(p["positionAmt"]) > 0) or
                      (side == "short" and float(p["positionAmt"]) < 0))
    if same_dir >= MAX_SAME_DIRECTION:
        reasons.append(f"同方向({side})持仓 {same_dir} 已达上限 {MAX_SAME_DIRECTION}")

    # 重复仓位
    for p in active:
        if p["symbol"] == symbol:
            existing_side = "long" if float(p["positionAmt"]) > 0 else "short"
            if existing_side == side:
                reasons.append(f"{symbol} 已有同方向({side})仓位")

    return {
        "pass": len(reasons) == 0,
        "reasons": reasons,
        "active_count": active_count,
        "active_positions": active,
    }


# ─── 交易参数检查 ──────────────────────────────────────

def check_trade_params(entry: float, stop: float, target: float) -> dict:
    """检查赔率和止损幅度."""
    reasons = []

    if entry <= 0 or stop <= 0 or target <= 0:
        return {"pass": False, "reasons": ["价格参数无效"]}

    # 赔率
    risk = abs(entry - stop)
    reward = abs(target - entry)
    rr_ratio = reward / risk if risk > 0 else 0
    if rr_ratio < MIN_RR_RATIO:
        reasons.append(f"赔率 {rr_ratio:.2f}:1 低于最低要求 {MIN_RR_RATIO}:1")

    # 止损幅度
    stop_pct = risk / entry
    if stop_pct < STOP_PCT_RANGE[0]:
        reasons.append(f"止损幅度 {stop_pct:.2%} 太窄 (最低 {STOP_PCT_RANGE[0]:.1%})")
    if stop_pct > STOP_PCT_RANGE[1]:
        reasons.append(f"止损幅度 {stop_pct:.2%} 太宽 (最高 {STOP_PCT_RANGE[1]:.1%})")

    return {
        "pass": len(reasons) == 0,
        "reasons": reasons,
        "rr_ratio": round(rr_ratio, 2),
        "stop_pct": round(stop_pct * 100, 2),
    }


# ─── 余额检查 ──────────────────────────────────────────

def check_balance(entry: float, stop: float, risk_pct: float) -> dict:
    """检查余额是否足够."""
    from lib.binance import get_usdt_balance

    try:
        balance = get_usdt_balance()
    except Exception:
        return {"pass": True, "reasons": [], "balance": 0}

    risk_amount = balance * risk_pct
    risk_distance = abs(entry - stop)
    if risk_distance <= 0:
        return {"pass": False, "reasons": ["止损距离为 0"]}

    quantity = risk_amount / risk_distance
    notional = quantity * entry
    required_margin = notional / LEVERAGE

    reasons = []
    if required_margin > balance * 0.9:  # 留 10% 安全边际
        reasons.append(f"保证金 ${required_margin:.2f} 超过可用余额 ${balance:.2f}")

    return {
        "pass": len(reasons) == 0,
        "reasons": reasons,
        "balance": round(balance, 2),
        "required_margin": round(required_margin, 2),
    }


# ─── 相关性检查 ──────────────────────────────────────────

def check_correlation(symbol: str) -> dict:
    """检查与现有持仓的相关性."""
    from lib.binance import get_position_risk, check_correlation as _check_corr

    try:
        positions = get_position_risk()
        active_symbols = [p["symbol"] for p in positions
                         if float(p.get("positionAmt", 0)) != 0]
    except Exception:
        return {"pass": True, "max_corr": 0, "penalty": 1.0, "details": {}}

    if not active_symbols or symbol in active_symbols:
        return {"pass": True, "max_corr": 0, "penalty": 1.0, "details": {}}

    try:
        all_symbols = active_symbols + [symbol]
        corr_result = _check_corr(all_symbols)
        pairs = corr_result.get("pairs", {})

        max_corr = 0
        details = {}
        for pair_key, corr_val in pairs.items():
            if symbol in pair_key:
                details[pair_key] = round(corr_val, 3)
                max_corr = max(max_corr, abs(corr_val))
    except Exception:
        return {"pass": True, "max_corr": 0, "penalty": 1.0, "details": {}}

    penalty = 1.0
    warning = ""
    if max_corr > 0.9:
        penalty = 0.25
        warning = f"与现有持仓相关性 {max_corr:.2f} 极高，建议放弃"
    elif max_corr > 0.7:
        penalty = 0.5
        warning = f"与现有持仓相关性 {max_corr:.2f}，仓位减半"

    return {
        "pass": True,  # 相关性是软门槛，不硬拦
        "max_corr": round(max_corr, 3),
        "penalty": penalty,
        "warning": warning,
        "details": details,
    }


# ─── 仓位计算 ──────────────────────────────────────────

def calc_position_size(entry: float, stop: float, regime: dict,
                       correlation_penalty: float = 1.0,
                       breaker_multiplier: float = 1.0,
                       conviction: str = "standard") -> dict:
    """计算仓位大小.

    conviction: "high" / "standard" / "probe" — AI 的信心水平
    """
    from lib.binance import get_usdt_balance

    # conviction → 基础风险比例
    base_risk = {
        "high": 0.015,      # 1.5%
        "standard": 0.010,  # 1.0%
        "probe": 0.005,     # 0.5%
    }.get(conviction, 0.01)

    # regime 乘数
    regime_mult = regime.get("risk_multiplier", 1.0)

    # 最终风险比例
    risk_pct = base_risk * regime_mult * correlation_penalty * breaker_multiplier
    risk_pct = max(RISK_PCT_RANGE[0], min(RISK_PCT_RANGE[1], risk_pct))

    try:
        balance = get_usdt_balance()
    except Exception:
        balance = CAPITAL

    risk_amount = balance * risk_pct
    risk_distance = abs(entry - stop)
    if risk_distance <= 0:
        return {"quantity": 0, "notional": 0, "risk_pct": 0, "risk_usd": 0}

    quantity = risk_amount / risk_distance
    notional = quantity * entry

    # 硬上限: 单仓名义价值不超过资本的 15% (3x 杠杆下)
    max_notional = balance * 0.15 * LEVERAGE
    if notional > max_notional:
        quantity = max_notional / entry
        notional = quantity * entry

    return {
        "quantity": quantity,
        "notional": round(notional, 2),
        "risk_pct": round(risk_pct * 100, 3),
        "risk_usd": round(quantity * risk_distance, 2),
        "balance": round(balance, 2),
    }


# ─── 一键检查 ──────────────────────────────────────────

def pre_trade_check(symbol: str, side: str, entry: float,
                    stop: float, target: float) -> dict:
    """开仓前一键风控检查 — 所有确定性规则.

    返回:
        {
            "pass": bool,           # 是否通过全部硬检查
            "reason": str,          # 未通过的原因 (可直接展示给 AI)
            "regime": dict,         # 市场状态
            "correlation": dict,    # 相关性信息
            "position_size": dict,  # 推荐仓位
            "details": dict,        # 各项检查的详细结果
        }
    """
    results = {}
    blocked_reasons = []

    # 1. 熔断器
    breaker = check_circuit_breaker()
    results["circuit_breaker"] = breaker
    if not breaker["can_trade"]:
        blocked_reasons.append(f"熔断: {'; '.join(breaker['reasons'])}")

    # 2. 持仓限制
    pos_check = check_positions(symbol, side)
    results["positions"] = pos_check
    if not pos_check["pass"]:
        blocked_reasons.extend(pos_check["reasons"])

    # 3. 交易参数
    param_check = check_trade_params(entry, stop, target)
    results["params"] = param_check
    if not param_check["pass"]:
        blocked_reasons.extend(param_check["reasons"])

    # 4. 市场状态
    regime = detect_regime()
    results["regime"] = regime

    # 5. 相关性
    corr = check_correlation(symbol)
    results["correlation"] = corr

    # 6. 仓位计算 (即使检查未通过也算，供 AI 参考)
    position_size = calc_position_size(
        entry, stop, regime,
        correlation_penalty=corr["penalty"],
        breaker_multiplier=breaker["size_multiplier"],
    )
    results["position_size"] = position_size

    # 7. 余额检查
    balance_check = check_balance(entry, stop, position_size["risk_pct"] / 100)
    results["balance"] = balance_check
    if not balance_check["pass"]:
        blocked_reasons.extend(balance_check["reasons"])

    passed = len(blocked_reasons) == 0
    reason = ""
    if not passed:
        reason = "风控拦截:\n" + "\n".join(f"  ❌ {r}" for r in blocked_reasons)

    return {
        "pass": passed,
        "reason": reason,
        "regime": regime,
        "correlation": corr,
        "position_size": position_size,
        "details": results,
    }


# ─── 系统状态概览 ──────────────────────────────────────

def get_system_status() -> str:
    """获取系统状态概览 — 供 AI 在 scan/trade-loop 开头使用."""
    regime = detect_regime()
    breaker = check_circuit_breaker()

    lines = [
        f"## 系统状态",
        f"- 市场: {regime['regime_cn']} (波动率:{regime['volatility']} 趋势:{regime['trend']})",
        f"- 策略建议: {regime['strategy_hint']}",
        f"- 仓位乘数: {regime['risk_multiplier']}x",
    ]

    if breaker["level"] != "normal":
        lines.append(f"- ⚠️ 熔断状态: {breaker['level'].upper()}")
        for r in breaker["reasons"]:
            lines.append(f"  - {r}")
    else:
        lines.append(f"- 熔断: 🟢 正常")

    try:
        from lib.binance import get_position_risk
        positions = get_position_risk()
        active = [p for p in positions if float(p.get("positionAmt", 0)) != 0]
        lines.append(f"- 持仓: {len(active)}/{MAX_POSITIONS}")
    except Exception:
        pass

    return "\n".join(lines)


# ─── 格式化输出 (供 AI prompt 使用) ──────────────────────

def format_check_result(result: dict) -> str:
    """把 pre_trade_check 结果格式化为 AI 可读的文本."""
    lines = []

    if result["pass"]:
        lines.append("✅ 风控检查全部通过")
    else:
        lines.append(result["reason"])

    regime = result["regime"]
    lines.append(f"\n市场状态: {regime['regime_cn']} | 仓位乘数: {regime['risk_multiplier']}x")

    corr = result["correlation"]
    if corr.get("warning"):
        lines.append(f"相关性: {corr['warning']}")

    ps = result["position_size"]
    lines.append(f"建议仓位: {ps['quantity']:.4f} (名义 ${ps['notional']:.2f}, 风险 ${ps['risk_usd']:.2f} = {ps['risk_pct']:.2f}%)")

    return "\n".join(lines)
