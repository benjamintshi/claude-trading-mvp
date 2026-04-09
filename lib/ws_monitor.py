"""WebSocket 实时价格监控 — 价格接近关键位时触发 AI 评估.

架构:
  Binance WS (ccxt.pro)  →  触发引擎  →  AI 评估  →  执行决策
  实时 markPrice @1s        5 种触发区      claude -p     smart-exit

触发区域:
  1. near_stop     — 距止损 < 1.5% → AI 评估是否提前平仓
  2. near_tp       — 距止盈 < 2%   → AI 评估是否让利润跑
  3. near_support  — 距支撑 < 1%   → AI 评估支撑有效性 (多仓)
  4. near_resistance — 距阻力 < 1% → AI 评估阻力有效性 (空仓)
  5. atr_breakout  — 5min 变动 > 1.5 ATR → AI 评估突破有效性
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


# ─── 数据结构 ────────────────────────────────────────────

@dataclass
class WatchConfig:
    """每个持仓的监控配置."""
    symbol: str
    side: str                   # "long" | "short"
    entry_price: float
    stop_price: float
    take_profit_price: float
    atr: float
    supports: list = field(default_factory=list)    # 支撑位 (最多 3 个)
    resistances: list = field(default_factory=list)  # 阻力位 (最多 3 个)


@dataclass
class TriggerEvent:
    """触发事件."""
    symbol: str
    trigger_type: str           # near_stop / near_tp / near_support / near_resistance / atr_breakout
    current_price: float
    threshold_price: float
    distance_pct: float         # 距离百分比
    urgency: str                # critical / high / medium
    timestamp: float = field(default_factory=time.time)
    detail: str = ""


# ─── 触发条件配置 ────────────────────────────────────────

TRIGGER_THRESHOLDS = {
    "near_stop": {"distance_pct": 0.015, "urgency": "critical"},     # 1.5%
    "near_tp": {"distance_pct": 0.02, "urgency": "high"},            # 2%
    "near_support": {"distance_pct": 0.01, "urgency": "medium"},     # 1%
    "near_resistance": {"distance_pct": 0.01, "urgency": "medium"},  # 1%
    "atr_breakout": {"atr_mult": 1.5, "urgency": "high"},            # 1.5x ATR in 5min
}


# ─── 冷却管理器 ──────────────────────────────────────────

class CooldownManager:
    """防止同一触发条件重复触发 AI."""

    # 各触发类型的基础冷却时间 (秒)
    COOLDOWN_SECONDS = {
        "near_stop": 300,        # 5 分钟
        "near_tp": 600,          # 10 分钟
        "near_support": 900,     # 15 分钟
        "near_resistance": 900,  # 15 分钟
        "atr_breakout": 600,     # 10 分钟
    }

    # 同一 symbol 的全局冷却
    GLOBAL_SYMBOL_COOLDOWN = 180  # 3 分钟

    # 每小时最大 AI 调用次数
    MAX_HOURLY_CALLS = 6

    # Regime 自适应冷却乘数
    REGIME_COOLDOWN_MULTIPLIER = {
        "高波趋势": 0.6,      # 高波动 → 缩短冷却 (更灵敏)
        "高波震荡": 0.5,      # 最高波动 → 最短冷却
        "低波趋势": 1.0,      # 正常
        "低波震荡": 1.2,      # 低波动 → 延长冷却 (减少噪音)
    }

    def __init__(self):
        self._last_trigger: dict[tuple[str, str], float] = {}  # (symbol, type) → timestamp
        self._last_symbol_trigger: dict[str, float] = {}       # symbol → timestamp
        self._hourly_calls: deque = deque()                    # timestamps of recent calls
        self._regime: str = ""                                 # 当前市场状态

    def set_regime(self, regime_cn: str):
        """设置当前市场状态，影响冷却时间."""
        self._regime = regime_cn

    def _get_cooldown(self, trigger_type: str) -> float:
        """获取当前冷却时间 (考虑 regime 乘数)."""
        base = self.COOLDOWN_SECONDS.get(trigger_type, 600)
        mult = self.REGIME_COOLDOWN_MULTIPLIER.get(self._regime, 1.0)
        return base * mult

    def can_trigger(self, symbol: str, trigger_type: str) -> bool:
        """检查是否可以触发 (未在冷却期内)."""
        now = time.time()

        # 1. 每小时限额
        self._cleanup_hourly(now)
        if len(self._hourly_calls) >= self.MAX_HOURLY_CALLS:
            return False

        # 2. 全局 symbol 冷却
        last_sym = self._last_symbol_trigger.get(symbol, 0)
        if now - last_sym < self.GLOBAL_SYMBOL_COOLDOWN:
            return False

        # 3. 特定触发类型冷却 (regime 自适应)
        key = (symbol, trigger_type)
        last = self._last_trigger.get(key, 0)
        cooldown = self._get_cooldown(trigger_type)
        if now - last < cooldown:
            return False

        return True

    def record_trigger(self, symbol: str, trigger_type: str):
        """记录一次触发."""
        now = time.time()
        self._last_trigger[(symbol, trigger_type)] = now
        self._last_symbol_trigger[symbol] = now
        self._hourly_calls.append(now)

    def _cleanup_hourly(self, now: float):
        """清理超过 1 小时的调用记录."""
        while self._hourly_calls and now - self._hourly_calls[0] > 3600:
            self._hourly_calls.popleft()

    def get_remaining_cooldown(self, symbol: str, trigger_type: str) -> float:
        """获取剩余冷却时间 (秒)."""
        now = time.time()
        key = (symbol, trigger_type)
        last = self._last_trigger.get(key, 0)
        cooldown = self._get_cooldown(trigger_type)
        remaining = cooldown - (now - last)
        return max(0, remaining)

    def get_hourly_remaining(self) -> int:
        """获取本小时剩余可调用次数."""
        self._cleanup_hourly(time.time())
        return max(0, self.MAX_HOURLY_CALLS - len(self._hourly_calls))


# ─── 触发引擎 ────────────────────────────────────────────

class TriggerEngine:
    """检测价格是否进入触发区域."""

    def __init__(self):
        self.cooldown = CooldownManager()
        # 价格历史: symbol → deque of (timestamp, price), 最多保留 5 分钟
        self.price_history: dict[str, deque] = {}

    def on_price_update(self, symbol: str, price: float, timestamp: float = None):
        """记录价格更新到历史缓冲."""
        ts = timestamp or time.time()
        if symbol not in self.price_history:
            self.price_history[symbol] = deque(maxlen=600)  # 10 分钟 @1s
        self.price_history[symbol].append((ts, price))

    def check_triggers(self, symbol: str, price: float,
                       config: WatchConfig) -> list[TriggerEvent]:
        """检查价格是否触发任何警戒区域.

        返回可触发的事件列表 (已过冷却期的)。
        """
        events = []

        # 1. 距止损
        if config.stop_price > 0:
            stop_dist = abs(price - config.stop_price) / price
            threshold = TRIGGER_THRESHOLDS["near_stop"]["distance_pct"]

            # 只检测价格朝止损方向移动的情况
            approaching_stop = (
                (config.side == "long" and price < config.entry_price and price - config.stop_price > 0) or
                (config.side == "short" and price > config.entry_price and config.stop_price - price > 0)
            )

            if stop_dist < threshold and approaching_stop:
                if self.cooldown.can_trigger(symbol, "near_stop"):
                    events.append(TriggerEvent(
                        symbol=symbol, trigger_type="near_stop",
                        current_price=price, threshold_price=config.stop_price,
                        distance_pct=stop_dist * 100,
                        urgency="critical",
                        detail=f"价格距止损仅 {stop_dist*100:.2f}%",
                    ))

        # 2. 距止盈
        if config.take_profit_price > 0:
            tp_dist = abs(price - config.take_profit_price) / price
            threshold = TRIGGER_THRESHOLDS["near_tp"]["distance_pct"]

            # 检测价格朝止盈方向移动
            approaching_tp = (
                (config.side == "long" and price > config.entry_price and config.take_profit_price - price > 0) or
                (config.side == "short" and price < config.entry_price and price - config.take_profit_price > 0)
            )

            if tp_dist < threshold and approaching_tp:
                if self.cooldown.can_trigger(symbol, "near_tp"):
                    events.append(TriggerEvent(
                        symbol=symbol, trigger_type="near_tp",
                        current_price=price, threshold_price=config.take_profit_price,
                        distance_pct=tp_dist * 100,
                        urgency="high",
                        detail=f"价格距止盈仅 {tp_dist*100:.2f}%，考虑让利润奔跑",
                    ))

        # 3. 距支撑位 (多仓关注)
        if config.side == "long" and config.supports:
            for level in config.supports[:3]:
                if level <= 0:
                    continue
                dist = abs(price - level) / price
                threshold = TRIGGER_THRESHOLDS["near_support"]["distance_pct"]
                if dist < threshold and price > level:
                    if self.cooldown.can_trigger(symbol, "near_support"):
                        events.append(TriggerEvent(
                            symbol=symbol, trigger_type="near_support",
                            current_price=price, threshold_price=level,
                            distance_pct=dist * 100,
                            urgency="medium",
                            detail=f"多仓价格接近支撑 ${level:.2f}",
                        ))
                    break  # 只触发最近的支撑

        # 4. 距阻力位 (空仓关注)
        if config.side == "short" and config.resistances:
            for level in config.resistances[:3]:
                if level <= 0:
                    continue
                dist = abs(price - level) / price
                threshold = TRIGGER_THRESHOLDS["near_resistance"]["distance_pct"]
                if dist < threshold and price < level:
                    if self.cooldown.can_trigger(symbol, "near_resistance"):
                        events.append(TriggerEvent(
                            symbol=symbol, trigger_type="near_resistance",
                            current_price=price, threshold_price=level,
                            distance_pct=dist * 100,
                            urgency="medium",
                            detail=f"空仓价格接近阻力 ${level:.2f}",
                        ))
                    break

        # 5. ATR 突破 (5 分钟内大幅变动)
        if config.atr > 0 and symbol in self.price_history:
            history = self.price_history[symbol]
            now = time.time()
            # 找 5 分钟前的价格
            price_5m_ago = None
            for ts, p in history:
                if now - ts <= 300:  # 5 分钟内
                    price_5m_ago = p
                    break

            if price_5m_ago is not None:
                delta = abs(price - price_5m_ago)
                atr_mult = TRIGGER_THRESHOLDS["atr_breakout"]["atr_mult"]
                if delta > atr_mult * config.atr:
                    if self.cooldown.can_trigger(symbol, "atr_breakout"):
                        direction = "上" if price > price_5m_ago else "下"
                        events.append(TriggerEvent(
                            symbol=symbol, trigger_type="atr_breakout",
                            current_price=price, threshold_price=price_5m_ago,
                            distance_pct=delta / config.atr * 100,
                            urgency="high",
                            detail=f"5分钟{direction}突 {delta/config.atr:.1f}x ATR",
                        ))

        return events

    def record_triggers(self, events: list[TriggerEvent]):
        """记录触发事件到冷却管理器."""
        for e in events:
            self.cooldown.record_trigger(e.symbol, e.trigger_type)


# ─── AI 评估 Prompt 生成 ────────────────────────────────

TRIGGER_TYPE_CN = {
    "near_stop": "⚠️ 接近止损",
    "near_tp": "🎯 接近止盈",
    "near_support": "📉 接近支撑",
    "near_resistance": "📈 接近阻力",
    "atr_breakout": "⚡ ATR 突破",
}


def build_eval_prompt(event: TriggerEvent, config: WatchConfig,
                      regime: str = "") -> str:
    """构建 AI 评估的 prompt.

    regime: 当前市场状态描述 (可选, 由 ws_runner 传入)
    """
    # 计算浮盈
    if config.side == "long":
        pnl_pct = (event.current_price - config.entry_price) / config.entry_price * 100
    else:
        pnl_pct = (config.entry_price - event.current_price) / config.entry_price * 100

    trigger_cn = TRIGGER_TYPE_CN.get(event.trigger_type, event.trigger_type)

    regime_line = f"\n- 市场状态: {regime}" if regime else ""

    return f"""WebSocket 实时监控触发 AI 评估。

