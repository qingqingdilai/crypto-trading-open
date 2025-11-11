# 技术规格（Spec）

## 1. 总览
- 运行入口：
  - 网格交易：`run_grid_trading.py [--debug] <grid_config.yaml>`
  - 刷量（Backpack挂单）：`run_volume_maker.py <config.yaml>`
  - 刷量（Lighter市价）：`run_lighter_volume_maker.py <config.yaml>`
  - 套利监控：`run_arbitrage_monitor.py`
  - 价格提醒：`run_price_alert.py <config.yaml>`
  - 网格波动率扫描：`grid_volatility_scanner/run_scanner.py [--duration N] [--exchange X]`
- 核心模块：
  - `core/adapters/exchanges`（适配层：接口、工厂、管理、WS 管理）
  - `core/services/grid`（网格策略与执行）
  - `core/services/volume_maker`（刷量逻辑）
  - `core/services/arbitrage_monitor`（套利监控）
  - `core/services/price_alert`（价格提醒）
  - `core/infrastructure`（配置、日志、DI 等）

## 2. 统一交易所接口（ExchangeInterface）
文件：`core/adapters/exchanges/interface.py`

- 生命周期
  - `connect() -> bool`
  - `disconnect() -> None`
  - `authenticate() -> bool`
  - `health_check() -> Dict`
- 市场数据
  - `get_exchange_info() -> ExchangeInfo`
  - `get_ticker(symbol) -> TickerData`
  - `get_tickers(symbols=None) -> List[TickerData>`
  - `get_orderbook(symbol, limit=None) -> OrderBookData`
  - `get_ohlcv(symbol, timeframe, since=None, limit=None) -> List[OHLCVData>`
  - `get_trades(symbol, since=None, limit=None) -> List[TradeData]`
- 账户与交易
  - `get_balances() -> List[BalanceData]`
  - `get_positions(symbols=None) -> List[PositionData]`
  - `create_order(symbol, side, order_type, amount, price=None, params=None) -> OrderData`
  - `cancel_order(order_id, symbol) -> OrderData`
  - `cancel_all_orders(symbol=None) -> List[OrderData]`
  - `get_order(order_id, symbol) -> OrderData`
  - `get_open_orders(symbol=None) -> List[OrderData]`
  - `get_order_history(symbol=None, since=None, limit=None) -> List[OrderData]`
- 交易设置
  - `set_leverage(symbol, leverage) -> Dict`
  - `set_margin_mode(symbol, margin_mode) -> Dict`
- 实时订阅
  - `subscribe_ticker(symbol, callback)`
  - `subscribe_orderbook(symbol, callback)`
  - `subscribe_trades(symbol, callback)`
  - `subscribe_user_data(callback)`
  - `unsubscribe(symbol=None)`
- 状态/事件
  - `get_status()`, `is_connected()`, `is_authenticated()`
  - `add_event_callback(event_type, callback)`, `remove_event_callback(event_type, callback)`

数据模型文件：`core/adapters/exchanges/models.py`
- 关键类型：`ExchangeType`, `OrderSide`, `OrderType`, `OrderStatus`, `PositionSide`, `MarginMode`
- 数据结构：`OrderData`, `PositionData`, `BalanceData`, `TickerData`, `OHLCVData`, `OrderBookData`, `TradeData`, `ExchangeInfo`
- Decimal 精度与时间戳处理在 `__post_init__` 中统一完成

## 3. 配置规格

### 3.1 网格交易（示例：`config/grid/lighter-long-perp-btc.yaml`）
- 必填：
  - `exchange`（如 lighter）
  - `symbol`（如 BTC / 交易所格式）
  - `grid_type`：`long|short|follow_long|follow_short|martingale_long|martingale_short`
  - `grid_interval`（价格步长）
  - `order_amount`（每格基础数量）
- Follow 模式：
  - `follow_grid_count`、`follow_timeout`、`follow_distance`、`price_offset_grids`
- 固定范围模式：
  - `price_range.lower_price | upper_price`
