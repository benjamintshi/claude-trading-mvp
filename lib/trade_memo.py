"""交易备忘录 — 记录每笔交易的 AI 分析思路.

每次开仓/平仓自动写入 data/trades/memo/ 目录，供复盘使用。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

DATA_DIR = Path(os.getenv("TRADE_MEMO_DIR",
    str(Path(__file__).resolve().parent.parent / "data" / "trades" / "memo")))


def record_open(symbol: str, side: str, entry: float, stop: float,
                target: float, conviction: str, regime: str,
                bull_case: str, bear_case: str, bull_score: int,
                bear_score: int, reasoning_audit: str, reason: str,
                market_snapshot: str = "", risk_usd: float = 0,
                risk_pct: float = 0, quantity: float = 0) -> str:
    """记录开仓分析思路.

    返回备忘录文件路径。
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{ts}_{symbol}_{side.upper()}_OPEN.md"
    filepath = DATA_DIR / filename

    rr = abs(target - entry) / abs(entry - stop) if abs(entry - stop) > 0 else 0
    stop_pct = abs(entry - stop) / entry * 100 if entry > 0 else 0

    content = f"""# {symbol} {side.upper()} — 开仓备忘录

**时间:** {time.strftime("%Y-%m-%d %H:%M:%S")}
**信心:** {conviction} | **市场:** {regime}

## 交易参数
| 项目 | 值 |
|------|-----|
| 入场 | ${entry:.4f} |
| 止损 | ${stop:.4f} ({stop_pct:.1f}%) |
| 目标 | ${target:.4f} |
| 赔率 | {rr:.1f}:1 |
| 数量 | {quantity:.4f} |
| 风险 | ${risk_usd:.2f} ({risk_pct:.2f}%) |

## 开仓理由
{reason}

## 牛熊辩论

### 🐂 牛方 ({bull_score}/10)
{bull_case}

### 🐻 熊方 ({bear_score}/10)
{bear_case}

### 判定
牛 {bull_score} vs 熊 {bear_score} → {"通过 (差值 > 3)" if bull_score > bear_score + 3 else "勉强通过" if bull_score > bear_score else "不应通过"}

## 推理审计
{reasoning_audit}

## 市场快照
{market_snapshot if market_snapshot else "未记录"}
"""

    with open(filepath, "w") as f:
        f.write(content)

    # 同时写入 JSON 索引
    _append_index({
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "type": "open",
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "stop": stop,
        "target": target,
        "rr_ratio": round(rr, 2),
        "conviction": conviction,
        "regime": regime,
        "bull_score": bull_score,
        "bear_score": bear_score,
        "reason": reason[:200],
        "file": filename,
    })

    return str(filepath)


def record_close(symbol: str, side: str, entry: float, exit_price: float,
                 pnl: float, pnl_pct: float, duration_hours: float,
                 reason: str, analysis: str = "",
                 lessons: str = "", market_at_close: str = "") -> str:
    """记录平仓分析思路.

    返回备忘录文件路径。
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    result = "WIN" if pnl > 0 else "LOSS"
    filename = f"{ts}_{symbol}_{side.upper()}_{result}.md"
    filepath = DATA_DIR / filename

    if duration_hours >= 24:
        duration_str = f"{duration_hours/24:.1f} 天"
    else:
        duration_str = f"{duration_hours:.1f} 小时"

    emoji = "💰" if pnl > 0 else "💸"

    content = f"""# {emoji} {symbol} {side.upper()} — 平仓备忘录 ({result})

**时间:** {time.strftime("%Y-%m-%d %H:%M:%S")}
**持仓时长:** {duration_str}

## 交易结果
| 项目 | 值 |
|------|-----|
| 入场 | ${entry:.4f} |
| 出场 | ${exit_price:.4f} |
| 盈亏 | ${pnl:+.2f} ({pnl_pct:+.1f}%) |
| 结果 | **{result}** |

