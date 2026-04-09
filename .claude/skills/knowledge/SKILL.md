---
name: knowledge
description: >-
  决策日志和知识查询。记录架构决策到 specs/decisions.md，查询过去的决策避免重复讨论。
  Use to record important decisions or review past decisions before starting new features.
allowed-tools: Read, Write, Grep
argument-hint: "[record|query] [topic]"
---

# Knowledge — 决策日志

## 记录决策

当做出重要架构/技术决策时，追加到 `specs/decisions.md`:

```markdown
## DEC-{NNN}: {决策标题}
**日期**: YYYY-MM-DD
**状态**: accepted | superseded | deprecated
**上下文**: 面临什么问题？
**方案**:
  - A: [描述] — 优点/缺点
  - B: [描述] — 优点/缺点
**决策**: 选择方案 [X]
**理由**: 为什么选这个
**后果**: 这个决策带来什么影响
```

## 查询决策

新功能开发前，搜索 `specs/decisions.md`:
- 有没有类似问题已做过决策？
- 有没有被否决的方案不应再尝试？
- 有没有约束条件需要遵守？

## 与 Memory 系统的分工
- **specs/decisions.md** — 项目级架构决策（正式、可追溯、团队共享）
- **Claude Memory** — 个人偏好、工作习惯、临时经验（自动、跨项目）
- 原则：团队需要知道的 → decisions.md；只对我有用的 → Memory