- 精度与风控：
  - `quantity_precision`、`price_decimals`、`fee_rate`
  - `margin_mode`、`leverage`
  - 剥头皮：`scalping_enabled`, `scalping_trigger_percent`, `scalping_take_profit_grids`
  - 智能剥头皮：`smart_scalping_enabled`, `allowed_deep_drops`, `min_drop_threshold_percent`
  - 本金保护：`capital_protection_enabled`, `capital_protection_trigger_percent`
  - 止盈：`take_profit_enabled`, `take_profit_percentage`
  - 价格锁定：`price_lock_enabled`, `price_lock_threshold`, `price_lock_start_at_threshold`
  - 止损保护：`stop_loss_protection_enabled`, `stop_loss_trigger_percent`, `stop_loss_escape_timeout`, `stop_loss_apr_threshold`
  - 退出清理：`exit_cleanup_enabled`
  - 其他：`reverse_order_grid_distance`, `order_health_check_enabled`, `order_health_check_interval`, `health_check_snapshot_count`, `rest_position_query_interval`, `enable_notifications`
- 运行时行为：
  - `detect_market_type()` 基于 `exchange + symbol` 推断现货/永续
  - Follow 模式动态计算 `upper/lower` 并按 `price_decimals` 量化

### 3.2 套利监控（`config/arbitrage/monitor.yaml`）
- 交易所：`exchanges: [edgex, lighter]`（示例）
- 标的：`symbols: [BTC-USDC-PERP, ...]`
- 阈值：`thresholds.price_spread`、`thresholds.funding_rate`、`thresholds.min_score`
- 监控周期：`monitoring.update_interval`
- 展示：`display.refresh_rate`, `display.max_opportunities`, `show_all_prices`, `show_funding_rates`
- 日志：`logging.level`, `logging.file`, `logging.console`

### 3.3 价格提醒（`config/price_alert/binance_alert.yaml`）
- 交易所与标的：spot/perpetual 混合清单
- 波动报警：窗口大小与百分比阈值
- 价格目标：上下限突破报警
- 报警：声音类型、持续、次数、冷却时间
- 终端列显示与颜色配置
- 日志文件与等级

### 3.4 刷量（`config/volume_maker/lighter_volume_maker.yaml`）
- 双交易所：`signal_exchange`（backpack|hyperliquid）、`execution_symbol`（lighter）
- 订单：`order_mode=market`, `order_size`, `min_size`, `max_size`, `quantity_precision`
- 市价参数：`market_wait_price_change`, `market_price_change_count`
- 滑点：`slippage` + 自动重试阶梯
- 价格稳定检测：`stability_check_duration`, `price_tolerance`, `check_interval`
- 订单簿条件与方向策略：`check_orderbook_reversal`, `direction_strategy`, `reverse_trading`
- 风控：`max_cycles`, `max_position`, `max_slippage`, `order_timeout`, `max_consecutive_fails`, `consecutive_fail_wait_minutes`

## 4. 命令行参数与日志
- 网格：`--debug` 开启详细日志；模块日志文件如 `logs/ExchangeAdapter.log`
- 终端 UI：网格、套利、刷量均提供 Rich UI；退出键 `Q` / `Ctrl+C`
- 日志：旋转文件、结构化格式、模块前缀（如 `core.adapters.exchanges...`）

## 5. 健康检查与错误处理
- 健康检查：快照次数（>=2）、位置容差、订单一致性比对
- 自动重连：心跳丢失 → 重连；WS 正常则尽量避免 REST
- 退出清理：撤单、平仓、断开适配器（确保一致性）
- 精度：下单与匹配查询统一量化到 `price_decimals` 与 `quantity_precision`

## 6. 性能与资源
- WS 优先；REST 退化并限频
- 刷量优化：`client_id + WS` 追踪，常态 0.5–2s 成交确认；超时再回退 REST
- 日志滚动与最低 IO 干扰

## 7. 安全与合规
- API Key/Secret 从环境变量或私有配置载入；不打印；最小化权限
- 交易风险提示：仅供研究/开发用途，谨慎资金管理

## 8. 测试与验证（概述）
- 手工测试脚本：`test/*.py`（适配器、订单簿、清算价）
- 建议：在测试账户与小额资金上逐步验证网格/刷量/提醒行为