## 触发信息
- 类型: {trigger_cn}
- {event.detail}
- 紧急度: {event.urgency}

## 持仓信息
- 标的: {config.symbol} {config.side.upper()}
- 入场: ${config.entry_price:.4f}
- 当前: ${event.current_price:.4f} ({pnl_pct:+.2f}%)
- 止损: ${config.stop_price:.4f}
- 止盈: ${config.take_profit_price:.4f}
- ATR: ${config.atr:.4f}{regime_line}

## 决策
获取最新市场数据 (RSI/MACD/OI/多空比) 后，从以下选项中选一个执行:

1. **HOLD** — 继续持有，不调整
2. **ADJUST_STOP** — 移动止损到新位置 (说明价位和理由)
3. **PARTIAL_CLOSE** — 部分平仓 (说明比例，如 50%)
4. **FULL_CLOSE** — 全部平仓 (说明理由)
5. **LET_RUN** — 撤止盈，启用追踪止损让利润奔跑

必须说明理由。如果数据不支持行动，选 HOLD。
高波动状态下: 优先保护利润 (ADJUST_STOP/PARTIAL_CLOSE)，追踪止损回调率 2%。
低波动状态下: 可更耐心持有，追踪止损回调率 1%。
"""


# ─── 多 Agent Prompt 模板 ──────────────────────────────────

def _build_base_context(event: TriggerEvent, config: WatchConfig,
                        regime: str = "", snapshot: str = "") -> str:
    """构建各 Agent 共享的基础上下文."""
    if config.side == "long":
        pnl_pct = (event.current_price - config.entry_price) / config.entry_price * 100
    else:
        pnl_pct = (config.entry_price - event.current_price) / config.entry_price * 100

    trigger_cn = TRIGGER_TYPE_CN.get(event.trigger_type, event.trigger_type)
    regime_line = f"\n- 市场状态: {regime}" if regime else ""

    return f"""## 触发信息
