# 架构设计（Design）

## 1. 分层与模块
- 分层：
  - API 层（脚本与可能的 HTTP API 扩展点）
  - 服务层（core/services/*）
  - 领域层（core/domain/*）
  - 适配器层（core/adapters/exchanges/*）
  - 基础设施层（core/infrastructure/*, core/logging/*）
- 设计原则：依赖倒置、接口分离、单一职责、开闭原则；避免跨层依赖与循环依赖

## 2. 交易所适配层
- 目标：以 `ExchangeInterface` 定义一致的能力边界，支撑可替换性与多交易所共存
- 组成：
  - `interface.py`：统一接口与配置对象（`ExchangeConfig`）
  - `models.py`：Decimal/时间戳友好的统一数据模型
  - `adapters/<exchange>_*.py`：各交易所 REST/WS 实现与 glue 逻辑
  - `factory.py`：`create_adapter(exchange_id, config)` 生成具体适配器
  - `subscription_manager.py` / `websocket_manager.py`：订阅、心跳、重连
  - `utils/*.py`：日志、格式化等通用工具
- 关键设计：
  - WS 优先：行情流、订单更新采用 WS，REST 兜底
  - 心跳与重连：`enable_heartbeat`、`heartbeat_interval`、`_is_heartbeat_alive()`
  - 精度：统一在模型与下单参数构造处量化（price_decimals/quantity_precision）

## 3. 网格交易服务
- 入口：`run_grid_trading.py`
- 组装：
  - `GridConfig`：从 YAML 解析 + 校验 + Follow 模式动态区间
  - `ExchangeFactory`：创建并连接适配器；自动识别现货/永续
  - `GridStrategyImpl` + `GridEngineImpl` + `PositionTrackerImpl`
  - `GridCoordinator`：终端 UI、循环控制、健康检查、退出清理
- 关键算法
  - Follow 动态价格区间：
    - Long：`upper = base_price(+offset)`，`lower = upper - grid_count*interval`
    - Short：`lower = base_price(-offset)`，`upper = lower + grid_count*interval`
    - 统一 `quantize(price_decimals)`，避免“查询价格与下单价格精度不一致”
  - 网格价格与索引：
    - `get_grid_price(i)` 与 `get_grid_index_by_price(price)` 使用 Decimal 与 round
  - 健康检查：
    - 至少 2 次快照；对比订单与持仓状态；`position_tolerance` 容差
  - 风控组件：
    - 剥头皮（简单/智能）、本金保护、止盈、价格锁定、止损保护、退出清理

## 4. 刷量交易服务（Volume Maker）
- 架构：双交易所（信号源 Backpack/Hyperliquid，执行端 Lighter）
- 流程（市价模式）：
  1) 监控信号源订单簿并等待价格稳定
  2) 检查买卖量比例/最小数量等条件
  3) 决策方向（随机/交替/反向）
  4) 在 Lighter 市价开仓（滑点保护）
  5) 等待价格变化次数或延时
  6) 市价平仓并统计
- 性能优化：
  - `client_id + WS` 跟踪订单，常态 0.5–2s 得到成交；超时回退 REST
  - 降低每轮 REST 数，从 4–5 次优化至 1–2 次

## 5. 套利监控与价格提醒
- 套利监控：
  - 统一符号（如 `BTC-USDC-PERP`），跨交易所取价与费率
  - 排序、动态精度、声音提醒，避免 UI 抖动
- 价格提醒：
  - 现货与永续并行；窗口波动与上下限触发；酷冷时间防抖

## 6. 网格波动率扫描器
- 虚拟网格，不实际下单；实时 APR 估计
- 排名与评级（S≥500%）
- Rich UI 与可参数化扫描窗口/交易所

## 7. 终端 UI 与日志
- 终端 UI：
  - 网格/套利/刷量/扫描器：状态、指标、表格、颜色提示
  - 交互：Q 退出；Ctrl+C 安全中断
- 日志：
  - `setup_optimized_logging()`；模块前缀；旋转文件；DEBUG 级别覆盖关键模块

## 8. 错误处理与恢复
- 断线 → 重连；WS 异常 → 回退 REST；多级重试
- 退出清理：停止 UI、撤销订单、平仓、断开适配器
- 配置缺失与精度错误：明确报错与建议（如 Lighter 的保证金与杠杆提示）

## 9. 可扩展性
- 新交易所：实现 `ExchangeInterface`；在 `factory` 注册
- 新策略：在 `core/services` 引入接口 + 实现，并在入口脚本组装
- 新 UI：沿用 Rich 组件与模块化 logger，保持一致体验

## 10. 测试建议
- 适配器：行情、订单创建/取消、订阅、心跳
- 网格：价格区间量化、索引换算、健康检查与容差
- 刷量：client_id + WS 路径、超时回退 REST、滑点阶梯

