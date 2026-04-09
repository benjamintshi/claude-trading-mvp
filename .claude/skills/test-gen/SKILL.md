---
name: test-gen
description: >-
  Generate tests for existing code. Analyzes functions and generates
  unit tests covering happy path, edge cases, and error scenarios.
  Use when adding tests to untested code or improving test coverage.
allowed-tools: Read, Write, Bash, Grep
disable-model-invocation: true
argument-hint: "[file-path or function-name]"
---

# Test Generation — 为现有代码生成测试

## 流程

### 1. 分析目标代码
读取目标文件/函数，理解：
- 输入参数和类型
- 返回值和类型
- 副作用 (数据库、API 调用)
- 错误路径
- 分支逻辑
- 外部依赖 (需要 mock 的服务)

### 2. 确定测试策略

```
对每个公开函数:

  Happy Path:
  - 正常输入 → 预期输出

  Edge Cases:
  - 空值、边界值、特殊输入

  Error Path:
  - 无效输入 → 预期错误
  - 依赖失败 → 错误处理
```

### 3. 交易系统优先级

按风险排序生成测试：

| 优先级 | 模块 | 关键函数 | 测试重点 |
|--------|------|---------|---------|
| P0 | lib/binance.py | `calc_quantity` | 仓位计算精度、边界、溢出 |
| P0 | lib/db.py | `close_position` | PnL 计算含手续费 |
| P1 | lib/binance.py | `place_order`, `open_long/short` | API 参数正确性 |
| P1 | lib/db.py | `open_position`, `get_open_positions` | 状态管理 |
| P2 | lib/notify.py | `notify_open`, `notify_close` | 消息格式、降级 |

### 4. 生成测试文件

**文件位置**: `tests/test_{module}.py`
- `tests/test_binance.py` — mock urllib, 测试逻辑
- `tests/test_db.py` — 测试数据库用 SQLite 或 mock psycopg2
- `tests/test_notify.py` — mock urllib, 测试格式化

**测试结构**:
- pytest 框架
- 按函数分组 (class TestCalcQuantity, class TestClosePosition)
- 测试名描述行为: `test_calc_quantity_caps_at_max_notional`
- AAA 模式: Arrange → Act → Assert
- Mock 外部 API，不 mock 被测单元

### 5. 验证
- `pytest tests/ -v` 全部通过
- 确认关键路径覆盖
- 确认没有测试依赖外部服务 (Binance API, Telegram, PostgreSQL)

## 输出

```markdown
## 测试生成报告

### 目标: [文件/函数名]
### 生成测试文件: [路径]
### 测试数量: [N] 个

| 函数 | Happy Path | Edge Cases | Error Path | 总计 |
|------|-----------|------------|------------|------|
| calc_quantity | 2 | 3 | 2 | 7 |
| close_position | 1 | 2 | 1 | 4 |

### 运行结果: ✅ 全部通过
```

## 下一步
- 测试写完了? → 运行 `pytest tests/ -v`
- 需要新功能? → `/tdd` (先写测试再实现)
- 需要代码审查? → `/code-review`