- 类型: {trigger_cn}
- {event.detail}
- 紧急度: {event.urgency}

## 持仓信息
- 标的: {config.symbol} {config.side.upper()}
- 入场: ${config.entry_price:.4f}
- 当前: ${event.current_price:.4f} ({pnl_pct:+.2f}%)
- 止损: ${config.stop_price:.4f}
- 止盈: ${config.take_profit_price:.4f}
- ATR: ${config.atr:.4f}{regime_line}
{snapshot}"""


def build_agent_prompts(event: TriggerEvent, config: WatchConfig,
                        regime: str = "", snapshot: str = "") -> dict[str, str]:
    """构建 3 个并行 Agent 的 prompt.

    返回 {"bull": ..., "bear": ..., "analyst": ...}
    """
    base = _build_base_context(event, config, regime, snapshot)

    return {
        "bull": f"""你是 Bull Agent (多头分析师)。只分析支持持有/加仓的理由。
不要调用任何工具，数据已全部提供。

{base}

任务: 列出 3-5 个支持继续持有或让利润奔跑的论据:
- 技术面支持 (RSI/EMA/MACD 方向)
- 市场微观结构 (funding/多空比/taker 买卖比)
- 关键支撑位和价格行为
- 趋势延续的证据

输出纯分析，不做最终决策。200 字以内。""",

        "bear": f"""你是 Bear Agent (空头分析师)。只分析支持平仓/减仓的理由。
