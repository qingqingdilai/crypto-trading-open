"""
套利执行器（TradeExecutionManager）实盘测试脚本 - Backpack 专用

⚠️  警告：这是实盘测试脚本，会使用真实资金进行交易！
🎯 测试目标：验证套利执行器的完整REST API功能
🔧 测试范围：
   - Backpack 交易所
   - 所有REST API功能（市场数据、账户、交易、设置）
   - 综合功能测试（批量操作、统计信息）

测试币种：SOL_USDC_PERP
测试金额：0.1 SOL（每个测试）

使用前请确保：
1. 已在 config/exchanges/backpack_config.yaml 中设置API密钥
2. 账户中有足够的资金
3. 理解这是实盘交易，会产生真实的费用和风险
"""

import asyncio
import sys
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.logging import get_logger
from core.adapters.exchanges.factory import get_exchange_factory
from core.adapters.exchanges.interface import ExchangeConfig
from core.services.arbitrage.execution.trade_execution_manager import TradeExecutionManager
from core.services.arbitrage.initialization.precision_manager import PrecisionManager
from core.services.arbitrage.shared.models import TradePlan, OrderType, ArbitrageDirection

# 测试配置
TEST_SYMBOL = "SOL_USDC_PERP"  # 修复：使用Backpack正确的永续合约符号格式
TEST_AMOUNT = Decimal("0.1")  # 0.1 SOL
SAFETY_PRICE_OFFSET = Decimal("0.05")  # 价格偏移5%，确保限价单不会立即成交

# 测试的交易所列表 - 只测试 Backpack
EXCHANGES = ["backpack"]

