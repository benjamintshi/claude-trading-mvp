"""信号反馈回路 — 自动统计信号准确率，动态调权.

每笔交易记录各信号是否触发、交易结果，自动统计各信号胜率。
高胜率信号加权，低胜率信号降权。

数据存储: data/feedback/signal_history.json
"""

import json
import os
from pathlib import Path

DATA_DIR = Path(os.getenv("FEEDBACK_DATA_DIR", "data/feedback"))
SIGNAL_HISTORY_FILE = DATA_DIR / "signal_history.json"
SIGNAL_WEIGHTS_FILE = DATA_DIR / "signal_weights.json"

# 14 个信号的默认权重
DEFAULT_WEIGHTS = {
    "support_resistance": 2,
    "abnormal_divergence": 2,
    "oi_divergence": 2,
    "funding_rate": 1,
    "long_short_ratio": 1,
    "taker_ratio": 1,
    "rsi_extreme": 1,
    "ema_trend": 1,
    "fear_greed": 1,
    "news_catalyst": 1,
    "volume_expansion": 1,
}

MAX_WEIGHT = 3
MIN_WEIGHT = 0


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load(filepath, default):
    if filepath.exists():
        with open(filepath) as f:
            return json.load(f)
    return default


def _save(filepath, data):
    _ensure_dir()
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


def record_trade_signals(symbol: str, side: str, score: int,
                         signals_triggered: dict, result: str,
                         pnl: float = 0) -> dict:
    """记录一笔交易的信号触发情况和结果.

    signals_triggered: {"support_resistance": True, "rsi_extreme": True, ...}
    result: "win" | "loss"
    """
    history = _load(SIGNAL_HISTORY_FILE, [])

    import time
    entry = {
        "symbol": symbol,
        "side": side,
        "score": score,
        "signals": signals_triggered,
        "result": result,
        "pnl": pnl,
        "time": int(time.time() * 1000),
    }
    history.append(entry)
    _save(SIGNAL_HISTORY_FILE, history)

    # 每 10 笔自动更新权重
    if len(history) % 10 == 0:
        update_weights()

    return entry


def _time_decay_weight(entry_time_ms: int, now_ms: int,
                       half_life_days: int = 30) -> float:
    """计算时间衰减权重 — 半衰期模型.

    半衰期 30 天: 30 天前的交易权重 = 0.5, 60 天前 = 0.25。
    """
    import math
    age_days = (now_ms - entry_time_ms) / (1000 * 86400)
    if age_days <= 0:
        return 1.0
    return math.pow(0.5, age_days / half_life_days)


def get_signal_accuracy(use_decay: bool = True) -> dict:
    """计算每个信号的胜率 (支持时间衰减加权).

    返回: {"rsi_extreme": {"wins": 5, "total": 8, "win_rate": 62.5}, ...}

    use_decay=True 时，近期交易权重更高 (半衰期 30 天)。
    """
    import time as _time
    history = _load(SIGNAL_HISTORY_FILE, [])
    if not history:
        return {}

    now_ms = int(_time.time() * 1000)
    stats = {}
    for entry in history:
        w = 1.0
        if use_decay:
            w = _time_decay_weight(entry.get("time", now_ms), now_ms)

        for signal_name, triggered in entry.get("signals", {}).items():
            if not triggered:
                continue
            if signal_name not in stats:
                stats[signal_name] = {"wins": 0, "losses": 0, "total": 0,
                                      "total_pnl": 0, "weighted_wins": 0,
                                      "weighted_total": 0}
            stats[signal_name]["total"] += 1
            stats[signal_name]["total_pnl"] += entry.get("pnl", 0)
            stats[signal_name]["weighted_total"] += w
            if entry["result"] == "win":
                stats[signal_name]["wins"] += 1
                stats[signal_name]["weighted_wins"] += w
            else:
                stats[signal_name]["losses"] += 1

    for sig, s in stats.items():
        s["win_rate"] = round(s["wins"] / s["total"] * 100, 1) if s["total"] > 0 else 0
        s["avg_pnl"] = round(s["total_pnl"] / s["total"], 2) if s["total"] > 0 else 0
        # 衰减加权胜率 (用于 update_weights)
        s["decayed_win_rate"] = round(
            s["weighted_wins"] / s["weighted_total"] * 100, 1
        ) if s["weighted_total"] > 0.5 else s["win_rate"]

    return stats


def update_weights() -> dict:
    """根据信号胜率更新权重 (使用时间衰减加权).

    规则:
    - 衰减胜率 > 60% 且样本 >= 5 → 权重 +1 (最大 3)
    - 衰减胜率 < 40% 且样本 >= 5 → 权重 -1 (最小 0)
    - 样本不足 → 保持默认权重
    """
    accuracy = get_signal_accuracy(use_decay=True)
    weights = _load(SIGNAL_WEIGHTS_FILE, DEFAULT_WEIGHTS.copy())

    for signal_name, default_w in DEFAULT_WEIGHTS.items():
        if signal_name not in accuracy:
            weights[signal_name] = default_w
            continue

        stats = accuracy[signal_name]
        if stats["total"] < 5:
            # 样本不足，保持默认
            weights[signal_name] = default_w
            continue

        # 使用衰减加权胜率 — 近期交易影响更大
        wr = stats.get("decayed_win_rate", stats["win_rate"])
        if wr > 60:
            weights[signal_name] = min(MAX_WEIGHT, default_w + 1)
        elif wr < 40:
            weights[signal_name] = max(MIN_WEIGHT, default_w - 1)
        else:
            weights[signal_name] = default_w

    _save(SIGNAL_WEIGHTS_FILE, weights)
    return weights


def get_current_weights() -> dict:
    """获取当前信号权重 (含动态调整)."""
    return _load(SIGNAL_WEIGHTS_FILE, DEFAULT_WEIGHTS.copy())


def get_feedback_summary() -> str:
    """生成信号反馈摘要 — 供 trade-loop 参考."""
    history = _load(SIGNAL_HISTORY_FILE, [])
    accuracy = get_signal_accuracy()
    weights = get_current_weights()

    total = len(history)
    if total == 0:
        return "暂无交易记录，使用默认信号权重。"

    wins = sum(1 for h in history if h["result"] == "win")
    overall_wr = wins / total * 100 if total > 0 else 0

    lines = [f"交易记录: {total} 笔 | 总胜率: {overall_wr:.0f}%", ""]

    # 按胜率排序的信号
    if accuracy:
        lines.append("信号胜率 (样本>=3):")
        sorted_sigs = sorted(accuracy.items(), key=lambda x: x[1]["win_rate"], reverse=True)
        for sig, stats in sorted_sigs:
            if stats["total"] >= 3:
                w = weights.get(sig, "?")
                arrow = "^" if w > DEFAULT_WEIGHTS.get(sig, 1) else ("v" if w < DEFAULT_WEIGHTS.get(sig, 1) else "=")
                lines.append(f"  {sig}: {stats['win_rate']:.0f}% ({stats['total']}笔) 权重:{w}{arrow}")

    # 权重变化提示
    changed = [(k, v) for k, v in weights.items() if v != DEFAULT_WEIGHTS.get(k, 1)]
    if changed:
        lines.append("")
        lines.append("权重已调整:")
        for k, v in changed:
            default = DEFAULT_WEIGHTS.get(k, 1)
            lines.append(f"  {k}: {default} → {v}")

    return "\n".join(lines)
