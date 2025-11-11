#!/usr/bin/env python3
"""
符号格式转换测试脚本

测试执行器的统一符号格式转换功能，验证决策模块可以使用统一格式
而执行器能够正确转换为各个交易所的特定格式
"""

import asyncio
from decimal import Decimal
from typing import Dict, Any

from core.adapters.exchanges.factory import ExchangeFactory
from core.services.arbitrage.execution.trade_execution_manager import TradeExecutionManager
from core.services.arbitrage.initialization.precision_manager import PrecisionManager


class MockExchangeInterface:
    """模拟交易所接口，用于测试符号格式转换"""
    
    def __init__(self, exchange_name: str):
        self.exchange_name = exchange_name
        self.received_symbols = []
    
    async def create_order(self, symbol: str, side: str, order_type: str, 
                          amount: Decimal, price: Decimal = None) -> Dict[str, Any]:
        """记录接收到的符号格式"""
        self.received_symbols.append(symbol)
        print(f"📋 {self.exchange_name} 接收到符号: {symbol}")
        
        # 返回模拟订单结果
        return type('OrderResult', (), {
            'id': f"order_{len(self.received_symbols)}",
            'filled': 0,
            'status': 'pending',
            'timestamp': None
        })()


class MockPrecisionManager:
    """模拟精度管理器"""
    
    async def get_symbol_precision(self, exchange: str, symbol: str):
        """返回模拟精度信息"""
        return type('PrecisionInfo', (), {
            'amount_precision': 8,
            'price_precision': 8
        })()


async def test_symbol_format_conversion():
    """测试符号格式转换功能"""
    print("🔍 开始测试符号格式转换功能...")
    
    # 创建模拟适配器
    mock_adapters = {
        'hyperliquid': MockExchangeInterface('hyperliquid'),
        'backpack': MockExchangeInterface('backpack'),
        'edgex': MockExchangeInterface('edgex')
    }
    
    # 创建执行管理器
    execution_manager = TradeExecutionManager(
        exchange_adapters=mock_adapters,
        precision_manager=MockPrecisionManager()
    )
    
    # 测试用例：统一格式符号
    test_cases = [
        {
            'standard_symbol': 'BTC-USDC-PERP',
            'expected_results': {
                'hyperliquid': 'BTC/USDC:PERP',
                'backpack': 'BTC_USDC_PERP',
                'edgex': 'BTC_USDT_PERP'
            }
        },
        {
            'standard_symbol': 'ETH-USDC-PERP',
            'expected_results': {
                'hyperliquid': 'ETH/USDC:PERP',
                'backpack': 'ETH_USDC_PERP',
                'edgex': 'ETH_USDT_PERP'
            }
        },
        {
            'standard_symbol': 'SOL-USDC',
            'expected_results': {
                'hyperliquid': 'SOL/USDC',
                'backpack': 'SOL_USDC',
                'edgex': 'SOL_USDT_PERP'  # EdgeX只有永续合约
            }
        }
    ]
    
    print(f"\n🧪 测试 {len(test_cases)} 个符号格式转换用例...")
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n--- 测试用例 {i}: {test_case['standard_symbol']} ---")
        
        for exchange, expected_format in test_case['expected_results'].items():
            try:
                # 清空之前的记录
                mock_adapters[exchange].received_symbols = []
                
                # 创建订单（这会触发符号格式转换）
                await execution_manager.create_order(
                    exchange=exchange,
                    symbol=test_case['standard_symbol'],
                    side='buy',
                    order_type='limit',
                    amount=Decimal('1.0'),
                    price=Decimal('50000')
                )
                
                # 验证转换结果
                received_symbol = mock_adapters[exchange].received_symbols[-1]
                
                if received_symbol == expected_format:
                    print(f"✅ {exchange}: {test_case['standard_symbol']} -> {received_symbol} (正确)")
                else:
                    print(f"❌ {exchange}: {test_case['standard_symbol']} -> {received_symbol} (期望: {expected_format})")
                    
            except Exception as e:
                print(f"❌ {exchange}: 转换失败 - {e}")
    
    print(f"\n📊 符号格式转换测试完成！")


async def test_direct_conversion():
    """直接测试转换方法"""
    print("\n🔍 直接测试转换方法...")
    
    # 创建执行管理器
    execution_manager = TradeExecutionManager(
        exchange_adapters={},
        precision_manager=MockPrecisionManager()
    )
    
    # 测试转换方法
    test_symbols = ['BTC-USDC-PERP', 'ETH-USDC-PERP', 'SOL-USDC']
    
    for symbol in test_symbols:
        print(f"\n--- 测试符号: {symbol} ---")
        
        # 测试各个交易所的转换
        hyperliquid_result = execution_manager._convert_to_hyperliquid_format(symbol)
        backpack_result = execution_manager._convert_to_backpack_format(symbol)
        edgex_result = execution_manager._convert_to_edgex_format(symbol)
        
        print(f"Hyperliquid: {symbol} -> {hyperliquid_result}")
        print(f"Backpack: {symbol} -> {backpack_result}")
        print(f"EdgeX: {symbol} -> {edgex_result}")


if __name__ == "__main__":
    asyncio.run(test_symbol_format_conversion())
    asyncio.run(test_direct_conversion()) 