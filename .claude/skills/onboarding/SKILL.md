---
name: onboarding
description: 4-phase codebase onboarding analysis for unfamiliar repos. Generates architecture map, key patterns, gotchas, and entry points.
allowed-tools: Read, Bash, Grep, Glob
argument-hint: "[focus-area]"
---

# Codebase Onboarding

对不熟悉的代码库进行系统性分析，输出可操作的上手指南。

## Phase 1: 项目轮廓 (30s)

快速扫描，建立高层理解：

1. 读取 `package.json` / `Cargo.toml` / `pyproject.toml` / `pom.xml` — 确定技术栈
2. 读取 `README.md` — 项目目标
3. 运行 `ls` 查看顶层目录结构
4. 读取 `.claude/rules/project.md`（如果存在）— 项目约定

输出：
```
## 项目轮廓
- 名称: xxx
- 技术栈: [语言 + 框架 + 数据库]
- 目录结构: [一级目录及用途]
- 入口文件: [main/index/app]
```

## Phase 2: 架构地图 (2min)

深入分析核心模块：

1. 扫描 `src/` 或主要源码目录，统计文件类型和数量
2. 识别分层模式: routes/controllers → services → models → utils
3. 找到配置文件: .env.example, config/, constants
4. 找到依赖注入/初始化入口

输出：
```
## 架构地图
- 分层: [描述层次和依赖方向]
- 核心模块: [列出 3-5 个关键模块及职责]
- 数据流: [请求→处理→响应的典型路径]
- 配置: [环境变量和配置文件位置]
```

## Phase 3: 关键模式 & 陷阱 (2min)

识别代码中的惯用模式和潜在陷阱：

1. Grep 常见模式: error handling, logging, auth, validation
2. 检查测试结构和覆盖率
3. 查看 git log 最近 20 条提交 — 了解活跃区域
4. 检查 CI/CD 配置

输出：
```
## 关键模式
- 错误处理: [项目的模式]
- 认证: [auth 方案]
- 测试: [框架 + 策略]
- 部署: [CI/CD 流程]

## ⚠️ 陷阱 (Gotchas)
- [需要注意的非直觉行为、隐含依赖、环境要求]
```

## Phase 4: 上手指南

综合前三阶段，输出一份简洁的上手指南：

```
## 快速上手

### 环境准备
[安装依赖、环境变量、数据库初始化]

### 开发命令
[dev/build/test/lint 命令]

### 修改代码的起点
- 添加新 API: 从 [路径] 开始
- 修改业务逻辑: 看 [路径]
- 添加测试: 看 [路径]

### 需要了解的约定
- [3-5 条最重要的编码约定]
```

将完整报告写入 `docs/ONBOARDING.md`。

### 导航

```
下一步:
- 开始开发: /spec-create [feature-name]
- 深入了解某模块: 直接阅读代码
- 检查依赖健康: /dep-audit
```
