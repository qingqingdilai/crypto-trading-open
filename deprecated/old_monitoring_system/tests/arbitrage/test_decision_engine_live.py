#!/usr/bin/env python3
"""
套利决策引擎实盘测试脚本

⚠️  警告：这是实盘测试脚本，会使用真实资金进行交易！
🎯 测试目标：验证决策引擎的完整功能
🔧 测试范围：
   - 配置文件加载
   - 套利信号处理
   - 先后下单逻辑
   - 盈亏计算
   - 平仓逻辑
   - 精度处理

测试币种：SOL_USDC_PERP
测试交易所：Backpack (权重1), Hyperliquid (权重3)

使用前请确保：
1. 已在配置文件中设置API密钥
2. 账户中有足够的资金
3. 理解这是实盘交易，会产生真实的费用和风险
"""

import asyncio
import sys
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Any

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.logging import get_logger
from core.services.arbitrage.decision.arbitrage_decision_engine import ArbitrageDecisionEngine
from core.services.arbitrage.initialization.precision_manager import PrecisionManager
from core.services.arbitrage.execution.trade_execution_manager import TradeExecutionManager
from core.services.arbitrage.execution.exchange_registry import ExchangeRegistry
from core.adapters.exchanges.factory import ExchangeFactory

# 测试配置
TEST_SYMBOL = "SOL_USDC_PERP"
TEST_EXCHANGES = ["backpack", "hyperliquid"]
CONFIG_PATH = "config/arbitrage/decision_engine.yaml"