不要调用任何工具，数据已全部提供。

{base}

任务: 列出 3-5 个支持平仓或减仓的论据:
- 技术面风险 (RSI 超买超卖/MACD 背离/布林带收窄)
- 市场微观结构风险 (funding 拥挤/多空比极端)
- 关键阻力位和价格行为
- 趋势反转或动量衰竭的信号

输出纯分析，不做最终决策。200 字以内。""",

        "analyst": f"""你是 Neutral Analyst (中立技术分析师)。客观评估，不偏多不偏空。
不要调用任何工具，数据已全部提供。

{base}

任务: 客观评估:
1. 当前趋势方向和强度 (多头/空头/震荡)
2. 最近的支撑位和阻力位
3. 动量分析 (RSI 位置 + MACD 方向 + 量能)
4. 波动率评估 (ATR + 布林带宽度)
5. 概率判断: 未来 1-4 小时价格更可能向哪个方向

输出纯分析，不做最终决策。200 字以内。""",
    }


def build_coordinator_prompt(event: TriggerEvent, config: WatchConfig,
                             regime: str, snapshot: str,
                             bull: str, bear: str, analyst: str) -> str:
    """构建 Coordinator 的汇总决策 prompt."""
    if config.side == "long":
        pnl_pct = (event.current_price - config.entry_price) / config.entry_price * 100
    else:
        pnl_pct = (config.entry_price - event.current_price) / config.entry_price * 100

    trigger_cn = TRIGGER_TYPE_CN.get(event.trigger_type, event.trigger_type)
    regime_line = f"\n- 市场状态: {regime}" if regime else ""

    return f"""你是 Coordinator (交易决策协调者)。3 位专家已并行完成分析，你负责汇总并做最终决策。

## 触发信息
- 类型: {trigger_cn}
- {event.detail}
- 紧急度: {event.urgency}

## 持仓信息
- 标的: {config.symbol} {config.side.upper()}
- 入场: ${config.entry_price:.4f}
- 当前: ${event.current_price:.4f} ({pnl_pct:+.2f}%)
- 止损: ${config.stop_price:.4f}
- 止盈: ${config.take_profit_price:.4f}
- ATR: ${config.atr:.4f}{regime_line}
{snapshot}

## 🐂 Bull Agent 观点
{bull}

## 🐻 Bear Agent 观点
{bear}

## 📊 Neutral Analyst 观点
{analyst}

## 你的任务
综合以上三方观点，做出最终决策。规则:
- 如果 Bear 论据明显强于 Bull → 倾向 PARTIAL_CLOSE 或 FULL_CLOSE
- 如果 Bull 论据明显强于 Bear → 倾向 HOLD 或 LET_RUN
- 如果势均力敌 → 倾向 HOLD 或 ADJUST_STOP (保守)
- Analyst 的趋势/概率判断作为 tiebreaker
- 紧急度 critical 时偏向保护资金

从以下选项中选一个执行:
1. **HOLD** — 继续持有，不调整
2. **ADJUST_STOP** — 移动止损到新位置 (说明价位和理由)
3. **PARTIAL_CLOSE** — 部分平仓 (说明比例)
4. **FULL_CLOSE** — 全部平仓
5. **LET_RUN** — 撤止盈，启用追踪止损

先用 1 句话总结三方核心分歧，再给出决策和理由。"""