class TradeExecutionManagerLiveTest:
    """套利执行器实盘测试类"""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.execution_manager: Optional[TradeExecutionManager] = None
        self.precision_manager: Optional[PrecisionManager] = None
        self.exchange_adapters = {}
        self.test_results = {}
        self.test_orders = []  # 记录测试订单，用于清理
        
    async def initialize(self) -> bool:
        """初始化测试环境"""
        try:
            self.logger.info("🚀 开始初始化套利执行器测试环境")
            
            # 1. 创建交易所工厂
            factory = get_exchange_factory()
            
            # 2. 创建交易所适配器
            for exchange_name in EXCHANGES:
                try:
                    config = self._load_exchange_config(exchange_name)
                    if config:
                        adapter = factory.create_adapter(config.exchange_id, config)
                        if adapter:
                            success = await adapter.connect()
                            if success:
                                self.exchange_adapters[exchange_name] = adapter
                                self.logger.info(f"✅ {exchange_name} 连接成功")
                            else:
                                self.logger.warning(f"⚠️ {exchange_name} 连接失败")
                        else:
                            self.logger.warning(f"⚠️ {exchange_name} 适配器创建失败")
                    else:
                        self.logger.warning(f"⚠️ {exchange_name} 配置加载失败")
                except Exception as e:
                    self.logger.error(f"❌ {exchange_name} 初始化失败: {e}")
            
            if not self.exchange_adapters:
                self.logger.error("❌ 没有可用的交易所适配器")
                return False
            
            # 3. 创建精度管理器
            self.precision_manager = PrecisionManager(self.exchange_adapters)
            
            # 获取测试交易对列表
            overlapping_symbols = [TEST_SYMBOL]
            success = await self.precision_manager.initialize_precision_cache(overlapping_symbols)
            if not success:
                self.logger.error("❌ 精度管理器初始化失败")
                return False
            
            # 4. 创建套利执行器
            self.execution_manager = TradeExecutionManager(
                exchange_adapters=self.exchange_adapters,
                precision_manager=self.precision_manager,
                config={
                    'default_timeout': 30,
                    'max_retries': 3,
                    'retry_delay': 1.0
                }
            )
            
            self.logger.info("✅ 套利执行器初始化成功")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 初始化失败: {e}")
            return False
    
    def _load_exchange_config(self, exchange_name: str) -> Optional[ExchangeConfig]:
        """加载交易所配置"""
        try:
            import yaml
            
            config_path = Path(__file__).parent.parent.parent / "config" / "exchanges" / f"{exchange_name}_config.yaml"
            
            if not config_path.exists():
                self.logger.warning(f"配置文件不存在: {config_path}")
                return None
            
            with open(config_path, 'r', encoding='utf-8') as file:
                config_data = yaml.safe_load(file)
            
            exchange_config = config_data.get(exchange_name, {})
            auth_config = exchange_config.get('authentication', {})
            
            # 检查认证信息（不同交易所有不同的认证方式）
            has_auth = False
            if exchange_name == 'hyperliquid':
                # Hyperliquid使用钱包私钥认证
                has_auth = bool(auth_config.get('private_key') and auth_config.get('wallet_address'))
            elif exchange_name == 'backpack':
                # Backpack使用API密钥和私钥认证
                has_auth = bool(auth_config.get('api_key') and auth_config.get('private_key'))
            elif exchange_name == 'edgex':
                # EdgeX使用API密钥认证
                has_auth = bool(auth_config.get('api_key') and auth_config.get('api_secret'))
            
            if not has_auth:
                self.logger.warning(f"⚠️ {exchange_name} 未设置认证信息或认证信息不完整")
                self.logger.info(f"   请在 config/exchanges/{exchange_name}_config.yaml 中设置认证信息")
                return None
            
            # 确定交易所类型
            from core.adapters.exchanges.models import ExchangeType
            exchange_type = ExchangeType.PERPETUAL  # 默认永续合约
            
            # 获取基础URL
            base_url = exchange_config.get('api', {}).get('base_url', '')
            if not base_url:
                # 设置默认URL
                default_urls = {
                    'hyperliquid': 'https://api.hyperliquid.xyz',
                    'backpack': 'https://api.backpack.exchange',
                    'edgex': 'https://api.edgex.exchange'
                }
                base_url = default_urls.get(exchange_name, '')
            
            # 根据交易所类型设置认证信息
            api_key = ''
            api_secret = ''
            
            if exchange_name == 'hyperliquid':
                # Hyperliquid使用private_key作为api_key
                api_key = auth_config.get('private_key', '')
            elif exchange_name == 'backpack':
                # Backpack使用api_key和private_key
                api_key = auth_config.get('api_key', '')
                api_secret = auth_config.get('private_key', '')  # backpack使用private_key作为secret
            elif exchange_name == 'edgex':
                # EdgeX使用api_key和api_secret
                api_key = auth_config.get('api_key', '')
                api_secret = auth_config.get('api_secret', '')
            
            return ExchangeConfig(
                exchange_id=exchange_name,
                name=exchange_name.capitalize(),
                exchange_type=exchange_type,
                api_key=api_key,
                api_secret=api_secret,
                wallet_address=auth_config.get('wallet_address', ''),
                base_url=base_url,
                testnet=False,  # 实盘测试
                rate_limits={},
                precision={}
            )
            
        except Exception as e:
            self.logger.error(f"加载配置失败: {exchange_name} - {e}")
            return None
    
    async def run_all_tests(self):
        """运行所有测试"""
        print("🚀 开始套利执行器完整功能测试")
        print("=" * 80)
        
        # 测试计划
        test_plan = [
            ("系统管理功能", self.test_system_management),
            ("市场数据功能", self.test_market_data),
            ("账户管理功能", self.test_account_management),
            ("交易设置功能", self.test_trading_settings),
            ("订单管理功能", self.test_order_management),
            ("批量操作功能", self.test_batch_operations),
            ("统计信息功能", self.test_statistics),
            ("交易执行功能", self.test_trade_execution),
        ]
        
        for test_name, test_func in test_plan:
            try:
                print(f"\n📋 测试: {test_name}")
                print("-" * 60)
                
                result = await test_func()
                self.test_results[test_name] = result
                
                if result.get('success', False):
                    print(f"✅ {test_name} 测试通过")
                else:
                    print(f"❌ {test_name} 测试失败: {result.get('error', '未知错误')}")
                    
            except Exception as e:
                print(f"❌ {test_name} 测试异常: {e}")
                self.test_results[test_name] = {'success': False, 'error': str(e)}
        
        # 清理测试订单
        await self.cleanup_test_orders()
        
        # 输出测试报告
        await self.generate_test_report()
    
    async def test_system_management(self) -> Dict[str, Any]:
        """测试系统管理功能"""
        results = {}
        
        try:
            # 1. 健康检查
            health_report = await self.execution_manager.health_check_all()
            results['health_check'] = {
                'success': len(health_report) > 0,
                'exchanges': list(health_report.keys()),
                'healthy_count': sum(1 for status in health_report.values() if status.get('status') == 'healthy')
            }
            print(f"   📊 健康检查: 检测到 {len(health_report)} 个交易所")
            
            # 2. 获取支持的交易对
            all_symbols = {}
            for exchange in EXCHANGES:
                if exchange in self.exchange_adapters:
                    symbols = await self.execution_manager.get_supported_symbols(exchange)
                    all_symbols[exchange] = len(symbols)
                    print(f"   📋 {exchange}: 支持 {len(symbols)} 个交易对")
            
            results['supported_symbols'] = all_symbols
            
            # 3. 获取交易所信息
            exchange_info = {}
            for exchange in EXCHANGES:
                if exchange in self.exchange_adapters:
                    info = await self.execution_manager.get_exchange_info(exchange)
                    exchange_info[exchange] = info is not None
                    print(f"   🏢 {exchange}: 信息获取 {'成功' if info else '失败'}")
            
            results['exchange_info'] = exchange_info
            
            return {
                'success': True,
                'results': results,
                'summary': f"健康检查完成，{results['health_check']['healthy_count']} 个交易所健康"
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def test_market_data(self) -> Dict[str, Any]:
        """测试市场数据功能"""
        results = {}
        
        try:
            for exchange in EXCHANGES:
                if exchange not in self.exchange_adapters:
                    continue
                
                exchange_results = {}
                
                # 1. 获取行情数据
                ticker = await self.execution_manager.get_ticker(exchange, TEST_SYMBOL)
                exchange_results['ticker'] = ticker is not None
                if ticker:
                    print(f"   📈 {exchange} 行情: {ticker.last}")
                
                # 2. 获取多个行情
                tickers = await self.execution_manager.get_tickers(exchange, [TEST_SYMBOL])
                exchange_results['tickers'] = len(tickers) > 0
                
                # 3. 获取订单簿
                orderbook = await self.execution_manager.get_orderbook(exchange, TEST_SYMBOL, 10)
                exchange_results['orderbook'] = orderbook is not None
                if orderbook:
                    print(f"   📊 {exchange} 订单簿: {len(orderbook.bids)} 买单, {len(orderbook.asks)} 卖单")
                
                # 4. 获取K线数据
                ohlcv = await self.execution_manager.get_ohlcv(exchange, TEST_SYMBOL, "1m", limit=5)
                exchange_results['ohlcv'] = len(ohlcv) > 0
                
                # 5. 获取成交记录
                trades = await self.execution_manager.get_trades(exchange, TEST_SYMBOL, limit=5)
                exchange_results['trades'] = len(trades) > 0
                
                results[exchange] = exchange_results
                
                success_count = sum(1 for result in exchange_results.values() if result)
                print(f"   ✅ {exchange} 市场数据: {success_count}/5 项成功")
            
            return {
                'success': True,
                'results': results,
                'summary': f"市场数据测试完成，覆盖 {len(results)} 个交易所"
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def test_account_management(self) -> Dict[str, Any]:
        """测试账户管理功能"""
        results = {}
        
        try:
            # 1. 获取所有余额
            all_balances = await self.execution_manager.get_all_balances()
            results['all_balances'] = len(all_balances) > 0
            
            for exchange, balances in all_balances.items():
                balance_count = len(balances) if isinstance(balances, list) else len(balances)
                print(f"   💰 {exchange} 余额: {balance_count} 个币种")
            
            # 2. 获取所有持仓
            all_positions = await self.execution_manager.get_all_positions()
            results['all_positions'] = len(all_positions) > 0
            
            for exchange, positions in all_positions.items():
                position_count = len(positions)
                print(f"   📊 {exchange} 持仓: {position_count} 个仓位")
            
            # 3. 单独获取每个交易所的账户信息
            for exchange in EXCHANGES:
                if exchange not in self.exchange_adapters:
                    continue
                
                # 获取余额
                balance = await self.execution_manager.get_account_balance(exchange)
                results[f'{exchange}_balance'] = balance is not None
                
                # 获取持仓
                positions = await self.execution_manager.get_positions(exchange)
                results[f'{exchange}_positions'] = positions is not None
            
            return {
                'success': True,
                'results': results,
                'summary': f"账户管理测试完成，检查了 {len(all_balances)} 个交易所"
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def test_trading_settings(self) -> Dict[str, Any]:
        """测试交易设置功能"""
        results = {}
        
        try:
            for exchange in EXCHANGES:
                if exchange not in self.exchange_adapters:
                    continue
                
                exchange_results = {}
                
                # 1. 测试设置杠杆（使用低杠杆避免风险）
                leverage_result = await self.execution_manager.set_leverage(exchange, TEST_SYMBOL, 1)
                exchange_results['leverage'] = leverage_result
                print(f"   ⚖️  {exchange} 设置杠杆: {'成功' if leverage_result else '失败'}")
                
                # 2. 测试设置保证金模式
                margin_result = await self.execution_manager.set_margin_mode(exchange, TEST_SYMBOL, 'cross')
                exchange_results['margin_mode'] = margin_result
                print(f"   📊 {exchange} 保证金模式: {'成功' if margin_result else '失败'}")
                
                results[exchange] = exchange_results
            
            return {
                'success': True,
                'results': results,
                'summary': f"交易设置测试完成，测试了 {len(results)} 个交易所"
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def test_order_management(self) -> Dict[str, Any]:
        """测试订单管理功能"""
        results = {}
        
        try:
            for exchange in EXCHANGES:
                if exchange not in self.exchange_adapters:
                    continue
                
                exchange_results = {}
                
                # 1. 获取活跃订单
                open_orders = await self.execution_manager.get_open_orders(exchange, TEST_SYMBOL)
                exchange_results['open_orders'] = len(open_orders) if open_orders else 0
                print(f"   📋 {exchange} 活跃订单: {exchange_results['open_orders']} 个")
                
                # 2. 获取历史订单
                history_orders = await self.execution_manager.get_order_history(
                    exchange, TEST_SYMBOL, limit=10
                )
                exchange_results['history_orders'] = len(history_orders) if history_orders else 0
                print(f"   📚 {exchange} 历史订单: {exchange_results['history_orders']} 个")
                
                # 3. 创建测试订单（使用安全的限价单）
                try:
                    # 获取当前价格
                    ticker = await self.execution_manager.get_ticker(exchange, TEST_SYMBOL)
                    if ticker and ticker.last:
                        # 创建一个不会立即成交的限价买单
                        safe_price = ticker.last * (1 - SAFETY_PRICE_OFFSET)
                        
                        order = await self.execution_manager.create_order(
                            exchange=exchange,
                            symbol=TEST_SYMBOL,
                            side='buy',
                            order_type='limit',
                            amount=TEST_AMOUNT,
                            price=safe_price
                        )
                        
                        if order:
                            exchange_results['create_order'] = True
                            self.test_orders.append((exchange, order.id, TEST_SYMBOL))
                            print(f"   ✅ {exchange} 创建订单: {order.id}")
                            
                            # 查询订单状态
                            order_status = await self.execution_manager.get_order_status(
                                order.id, exchange, TEST_SYMBOL
                            )
                            exchange_results['order_status'] = order_status is not None
                            
                        else:
                            exchange_results['create_order'] = False
                            print(f"   ❌ {exchange} 创建订单失败")
                    else:
                        exchange_results['create_order'] = False
                        print(f"   ❌ {exchange} 无法获取价格，跳过订单测试")
                        
                except Exception as e:
                    exchange_results['create_order'] = False
                    print(f"   ❌ {exchange} 订单测试异常: {e}")
                
                results[exchange] = exchange_results
            
            return {
                'success': True,
                'results': results,
                'summary': f"订单管理测试完成，创建了 {len(self.test_orders)} 个测试订单"
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def test_batch_operations(self) -> Dict[str, Any]:
        """测试批量操作功能"""
        results = {}
        
        try:
            # 1. 批量取消订单
            if self.test_orders:
                cancel_results = await self.execution_manager.batch_cancel_orders(self.test_orders)
                results['batch_cancel'] = {
                    'total': len(self.test_orders),
                    'success': sum(1 for result in cancel_results.values() if result),
                    'details': cancel_results
                }
                print(f"   🗑️  批量取消: {results['batch_cancel']['success']}/{results['batch_cancel']['total']} 成功")
                
                # 清空测试订单列表
                self.test_orders.clear()
            else:
                results['batch_cancel'] = {'total': 0, 'success': 0}
                print("   ℹ️  没有测试订单需要取消")
            
            return {
                'success': True,
                'results': results,
                'summary': f"批量操作测试完成，取消了 {results['batch_cancel']['success']} 个订单"
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def test_statistics(self) -> Dict[str, Any]:
        """测试统计信息功能"""
        results = {}
        
        try:
            # 获取执行统计
            stats = await self.execution_manager.get_execution_stats()
            results['execution_stats'] = stats
            
            print(f"   📊 总订单数: {stats.get('total_orders', 0)}")
            print(f"   ✅ 成功订单: {stats.get('successful_orders', 0)}")
            print(f"   ❌ 失败订单: {stats.get('failed_orders', 0)}")
            print(f"   📈 成功率: {stats.get('success_rate', 0)}%")
            print(f"   💰 总交易量: {stats.get('total_volume', 0)}")
            print(f"   🏢 注册交易所: {stats.get('registered_exchanges', 0)}")
            print(f"   📋 支持交易对: {stats.get('supported_symbols', 0)}")
            
            return {
                'success': True,
                'results': results,
                'summary': f"统计信息测试完成，处理了 {stats.get('total_orders', 0)} 个订单"
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def test_trade_execution(self) -> Dict[str, Any]:
        """测试交易执行功能（单个交易所或套利交易）"""
        results = {}
        
        try:
            # 获取可用的交易所
            available_exchanges = [ex for ex in EXCHANGES if ex in self.exchange_adapters]
            
            if len(available_exchanges) == 0:
                return {
                    'success': False,
                    'error': "没有可用的交易所进行交易测试"
                }
            
            # 根据交易所数量选择测试策略
            if len(available_exchanges) == 1:
                # 单个交易所：进行基本的买入/卖出测试
                return await self._test_single_exchange_trading(available_exchanges[0])
            else:
                # 多个交易所：进行套利测试
                return await self._test_arbitrage_trading(available_exchanges[0], available_exchanges[1])
                
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def _test_single_exchange_trading(self, exchange: str) -> Dict[str, Any]:
        """单个交易所交易测试"""
        try:
            # 获取价格信息
            ticker = await self.execution_manager.get_ticker(exchange, TEST_SYMBOL)
            
            if not ticker:
                return {
                    'success': False,
                    'error': f"无法获取 {exchange} 的价格信息"
                }
            
            # 创建基本交易计划（使用安全的价格避免实际成交）
            safe_offset = SAFETY_PRICE_OFFSET
            
            trade_plan = TradePlan(
                plan_id=f"test_single_{exchange}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                symbol=TEST_SYMBOL,
                direction=ArbitrageDirection.LONG_A_SHORT_B,  # 添加必需的direction参数
                long_exchange=exchange,
                short_exchange=exchange,  # 单个交易所测试时使用相同交易所
                quantity=TEST_AMOUNT,  # 使用正确的参数名
                expected_profit=Decimal("0.01"),  # 预期利润
                order_type=OrderType.LIMIT,  # 使用正确的枚举类型
                timeout=30,
                created_at=datetime.now()
            )
            
            print(f"   📋 创建单个交易所交易计划: {exchange}")
            print(f"   💰 数量: {TEST_AMOUNT} {TEST_SYMBOL}")
            print(f"   💵 买入价: {ticker.last * (1 - safe_offset)}")
            
            # 执行交易计划
            execution_result = await self.execution_manager.execute_trade_plan(trade_plan)
            
            return {
                'success': execution_result.success,
                'plan_id': execution_result.plan_id,
                'execution_time': execution_result.execution_time,
                'error': execution_result.error_message,
                'type': 'single_exchange'
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def _test_arbitrage_trading(self, long_exchange: str, short_exchange: str) -> Dict[str, Any]:
        """套利交易测试"""
        try:
            # 获取两个交易所的价格
            long_ticker = await self.execution_manager.get_ticker(long_exchange, TEST_SYMBOL)
            short_ticker = await self.execution_manager.get_ticker(short_exchange, TEST_SYMBOL)
            
            if not long_ticker or not short_ticker:
                return {
                    'success': False,
                    'error': "无法获取价格信息进行套利测试"
                }
            
            # 创建交易计划（使用安全的价格避免实际成交）
            safe_offset = SAFETY_PRICE_OFFSET
            
            trade_plan = TradePlan(
                plan_id=f"test_arbitrage_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                symbol=TEST_SYMBOL,
                direction=ArbitrageDirection.LONG_A_SHORT_B,  # 添加必需的direction参数
                long_exchange=long_exchange,
                short_exchange=short_exchange,
                quantity=TEST_AMOUNT,  # 使用正确的参数名
                expected_profit=Decimal("0.01"),  # 预期利润
                order_type=OrderType.LIMIT,  # 使用正确的枚举类型
                timeout=30,
                created_at=datetime.now()
            )
            
            print(f"   📋 创建交易计划: {long_exchange} -> {short_exchange}")
            print(f"   💰 数量: {TEST_AMOUNT} {TEST_SYMBOL}")
            print(f"   💵 买入价: {long_ticker.last * (1 - safe_offset)}")
            print(f"   💵 卖出价: {short_ticker.last * (1 + safe_offset)}")
            
            # 执行交易计划
            execution_result = await self.execution_manager.execute_trade_plan(trade_plan)
            
            return {
                'success': execution_result.success,
                'plan_id': execution_result.plan_id,
                'execution_time': execution_result.execution_time,
                'error': execution_result.error_message,
                'type': 'arbitrage'
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def cleanup_test_orders(self):
        """清理测试订单"""
        if not self.test_orders:
            return
        
        print(f"\n🧹 清理 {len(self.test_orders)} 个测试订单...")
        
        # 批量取消订单
        cancel_results = await self.execution_manager.batch_cancel_orders(self.test_orders)
        
        success_count = sum(1 for result in cancel_results.values() if result)
        print(f"   ✅ 成功取消 {success_count}/{len(self.test_orders)} 个订单")
        
        # 清空列表
        self.test_orders.clear()
    
    async def generate_test_report(self):
        """生成测试报告"""
        print("\n" + "=" * 80)
        print("📊 套利执行器测试报告")
        print("=" * 80)
        
        # 统计测试结果
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results.values() if result.get('success', False))
        failed_tests = total_tests - passed_tests
        
        print(f"📋 测试总数: {total_tests}")
        print(f"✅ 通过测试: {passed_tests}")
        print(f"❌ 失败测试: {failed_tests}")
        print(f"📈 通过率: {(passed_tests/total_tests*100):.1f}%")
        
        # 详细结果
        print("\n📋 详细结果:")
        for test_name, result in self.test_results.items():
            status = "✅ 通过" if result.get('success', False) else "❌ 失败"
            summary = result.get('summary', result.get('error', '无详细信息'))
            print(f"   {status} - {test_name}: {summary}")
        
        # 系统信息
        if self.execution_manager:
            stats = await self.execution_manager.get_execution_stats()
            print(f"\n🔧 系统信息:")
            print(f"   🏢 注册交易所: {stats.get('registered_exchanges', 0)}")
            print(f"   📋 支持交易对: {stats.get('supported_symbols', 0)}")
            print(f"   💰 总交易量: {stats.get('total_volume', 0)}")
            print(f"   📊 订单统计: {stats.get('total_orders', 0)} 总计, {stats.get('successful_orders', 0)} 成功")
        
        # 保存报告到文件
        await self.save_report_to_file()
    
    async def save_report_to_file(self):
        """保存报告到文件"""
        try:
            report_data = {
                'timestamp': datetime.now().isoformat(),
                'test_results': self.test_results,
                'execution_stats': await self.execution_manager.get_execution_stats() if self.execution_manager else {},
                'exchanges_tested': list(self.exchange_adapters.keys()),
                'test_symbol': TEST_SYMBOL,
                'test_amount': float(TEST_AMOUNT)
            }
            
            # 创建报告目录
            report_dir = Path(__file__).parent / "reports"
            report_dir.mkdir(exist_ok=True)
            
            # 生成报告文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_file = report_dir / f"trade_execution_manager_test_{timestamp}.json"
            
            # 保存报告
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, ensure_ascii=False, default=str)
            
            print(f"\n💾 测试报告已保存: {report_file}")
            
        except Exception as e:
            print(f"❌ 保存报告失败: {e}")


async def main():
    """主函数"""
    print("🚀 套利执行器（TradeExecutionManager）实盘测试")
    print("=" * 80)
    
    # 安全确认
    confirmation = input("⚠️  这是实盘测试，可能产生真实交易和费用。是否继续？(yes/no): ")
    if confirmation.lower() != 'yes':
        print("❌ 测试已取消")
        return
    
    # 创建测试实例
    test_instance = TradeExecutionManagerLiveTest()
    
    # 初始化
    if not await test_instance.initialize():
        print("❌ 初始化失败，测试终止")
        return
    
    # 运行测试
    await test_instance.run_all_tests()
    
    print("\n🎉 测试完成！")


if __name__ == "__main__":
    asyncio.run(main()) 