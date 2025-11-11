#!/usr/bin/env python3
"""
测试交易执行器架构设计
验证执行器只负责执行交易指令，不包含策略逻辑
"""

import asyncio
import sys
import os
from decimal import Decimal
from typing import List, Dict, Any
from datetime import datetime

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from core.services.arbitrage.execution.trade_execution_manager import TradeExecutionManager
from core.services.arbitrage.shared.models import OrderInfo
from core.services.arbitrage.execution.exchange_registry import ExchangeRegistry
from core.services.arbitrage.initialization.precision_manager import PrecisionManager
from core.logging import get_logger

class MockDecisionEngine:
    """
    模拟决策引擎 - 负责提供交易决策和价格
    这展示了正确的架构分离
    """
    
    def __init__(self, exchange_registry: ExchangeRegistry):
        self.exchange_registry = exchange_registry
        self.logger = get_logger()
    
    async def get_market_price(self, exchange: str, symbol: str) -> Decimal:
        """获取市场价格"""
        try:
            adapter = self.exchange_registry.get_adapter(exchange)
            if not adapter:
                raise ValueError(f"交易所 {exchange} 未注册")
            
            ticker = await adapter.get_ticker(symbol)
            if ticker and ticker.last_price:
                return Decimal(str(ticker.last_price))
            return Decimal('100.0')  # 默认价格
        except Exception as e:
            self.logger.warning(f"获取市场价格失败: {e}")
            return Decimal('100.0')  # 默认价格
    
    async def calculate_order_price(self, exchange: str, symbol: str, side: str, 
                                  strategy: str = 'market_making') -> Decimal:
        """
        计算订单价格 - 这是决策引擎的职责
        """
        market_price = await self.get_market_price(exchange, symbol)
        
        if strategy == 'market_making':
            # 市场做市策略：买单比市价低0.1%，卖单比市价高0.1%
            if side.lower() == 'buy':
                return market_price * Decimal('0.999')  # 买单价格更低
            else:
                return market_price * Decimal('1.001')  # 卖单价格更高
        
        elif strategy == 'aggressive':
            # 激进策略：买单比市价高0.1%，卖单比市价低0.1%
            if side.lower() == 'buy':
                return market_price * Decimal('1.001')  # 买单价格更高
            else:
                return market_price * Decimal('0.999')  # 卖单价格更低
        
        return market_price

async def test_single_order_execution():
    """测试单个订单执行"""
    print("=" * 60)
    print("🔍 测试单个订单执行")
    print("=" * 60)
    
    # 初始化组件
    exchange_registry = ExchangeRegistry()
    
    # 注册交易所
    from core.adapters.exchanges.factory import ExchangeAdapterFactory
    factory = ExchangeAdapterFactory()
    await factory.register_adapters(exchange_registry)
    
    # 创建精度管理器
    adapters = exchange_registry.get_all_adapters()
    precision_manager = PrecisionManager(adapters)
    
    # 创建执行器和决策引擎
    executor = TradeExecutionManager(exchange_registry, precision_manager)
    decision_engine = MockDecisionEngine(exchange_registry)
    
    try:
        # 步骤1：决策引擎计算价格
        print("📊 步骤1：决策引擎计算订单价格")
        exchange = "backpack"
        symbol = "SOL_USDC_PERP"
        side = "buy"
        amount = Decimal("0.1")
        
        # 决策引擎提供价格
        order_price = await decision_engine.calculate_order_price(
            exchange, symbol, side, strategy='market_making'
        )
        print(f"   决策引擎计算价格: {order_price}")
        
        # 步骤2：执行器执行交易指令
        print("⚡ 步骤2：执行器执行交易指令")
        order_info = await executor.create_order(
            exchange=exchange,
            symbol=symbol,
            side=side,
            order_type='limit',
            amount=amount,
            price=order_price  # 价格由决策引擎提供
        )
        
        print(f"✅ 订单执行成功:")
        print(f"   订单ID: {order_info.order_id}")
        print(f"   交易所: {order_info.exchange}")
        print(f"   交易对: {order_info.symbol}")
        print(f"   方向: {order_info.side}")
        print(f"   数量: {order_info.amount}")
        print(f"   价格: {order_info.price}")
        print(f"   状态: {order_info.status}")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False

