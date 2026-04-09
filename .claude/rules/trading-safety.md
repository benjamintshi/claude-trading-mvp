---
paths:
  - "lib/**"
  - "scripts/**"
  - ".claude/commands/**"
---

# 交易系统安全规则

<important>
修改以下参数时必须通知用户确认：
- 仓位计算逻辑 (calc_quantity, calc_adaptive_risk_pct)
- 风控参数 (max_positions, leverage, capital, 评分门槛)
- 自适应仓位参数 (评分→风险映射, regime risk_multiplier)
- 订单执行逻辑 (place_order, open_position_with_sl_tp, close_long/short)
- PnL 计算 (commission rate, pnl formula)
- 止损管理规则
- 信号权重边界 (MAX_WEIGHT, MIN_WEIGHT)

绝不允许：
- 移除或绕过仓位限制 (max 5)
- 移除或绕过风险比率检查 (> 3:1)
- 将杠杆设置超过 10x
- 在没有止损的情况下开仓
- 硬编码 API 密钥
- 跳过验证链的任何步骤 (regime → debate → audit → risk-check → correlation)
- 在 bull-bear-debate 中伪造或跳过熊方论证
- 在 reasoning-audit 中忽略三角不一致
- 手动覆盖 calc_adaptive_risk_pct 的结果 (不得硬编码仓位大小)
</important>

## 验证链安全
- 开仓必须按顺序通过: regime-detect → bull-bear-debate → reasoning-audit → risk-check → correlation
- 任一步骤拦截 → 不开仓，不得绕过
- 高波震荡状态下评分门槛自动 +2 (10/14 才开仓)，不得手动降低

## Paper/Live 模式安全
- 切换 PAPER_TRADING=false 前必须通知用户确认
- 不得在代码中硬编码 PAPER_TRADING 值，必须从环境变量读取
- Paper 模式下的模拟数据 (data/paper/) 不得与实盘数据混淆

## 信号反馈安全
- 信号权重范围: 0 ≤ weight ≤ 3，不得突破
- 权重更新需要 ≥ 5 笔样本，样本不足保持默认权重
- 不得手动编辑 signal_weights.json 绕过自动调权逻辑

## 数据完整性
- positions 表的 status 只有 'open' 和 'closed' 两个值
- 平仓时必须同时更新 positions 和 trades 表
- PnL 计算必须扣除双向手续费
- 平仓后必须调用 record_trade_signals() 记录信号反馈

## 变更流程
- 修改 lib/binance.py 中的订单逻辑 → 必须有对应测试
- 修改 lib/db.py 中的 PnL 计算 → 必须有数值验证测试
- 修改 lib/feedback.py 中的权重逻辑 → 必须有边界值测试
- 修改 scripts/ 中的自动化脚本 → 先在非 cron 环境手动验证
