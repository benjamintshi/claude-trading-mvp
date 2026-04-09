---
name: tdd
description: >-
  Use when implementing any feature or bugfix, before writing implementation code.
  Enforces RED-GREEN-REFACTOR cycle. Iron law: no production code without a failing test first.
allowed-tools: Read, Bash, Write, Edit, Grep
disable-model-invocation: true
argument-hint: "[feature-or-bugfix-description]"
---

# 测试驱动开发 (TDD)

## 概述

先写测试。看它失败。写最小代码通过。

**核心原则:** 如果你没有看到测试失败，你不知道它是否测的对。

**违反规则的字面意思就是违反规则的精神。**

## 铁律

```
没有失败的测试，就不写生产代码
```

先写了代码再写测试？**删掉代码。从头来。**

**没有例外：**
- 不要保留它当"参考"
- 不要在写测试时"改造"它
- 删除就是删除

## 何时使用

**总是：** 新功能、Bug 修复、重构、行为变更

**例外（问你的用户）：** 一次性原型、配置文件

## Red-Green-Refactor 循环

### RED — 写失败测试

```python
# 示例: 测试仓位计算
def test_calc_quantity_respects_risk_limit():
    """单笔风险不超过 capital * risk_pct"""
    qty = calc_quantity("BTCUSDT", 2000, 0.01, 50000, 49500, 3)
    notional = qty * 50000
    risk = qty * abs(50000 - 49500)
    assert risk <= 20.0  # $2000 * 1% = $20
```

**要求：** 一个行为、清晰命名、真实代码（非必要不 mock）

### 验证 RED — 看它失败

确认：测试失败（不是报错）、失败信息符合预期、因为功能缺失而失败

### GREEN — 最小代码

写最简单的代码让测试通过。不加功能。

### 验证 GREEN — 看它通过

确认：测试通过、其他测试仍通过、输出干净

### REFACTOR — 清理

只在 GREEN 之后。保持测试绿色。不加新行为。

## 交易系统特别注意

- **仓位计算 (calc_quantity)**: 必须测试边界情况 (极小止损、极大杠杆、零资金)
- **PnL 计算**: 必须包含手续费扣除的数值验证
- **订单执行**: mock Binance API，验证参数正确性
- **DB 操作**: 用测试数据库，验证状态转换 (open → closed)

## 常见合理化

| 借口 | 现实 |
|------|------|
| "太简单不需要测试" | calc_quantity 一个 bug 就能亏完本金。测试。 |
| "我之后再补测试" | 后补的测试立即通过，证明不了任何事。 |
| "已经手动测过了" | 手动 ≠ 系统化。下次改代码没有回归保护。 |
| "交易逻辑不好测" | mock API 调用，测逻辑。难测试 = 设计问题。 |
| "TDD 太慢" | 比线上亏钱快。 |

## Red Flags

- 先写代码再写测试
- 测试立即通过
- "之后再加测试"
- "就这一次跳过"
- 修改了 lib/ 里的代码但没有对应测试

**以上全部意味着：删掉代码。用 TDD 重来。**

## 下一步
- 实现中遇到 bug? → `/bug-fix`
- 完成实现? → `/verify-completion`
- 需要代码审查? → `/code-review`