## 平仓理由
{reason}

## 复盘分析
{analysis if analysis else "待补充"}

## 经验教训
{lessons if lessons else "待补充"}

## 平仓时市场状态
{market_at_close if market_at_close else "未记录"}
"""

    with open(filepath, "w") as f:
        f.write(content)

    _append_index({
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "type": "close",
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "exit": exit_price,
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "result": result.lower(),
        "duration_hours": round(duration_hours, 1),
        "reason": reason[:200],
        "file": filename,
    })

    return str(filepath)


def record_ws_decision(symbol: str, trigger_type: str, price: float,
                       bull_summary: str, bear_summary: str,
                       analyst_summary: str, decision: str,
                       detail: str = "") -> str:
    """记录 WebSocket 触发的多 Agent 决策.

    返回备忘录文件路径。
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{ts}_{symbol}_WS_{trigger_type}.md"
    filepath = DATA_DIR / filename

    content = f"""# {symbol} — WS 触发决策记录

**时间:** {time.strftime("%Y-%m-%d %H:%M:%S")}
**触发:** {trigger_type} @ ${price:.4f}
**详情:** {detail}

## 多 Agent 分析

### 🐂 Bull Agent
{bull_summary[:500] if bull_summary else "N/A"}

### 🐻 Bear Agent
{bear_summary[:500] if bear_summary else "N/A"}

### 📊 Analyst
{analyst_summary[:500] if analyst_summary else "N/A"}

## Coordinator 决策
{decision[:800] if decision else "N/A"}
"""

    with open(filepath, "w") as f:
        f.write(content)

    return str(filepath)


def get_trade_history(limit: int = 20) -> list[dict]:
    """获取最近的交易记录索引."""
    index_file = DATA_DIR / "index.json"
    if not index_file.exists():
        return []
    try:
        with open(index_file) as f:
            records = json.load(f)
        return records[-limit:]
    except Exception:
        return []


def get_summary() -> str:
    """生成交易备忘录摘要."""
    records = get_trade_history(50)
    if not records:
        return "暂无交易备忘录。"

    opens = [r for r in records if r["type"] == "open"]
    closes = [r for r in records if r["type"] == "close"]
    wins = [r for r in closes if r.get("result") == "win"]
    losses = [r for r in closes if r.get("result") == "loss"]
    total_pnl = sum(r.get("pnl", 0) for r in closes)

    lines = [
        f"## 交易备忘录摘要",
        f"- 开仓记录: {len(opens)} 笔",
        f"- 平仓记录: {len(closes)} 笔 ({len(wins)} 赢 / {len(losses)} 亏)",
        f"- 总 PnL: ${total_pnl:+.2f}",
    ]

    if closes:
        win_rate = len(wins) / len(closes) * 100
        lines.append(f"- 胜率: {win_rate:.0f}%")

    # 最近 5 笔
    lines.append(f"\n### 最近交易:")
    for r in records[-5:]:
        if r["type"] == "open":
            lines.append(f"- 📂 {r['time'][:10]} {r['symbol']} {r['side'].upper()} "
                         f"信心:{r.get('conviction','')} 牛{r.get('bull_score','')}:熊{r.get('bear_score','')}")
        else:
            emoji = "💰" if r.get("pnl", 0) > 0 else "💸"
            lines.append(f"- {emoji} {r['time'][:10]} {r['symbol']} "
                         f"${r.get('pnl',0):+.2f} ({r.get('pnl_pct',0):+.1f}%) {r.get('reason','')[:30]}")

    return "\n".join(lines)


def _append_index(record: dict):
    """追加记录到索引文件."""
    index_file = DATA_DIR / "index.json"
    records = []
    if index_file.exists():
        try:
            with open(index_file) as f:
                records = json.load(f)
        except Exception:
            pass
    records.append(record)
    # 只保留最近 200 条
    records = records[-200:]
    with open(index_file, "w") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
