---
paths:
  - "**/*.py"
---

# Python 代码规范

## 风格
- 遵循 PEP 8
- 使用 type hints (函数参数和返回值)
- f-string 优于 format() 或 %
- 使用 pathlib 而非 os.path

## 错误处理
- 捕获具体异常，不用裸 `except:`
- API 调用必须有 try/except + 有意义的错误信息
- 数据库操作用 context manager (with conn)
- 网络请求设置 timeout

## 安全
- 不硬编码 API keys、密码、token
- 所有秘密信息从环境变量读取
- 日志中不输出敏感信息 (API secret, 完整 token)
- SQL 用参数化查询，不用 f-string 拼接

## 测试
- 测试文件放 `tests/` 目录
- 测试函数 `test_` 前缀
- mock 外部 API 调用 (Binance, Telegram)
- 测试覆盖: 正常路径 + 边界条件 + 错误处理