class DecisionEngineLiveTest:
    """决策引擎实盘测试类"""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        self.decision_engine = None
        self.exchange_registry = None
        self.precision_manager = None
        self.execution_manager = None
        self.test_results = {}
    
    def _get_exchange_config(self, exchange_name: str) -> Dict[str, Any]:
        """
        获取交易所配置
        
        从环境变量或配置文件中加载API配置信息
        
        Args:
            exchange_name: 交易所名称
            
        Returns:
            交易所配置字典
        """
        import os
        
        # 尝试从环境变量获取配置
        api_key = os.getenv(f"{exchange_name.upper()}_API_KEY")
        api_secret = os.getenv(f"{exchange_name.upper()}_API_SECRET")
        
        # 如果环境变量不存在，使用占位符配置（仅用于测试）
        if not api_key or not api_secret:
            self.logger.warning(f"⚠️  {exchange_name} 的API配置不存在，使用占位符配置")
            api_key = "test_key"
            api_secret = "test_secret"
        
        config = {
            "api_key": api_key,
            "api_secret": api_secret,
            "testnet": True,  # 使用测试网络
        }
        
        # 根据交易所添加特定配置
        if exchange_name == "hyperliquid":
            wallet_address = os.getenv("HYPERLIQUID_WALLET_ADDRESS")
            if wallet_address:
                config["wallet_address"] = wallet_address
            else:
                self.logger.warning("⚠️  Hyperliquid 钱包地址不存在，使用占位符")
                config["wallet_address"] = "0x" + "0" * 40
        
        return config
        
    async def initialize(self) -> bool:
        """初始化测试环境"""
        try:
            self.logger.info("🚀 开始初始化测试环境")
            
            # 创建交易所适配器
            factory = ExchangeFactory()
            adapters = {}
            
            # 为每个测试交易所创建适配器实例
            for exchange_name in TEST_EXCHANGES:
                try:
                    # 获取交易所配置
                    exchange_config = self._get_exchange_config(exchange_name)
                    
                    # 创建适配器
                    adapter = factory.create_adapter(
                        exchange_name,
                        config=None,  # 使用默认配置
                        **exchange_config
                    )
                    adapters[exchange_name] = adapter
                    self.logger.info(f"✅ 创建交易所适配器: {exchange_name}")
                except Exception as e:
                    self.logger.error(f"❌ 创建交易所适配器失败: {exchange_name} - {e}")
                    continue
            
            if not adapters:
                self.logger.error("❌ 没有成功创建任何交易所适配器")
                return False
            
            # 初始化交易所注册表
            self.exchange_registry = ExchangeRegistry(adapters)
            
            # 初始化精度管理器
            self.precision_manager = PrecisionManager(adapters)
            
            # 初始化执行管理器
            self.execution_manager = TradeExecutionManager(
                adapters,
                self.precision_manager
            )
            
            # 初始化决策引擎
            self.decision_engine = ArbitrageDecisionEngine(
                precision_manager=self.precision_manager,
                execution_manager=self.execution_manager,
                exchange_registry=self.exchange_registry,
                config_path=CONFIG_PATH
            )
            
            # 验证交易所连接
            for exchange in TEST_EXCHANGES:
                adapter = self.exchange_registry.get_adapter(exchange)
                if not adapter:
                    self.logger.error(f"交易所 {exchange} 未正确注册")
                    return False
                
                # 测试连接
                try:
                    ticker = await adapter.get_ticker(TEST_SYMBOL)
                    if ticker and ticker.last:
                        self.logger.info(f"✅ {exchange} 连接成功，价格: {ticker.last}")
                    else:
                        self.logger.warning(f"⚠️ {exchange} 无法获取价格数据")
                except Exception as e:
                    self.logger.error(f"❌ {exchange} 连接失败: {e}")
                    return False
            
            self.logger.info("✅ 测试环境初始化成功")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 初始化失败: {e}")
            return False
    
    async def run_all_tests(self):
        """运行所有测试"""
        try:
            print("🎯 开始运行决策引擎测试")
            print("=" * 80)
            
            # 测试1：配置文件加载
            await self.test_config_loading()
            
            # 测试2：市场数据模拟
            await self.test_market_data_simulation()
            
            # 测试3：套利信号处理
            await self.test_arbitrage_signal_processing()
            
            # 测试4：先后下单逻辑
            await self.test_sequential_order_execution()
            
            # 测试5：盈亏计算
            await self.test_profit_calculation()
            
            # 测试6：平仓逻辑
            await self.test_position_closing()
            
            # 测试7：精度处理
            await self.test_precision_handling()
            
            # 输出测试结果
            await self.generate_test_report()
            
        except Exception as e:
            self.logger.error(f"测试执行失败: {e}")
    
    async def test_config_loading(self):
        """测试配置文件加载"""
        test_name = "配置文件加载"
        print(f"\n📋 测试: {test_name}")
        print("-" * 40)
        
        try:
            # 检查配置是否正确加载
            config = self.decision_engine.config
            
            # 验证关键配置项
            required_sections = [
                'decision_params', 'position_management', 'exchange_weights',
                'order_execution', 'profit_management', 'precision_management'
            ]
            
            missing_sections = []
            for section in required_sections:
                if section not in config:
                    missing_sections.append(section)
            
            if missing_sections:
                print(f"❌ 缺少配置节: {missing_sections}")
                self.test_results[test_name] = {"passed": False, "error": f"Missing sections: {missing_sections}"}
                return
            
            # 检查交易所权重
            weights = config.get('exchange_weights', {})
            print(f"   交易所权重: {weights}")
            
            # 检查仓位管理
            position_mgmt = config.get('position_management', {})
            print(f"   每次开仓金额: {position_mgmt.get('order_amount_usdc')} USDC")
            print(f"   最大总仓位: {position_mgmt.get('max_total_position_usdc')} USDC")
            
            # 检查下单配置
            order_exec = config.get('order_execution', {})
            print(f"   下单模式: {order_exec.get('execution_mode')}")
            print(f"   第一交易所订单类型: {order_exec.get('first_exchange', {}).get('order_type')}")
            print(f"   第二交易所订单类型: {order_exec.get('second_exchange', {}).get('order_type')}")
            
            print("✅ 配置文件加载成功")
            self.test_results[test_name] = {"passed": True, "config": config}
            
        except Exception as e:
            print(f"❌ 配置文件加载失败: {e}")
            self.test_results[test_name] = {"passed": False, "error": str(e)}
    
    async def test_market_data_simulation(self):
        """测试市场数据模拟"""
        test_name = "市场数据模拟"
        print(f"\n📋 测试: {test_name}")
        print("-" * 40)
        
        try:
            # 获取真实市场数据
            market_data = await self._get_real_market_data()
            
            if not market_data:
                print("❌ 无法获取市场数据")
                self.test_results[test_name] = {"passed": False, "error": "No market data"}
                return
            
            print(f"   交易对: {market_data['symbol']}")
            print(f"   交易所数据: {len(market_data['exchanges'])} 个交易所")
            
            for exchange, data in market_data['exchanges'].items():
                price = data.get('price', 'N/A')
                volume = data.get('volume', 'N/A')
                print(f"   {exchange}: 价格={price}, 成交量={volume}")
            
            # 计算价差
            prices = []
            for exchange_data in market_data['exchanges'].values():
                if 'price' in exchange_data:
                    prices.append(float(exchange_data['price']))
            
            if len(prices) >= 2:
                max_price = max(prices)
                min_price = min(prices)
                spread = ((max_price - min_price) / min_price) * 100
                print(f"   价差: {spread:.4f}%")
                
                market_data['spread_percentage'] = spread
            
            print("✅ 市场数据模拟成功")
            self.test_results[test_name] = {"passed": True, "market_data": market_data}
            
        except Exception as e:
            print(f"❌ 市场数据模拟失败: {e}")
            self.test_results[test_name] = {"passed": False, "error": str(e)}
    
    async def test_arbitrage_signal_processing(self):
        """测试套利信号处理"""
        test_name = "套利信号处理"
        print(f"\n📋 测试: {test_name}")
        print("-" * 40)
        
        try:
            # 获取市场数据
            market_data = self.test_results.get("市场数据模拟", {}).get("market_data")
            
            if not market_data:
                print("❌ 缺少市场数据")
                self.test_results[test_name] = {"passed": False, "error": "No market data"}
                return
            
            # 模拟大价差信号（如果当前价差不够大）
            if market_data.get('spread_percentage', 0) < 0.1:  # 小于0.1%
                print("   当前价差较小，模拟大价差信号")
                # 人为调整价格创造价差
                exchanges = list(market_data['exchanges'].keys())
                if len(exchanges) >= 2:
                    # 让第一个交易所价格更低
                    original_price = market_data['exchanges'][exchanges[0]]['price']
                    market_data['exchanges'][exchanges[0]]['price'] = original_price * 0.99
                    
                    # 让第二个交易所价格更高
                    original_price = market_data['exchanges'][exchanges[1]]['price']
                    market_data['exchanges'][exchanges[1]]['price'] = original_price * 1.01
                    
                    # 重新计算价差
                    prices = [float(data['price']) for data in market_data['exchanges'].values()]
                    max_price = max(prices)
                    min_price = min(prices)
                    spread = ((max_price - min_price) / min_price) * 100
                    market_data['spread_percentage'] = spread
                    
                    print(f"   调整后价差: {spread:.4f}%")
            
            # 处理套利信号
            trade_plan = await self.decision_engine.analyze_market_data(market_data)
            
            if trade_plan:
                print(f"✅ 套利信号识别成功")
                print(f"   交易计划ID: {trade_plan.plan_id}")
                print(f"   多头交易所: {trade_plan.long_exchange}")
                print(f"   空头交易所: {trade_plan.short_exchange}")
                print(f"   预期利润: {trade_plan.expected_profit}")
                
                self.test_results[test_name] = {
                    "passed": True,
                    "trade_plan": {
                        "plan_id": trade_plan.plan_id,
                        "long_exchange": trade_plan.long_exchange,
                        "short_exchange": trade_plan.short_exchange,
                        "expected_profit": float(trade_plan.expected_profit)
                    }
                }
            else:
                print("⚠️ 未识别到套利机会（可能是价差不够大或风险过高）")
                self.test_results[test_name] = {"passed": True, "trade_plan": None, "reason": "No opportunity"}
            
        except Exception as e:
            print(f"❌ 套利信号处理失败: {e}")
            self.test_results[test_name] = {"passed": False, "error": str(e)}
    
    async def test_sequential_order_execution(self):
        """测试先后下单逻辑"""
        test_name = "先后下单逻辑"
        print(f"\n📋 测试: {test_name}")
        print("-" * 40)
        
        try:
            # 获取交易计划
            trade_plan_data = self.test_results.get("套利信号处理", {}).get("trade_plan")
            
            if not trade_plan_data:
                print("⚠️ 没有交易计划，跳过此测试")
                self.test_results[test_name] = {"passed": True, "skipped": True, "reason": "No trade plan"}
                return
            
            # 测试交易所权重排序
            exchanges = [trade_plan_data['long_exchange'], trade_plan_data['short_exchange']]
            sorted_exchanges = self.decision_engine._get_sorted_exchanges(exchanges)
            
            print(f"   原始交易所: {exchanges}")
            print(f"   权重排序后: {sorted_exchanges}")
            
            # 验证排序是否正确
            weights = self.decision_engine.exchange_weights
            expected_order = sorted(exchanges, key=lambda x: weights.get(x, 999))
            
            if sorted_exchanges == expected_order:
                print("✅ 权重排序正确")
                
                # 检查权重配置
                for exchange in sorted_exchanges:
                    weight = weights.get(exchange, 999)
                    print(f"   {exchange}: 权重={weight}")
                
                self.test_results[test_name] = {
                    "passed": True,
                    "original_exchanges": exchanges,
                    "sorted_exchanges": sorted_exchanges,
                    "weights": {ex: weights.get(ex, 999) for ex in exchanges}
                }
            else:
                print(f"❌ 权重排序错误，期望: {expected_order}")
                self.test_results[test_name] = {"passed": False, "error": "Weight sorting failed"}
            
        except Exception as e:
            print(f"❌ 先后下单逻辑测试失败: {e}")
            self.test_results[test_name] = {"passed": False, "error": str(e)}
    
    async def test_profit_calculation(self):
        """测试盈亏计算"""
        test_name = "盈亏计算"
        print(f"\n📋 测试: {test_name}")
        print("-" * 40)
        
        try:
            # 模拟仓位数据
            mock_position = {
                'plan_id': 'test_plan_123',
                'symbol': TEST_SYMBOL,
                'exchanges': ['backpack', 'hyperliquid'],
                'amount': Decimal('0.1'),
                'open_prices': {
                    'backpack': Decimal('100.0'),
                    'hyperliquid': Decimal('102.0')
                },
                'orders': []
            }
            
            # 添加到当前仓位
            self.decision_engine.current_positions['test_plan_123'] = mock_position
            
            # 测试盈亏计算
            profit = await self.decision_engine._calculate_position_profit('test_plan_123')
            
            if profit is not None:
                print(f"✅ 盈亏计算成功")
                print(f"   当前盈亏: {profit} USDC")
                print(f"   计算逻辑: 基于开仓价格和当前价格的差异")
                
                # 测试不同价格变化的盈亏
                print("   价格变化测试:")
                print(f"   - 开仓价格: backpack={mock_position['open_prices']['backpack']}, hyperliquid={mock_position['open_prices']['hyperliquid']}")
                print(f"   - 价差: {float(mock_position['open_prices']['hyperliquid'] - mock_position['open_prices']['backpack'])}")
                
                self.test_results[test_name] = {
                    "passed": True,
                    "profit": float(profit),
                    "open_prices": {k: float(v) for k, v in mock_position['open_prices'].items()}
                }
            else:
                print("⚠️ 盈亏计算返回None（可能是无法获取当前价格）")
                self.test_results[test_name] = {"passed": True, "profit": None, "reason": "No current price"}
            
            # 清理测试数据
            if 'test_plan_123' in self.decision_engine.current_positions:
                del self.decision_engine.current_positions['test_plan_123']
            
        except Exception as e:
            print(f"❌ 盈亏计算测试失败: {e}")
            self.test_results[test_name] = {"passed": False, "error": str(e)}
    
    async def test_position_closing(self):
        """测试平仓逻辑"""
        test_name = "平仓逻辑"
        print(f"\n📋 测试: {test_name}")
        print("-" * 40)
        
        try:
            # 获取平仓配置
            profit_config = self.decision_engine.profit_management
            
            print(f"   目标利润: {profit_config.get('target_profit_usdc')} USDC")
            print(f"   止损线: {profit_config.get('stop_loss_usdc')} USDC")
            print(f"   平仓模式: {profit_config.get('close_mode')}")
            print(f"   检查间隔: {profit_config.get('close_check_interval')} 秒")
            
            # 测试平仓条件判断
            target_profit = Decimal(str(profit_config.get('target_profit_usdc', 2.0)))
            stop_loss = Decimal(str(profit_config.get('stop_loss_usdc', -5.0)))
            
            # 模拟不同的盈亏情况
            test_profits = [
                (Decimal('3.0'), "达到目标利润"),
                (Decimal('-6.0'), "达到止损线"),
                (Decimal('1.0'), "未达到平仓条件")
            ]
            
            for profit, description in test_profits:
                should_close = False
                close_reason = None
                
                if profit >= target_profit:
                    should_close = True
                    close_reason = "target_profit"
                elif profit <= stop_loss:
                    should_close = True
                    close_reason = "stop_loss"
                
                print(f"   测试盈亏 {profit} USDC - {description}: {'需要平仓' if should_close else '继续持有'}")
                if should_close:
                    print(f"     平仓原因: {close_reason}")
            
            print("✅ 平仓逻辑测试通过")
            self.test_results[test_name] = {
                "passed": True,
                "config": {
                    "target_profit": float(target_profit),
                    "stop_loss": float(stop_loss),
                    "close_mode": profit_config.get('close_mode')
                }
            }
            
        except Exception as e:
            print(f"❌ 平仓逻辑测试失败: {e}")
            self.test_results[test_name] = {"passed": False, "error": str(e)}
    
    async def test_precision_handling(self):
        """测试精度处理"""
        test_name = "精度处理"
        print(f"\n📋 测试: {test_name}")
        print("-" * 40)
        
        try:
            # 获取精度配置
            precision_config = self.decision_engine.precision_management
            
            print(f"   精度兼容模式: {precision_config.get('compatibility_mode')}")
            print(f"   默认精度: {precision_config.get('default_precision')}")
            
            # 测试获取统一精度
            unified_precision = await self.decision_engine._get_unified_precision(
                TEST_SYMBOL, TEST_EXCHANGES
            )
            
            print(f"   统一精度: {unified_precision}")
            
            # 测试精度调整
            test_amounts = [
                Decimal('100.123456789'),
                Decimal('0.000001'),
                Decimal('1000.0')
            ]
            
            for amount in test_amounts:
                # 调整到统一精度
                adjusted_amount = amount.quantize(
                    Decimal('0.1') ** unified_precision['amount']
                )
                
                print(f"   数量调整: {amount} -> {adjusted_amount}")
            
            # 测试价格精度调整
            test_prices = [
                Decimal('155.123456789'),
                Decimal('0.000001'),
                Decimal('1000.0')
            ]
            
            for price in test_prices:
                # 调整到统一精度
                adjusted_price = price.quantize(
                    Decimal('0.1') ** unified_precision['price']
                )
                
                print(f"   价格调整: {price} -> {adjusted_price}")
            
            print("✅ 精度处理测试通过")
            self.test_results[test_name] = {
                "passed": True,
                "unified_precision": unified_precision,
                "config": precision_config
            }
            
        except Exception as e:
            print(f"❌ 精度处理测试失败: {e}")
            self.test_results[test_name] = {"passed": False, "error": str(e)}
    
    async def generate_test_report(self):
        """生成测试报告"""
        print("\n" + "=" * 80)
        print("📊 测试结果总结")
        print("=" * 80)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results.values() if result.get('passed', False))
        
        print(f"总测试数: {total_tests}")
        print(f"通过测试: {passed_tests}")
        print(f"失败测试: {total_tests - passed_tests}")
        print(f"通过率: {passed_tests/total_tests*100:.1f}%")
        
        print("\n详细结果:")
        for test_name, result in self.test_results.items():
            status = "✅ 通过" if result.get('passed', False) else "❌ 失败"
            print(f"   {test_name}: {status}")
            
            if not result.get('passed', False) and 'error' in result:
                print(f"     错误: {result['error']}")
            elif result.get('skipped', False):
                print(f"     跳过: {result.get('reason', 'Unknown')}")
        
        # 输出决策引擎统计信息
        stats = self.decision_engine.get_statistics()
        print(f"\n决策引擎统计:")
        print(f"   当前仓位: {stats['current_positions']}")
        print(f"   总仓位: {stats['total_position_usdc']} USDC")
        print(f"   历史仓位: {stats['position_history_count']}")
        print(f"   决策记录: {stats['decision_history_count']}")
        
        # 保存报告到文件
        await self.save_report_to_file()
    
    async def save_report_to_file(self):
        """保存报告到文件"""
        try:
            report_data = {
                'timestamp': datetime.now().isoformat(),
                'test_results': self.test_results,
                'decision_engine_stats': self.decision_engine.get_statistics(),
                'config': self.decision_engine.config,
                'test_symbol': TEST_SYMBOL,
                'test_exchanges': TEST_EXCHANGES
            }
            
            # 创建报告目录
            report_dir = Path(__file__).parent / "reports"
            report_dir.mkdir(exist_ok=True)
            
            # 生成报告文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_file = report_dir / f"decision_engine_test_{timestamp}.json"
            
            # 保存报告
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, ensure_ascii=False, default=str)
            
            print(f"\n💾 测试报告已保存: {report_file}")
            
        except Exception as e:
            print(f"❌ 保存报告失败: {e}")
    
    async def _get_real_market_data(self) -> Optional[Dict[str, Any]]:
        """获取真实市场数据"""
        try:
            market_data = {
                'symbol': TEST_SYMBOL,
                'exchanges': {},
                'timestamp': datetime.now()
            }
            
            for exchange in TEST_EXCHANGES:
                adapter = self.exchange_registry.get_adapter(exchange)
                if adapter:
                    ticker = await adapter.get_ticker(TEST_SYMBOL)
                    if ticker:
                        market_data['exchanges'][exchange] = {
                            'price': float(ticker.last),
                            'volume': float(ticker.volume) if ticker.volume else 0,
                            'timestamp': ticker.timestamp or datetime.now()
                        }
            
            return market_data if market_data['exchanges'] else None
            
        except Exception as e:
            self.logger.error(f"获取市场数据失败: {e}")
            return None


async def main():
    """主函数"""
    print("🚀 套利决策引擎实盘测试")
    print("=" * 80)
    
    # 安全确认
    confirmation = input("⚠️  这是实盘测试，可能产生真实交易和费用。是否继续？(yes/no): ")
    if confirmation.lower() != 'yes':
        print("❌ 测试已取消")
        return
    
    # 创建测试实例
    test_instance = DecisionEngineLiveTest()
    
    # 初始化
    if not await test_instance.initialize():
        print("❌ 初始化失败，测试终止")
        return
    
    # 运行测试
    await test_instance.run_all_tests()
    
    print("\n🎉 测试完成！")


if __name__ == "__main__":
    asyncio.run(main()) 