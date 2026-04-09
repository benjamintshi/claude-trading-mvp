---
name: context-budget
description: Audit token consumption across loaded components (rules, skills, MCP tools). Identifies what is consuming the most context.
allowed-tools: Read, Bash, Grep, Glob
argument-hint: "[component-type]"
---

# Context Budget Audit

分析当前 context 中各组件的 token 消耗，帮助优化上下文使用。

## 执行流程

### Step 1: 扫描组件

统计以下组件的近似 token 数（1 token ≈ 4 chars）：

```
Rules:   .claude/rules/**/*.md     — 每个文件单独统计
Skills:  .claude/skills/*/SKILL.md — 已加载的 skill
Agents:  .claude/agents/*/SKILL.md — agent 定义
CLAUDE.md:  根目录                  — 全局指令
```

### Step 2: 估算 Token

对每个文件：
- 读取文件大小（字节数）
- 估算 token 数 = chars / 4
- 按类别汇总

### Step 3: 输出报告

```markdown
## Context Budget Report

| Component        | Files | Est. Tokens | % of Budget |
|-----------------|-------|-------------|-------------|
| Rules (common)  | 10    | ~XXXX       | XX%         |
| Rules (lang)    | 2     | ~XXXX       | XX%         |
| Skills (loaded) | N     | ~XXXX       | XX%         |
| Agents          | 13    | ~XXXX       | XX%         |
| CLAUDE.md       | 1     | ~XXXX       | XX%         |
| **Total**       |       | ~XXXX       | XX%         |

### Top 5 Largest Files
1. file.md — ~XXXX tokens
2. ...

### Recommendations
- [具体建议: 哪些可以精简、哪些可以按需加载]
```

假设总上下文预算为 200K tokens，tools/system prompt 占约 30K。

### Step 4: 导航

```
下一步:
- 精简最大的文件
- 删除不需要的 rules/agents
- /compact 释放对话上下文
```
