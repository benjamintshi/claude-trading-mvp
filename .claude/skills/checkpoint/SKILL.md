---
name: checkpoint
description: >-
  保存当前工作进度到文件，支持跨会话恢复。
  Use to save progress before ending a session or switching tasks.
allowed-tools: Read, Write, Bash
argument-hint: "[save|restore]"
---

# 检查点 — 保存和恢复进度

## 保存 (当用户说"保存进度" / "checkpoint")

创建或更新 `specs/checkpoint.md`:

```markdown
# Checkpoint — {日期时间}

## 当前任务
{正在做什么}

## 进度
- [x] 已完成的步骤
- [ ] 下一步要做的事
- [ ] 后续步骤

## 上下文
- 分支: {当前 git 分支}
- 最近修改: {git diff --stat 摘要}
- 未提交变更: {有/无}

## 决策记录
- {做了什么决策，为什么}
- {尝试过什么方案，结果如何}

## 恢复说明
继续工作时：
1. 切到分支 {branch}
2. 读取 specs/{feature}/TASKS.md 看任务进度
3. 从 Task {N} 继续
```

## 恢复 (当新会话开始时)

如果 `specs/checkpoint.md` 存在：
1. 读取检查点内容
2. 告诉用户上次的进度
3. 询问是否从上次继续

## 关键原则
- **自动提醒**: 如果上下文快满了，主动建议保存 checkpoint
- **简洁**: 只记有用信息，不记废话
- **可恢复**: 新 session 的 Claude 读了 checkpoint 就能继续工作
