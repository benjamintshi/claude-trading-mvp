---
name: skill-router
description: >-
  Use at the start of EVERY conversation and before EVERY response. Establishes
  how to discover and invoke skills. If there is even a 1% chance a skill applies,
  you MUST invoke it before responding.
---

# Skill Router — 技能自动发现与强制调用

<SUBAGENT-STOP>
如果你是被派发的子代理执行特定任务，跳过此 skill。
</SUBAGENT-STOP>

## 架构原则

**代码做风控，AI 做判断。**

- 风控规则 (risk_gateway.py) → 代码自动执行，不需要 AI
- 止损管理 (position_manager.py) → 代码自动执行，不需要 AI
- 市场判断、开仓决策、平仓时机 → AI 的工作

## 路由决策

| 用户意图 | 对应 Command / Skill |
|----------|---------------------|
| **交易操作** | |
| 扫描市场/找机会 | `/scan` — AI 直接看原始数据判断 |
| 开仓交易 | `/open` — 代码风控 → AI 牛熊辩论 + 推理审计 → 执行 |
| 平仓交易 | `/close` — 平仓 + `trade-journal` 复盘 |
| 查看持仓 | `/positions` |
| 完整交易循环 | `/trade-loop` — 代码风控+止损管理 → AI 扫描+判断 |
| **AI Skills (需要判断力)** | |
| 牛熊对辩 | `bull-bear-debate` — 开仓前强制，牛 > 熊 + 3 |
| 推理审计 | `reasoning-audit` — 证据→推理→决策一致性 |
| 智能平仓 (WS 触发) | `smart-exit` — 多 Agent 实时决策 |
| 平仓后复盘 | `trade-journal` — 归因分析 + 模式识别 |
| **代码自动 (不需要 AI 调用)** | |
| 风控检查 | `risk_gateway.pre_trade_check()` — /open 自动调用 |
| 熔断器 | `risk_gateway.check_circuit_breaker()` — 自动检查 |
| 持仓止损管理 | `scripts/position_manager.py` — cron 自动运行 |
| 市场状态 | `risk_gateway.detect_regime()` — 自动获取 |
| 相关性 | `risk_gateway.check_correlation()` — 自动检查 |
| 仓位计算 | `risk_gateway.calc_position_size()` — 自动计算 |
| **开发工具** | |
| 修复 bug | `bug-fix` |
| 写新功能 | `tdd` (测试驱动) |
| 补测试 | `test-gen` |
| 代码审查 | `code-review` |
| 验证完成 | `verify-completion` |
| 清理 slop | `deslop` |

## 规则

**在任何响应或操作之前，先检查相关 skill。**

Skill 本身会告诉你它是刚性 (必须严格遵循) 还是柔性 (适应上下文)。