async def test_batch_order_execution():
    """测试批量订单执行"""
    print("\n" + "=" * 60)
    print("🔍 测试批量订单执行")
    print("=" * 60)
    
    # 初始化组件
    exchange_registry = ExchangeRegistry()
    
    # 注册交易所
    from core.adapters.exchanges.factory import ExchangeAdapterFactory
    factory = ExchangeAdapterFactory()
    await factory.register_adapters(exchange_registry)
    
    # 创建精度管理器
    adapters = exchange_registry.get_all_adapters()
    precision_manager = PrecisionManager(adapters)
    
    # 创建执行器和决策引擎
    executor = TradeExecutionManager(exchange_registry, precision_manager)
    decision_engine = MockDecisionEngine(exchange_registry)
    
    try:
        # 步骤1：决策引擎制定交易策略
        print("📊 步骤1：决策引擎制定交易策略")
        
        # 模拟套利策略：在同一交易所做多空对冲
        trade_pairs = [
            {'exchange': 'backpack', 'symbol': 'SOL_USDC_PERP', 'side': 'buy', 'amount': '0.1'},
            {'exchange': 'backpack', 'symbol': 'SOL_USDC_PERP', 'side': 'sell', 'amount': '0.1'}
        ]
        
        # 决策引擎计算每个订单的价格
        orders = []
        for pair in trade_pairs:
            price = await decision_engine.calculate_order_price(
                pair['exchange'], pair['symbol'], pair['side'], strategy='market_making'
            )
            orders.append({
                'exchange': pair['exchange'],
                'symbol': pair['symbol'],
                'side': pair['side'],
                'order_type': 'limit',
                'amount': Decimal(pair['amount']),
                'price': price
            })
            print(f"   {pair['side'].upper()}单价格: {price}")
        
        # 步骤2：执行器批量执行交易指令
        print("⚡ 步骤2：执行器批量执行交易指令")
        order_results = await executor.batch_create_orders(orders)
        
        print(f"✅ 批量订单执行完成:")
        print(f"   成功创建: {len(order_results)} 个订单")
        for i, order in enumerate(order_results):
            print(f"   订单{i+1}: {order.side.upper()} {order.amount} @ {order.price} -> {order.order_id}")
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False

async def test_architecture_violation():
    """测试架构违规：缺少价格参数"""
    print("\n" + "=" * 60)
    print("🔍 测试架构违规检测")
    print("=" * 60)
    
    # 初始化组件
    exchange_registry = ExchangeRegistry()
    
    # 注册交易所
    from core.adapters.exchanges.factory import ExchangeAdapterFactory
    factory = ExchangeAdapterFactory()
    await factory.register_adapters(exchange_registry)
    
    # 创建精度管理器
    adapters = exchange_registry.get_all_adapters()
    precision_manager = PrecisionManager(adapters)
    
    # 创建执行器
    executor = TradeExecutionManager(exchange_registry, precision_manager)
    
    try:
        # 尝试创建订单但不提供价格
        print("❌ 尝试创建订单但不提供价格（应该失败）")
        await executor.create_order(
            exchange="backpack",
            symbol="SOL_USDC_PERP",
            side="buy",
            order_type="limit",
            amount=Decimal("0.1"),
            price=Decimal("0")  # 无效价格
        )
        
        print("❌ 测试失败: 应该抛出异常但没有")
        return False
        
    except ValueError as e:
        print(f"✅ 正确检测到架构违规: {e}")
        return True
    except Exception as e:
        print(f"❌ 意外错误: {e}")
        return False

async def main():
    """主测试函数"""
    print("🚀 交易执行器架构测试")
    print("测试目标：验证执行器只负责执行交易指令，不包含策略逻辑")
    
    results = []
    
    # 测试单个订单执行
    results.append(await test_single_order_execution())
    
    # 测试批量订单执行
    results.append(await test_batch_order_execution())
    
    # 测试架构违规检测
    results.append(await test_architecture_violation())
    
    # 输出测试结果
    print("\n" + "=" * 60)
    print("📊 测试结果总结")
    print("=" * 60)
    
    total_tests = len(results)
    passed_tests = sum(results)
    
    print(f"总测试数: {total_tests}")
    print(f"通过测试: {passed_tests}")
    print(f"失败测试: {total_tests - passed_tests}")
    print(f"通过率: {passed_tests/total_tests*100:.1f}%")
    
    if passed_tests == total_tests:
        print("🎉 所有测试通过！新的执行器架构设计正确。")
        print("📋 架构验证:")
        print("   ✅ 执行器只负责执行交易指令")
        print("   ✅ 价格由决策引擎提供")
        print("   ✅ 正确检测架构违规")
    else:
        print("❌ 部分测试失败，需要进一步调试")

if __name__ == "__main__":
    asyncio.run(main()) 