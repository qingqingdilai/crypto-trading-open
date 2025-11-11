"""
测试监控服务重构后的符号转换功能

验证监控服务是否正确使用统一的符号转换服务
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime
from decimal import Decimal

from core.services.implementations.enhanced_monitoring_service import EnhancedMonitoringServiceImpl
from core.services.symbol_manager.interfaces.symbol_conversion_service import ISymbolConversionService
from core.services.interfaces.config_service import IConfigurationService
from core.domain.models import PriceData, SpreadData
from core.adapters.exchanges.manager import ExchangeManager
from core.data_aggregator import DataAggregator


class TestMonitoringServiceRefactored:
    """测试重构后的监控服务"""
    
    @pytest.fixture
    def mock_exchange_manager(self):
        """模拟交易所管理器"""
        mock = Mock(spec=ExchangeManager)
        return mock
    
    @pytest.fixture
    def mock_data_aggregator(self):
        """模拟数据聚合器"""
        mock = Mock(spec=DataAggregator)
        return mock
    
    @pytest.fixture
    def mock_config_service(self):
        """模拟配置服务"""
        mock = Mock(spec=IConfigurationService)
        mock.initialize = AsyncMock(return_value=True)
        return mock
    
    @pytest.fixture
    def mock_symbol_conversion_service(self):
        """模拟符号转换服务"""
        mock = Mock(spec=ISymbolConversionService)
        
        # 设置模拟的符号转换规则
        async def mock_convert_from_exchange_format(symbol: str, exchange: str) -> str:
            """模拟符号转换：将交易所格式转换为标准格式"""
            if exchange == 'hyperliquid':
                if symbol == 'BTC/USDC:PERP':
                    return 'BTC-USDC-PERP'
                elif symbol == 'ETH/USDC:PERP':
                    return 'ETH-USDC-PERP'
            elif exchange == 'backpack':
                if symbol == 'BTC_USDC_PERP':
                    return 'BTC-USDC-PERP'
                elif symbol == 'ETH_USDC_PERP':
                    return 'ETH-USDC-PERP'
            elif exchange == 'edgex':
                if symbol == 'BTC_USDT_PERP':
                    return 'BTC-USDC-PERP'  # EdgeX的USDT映射到USDC
                elif symbol == 'ETH_USDT_PERP':
                    return 'ETH-USDC-PERP'
            
            return symbol
        
        mock.convert_from_exchange_format = AsyncMock(side_effect=mock_convert_from_exchange_format)
        return mock
    
    @pytest.fixture
    def monitoring_service(self, mock_exchange_manager, mock_data_aggregator, 
                          mock_config_service, mock_symbol_conversion_service):
        """创建监控服务实例"""
        return EnhancedMonitoringServiceImpl(
            exchange_manager=mock_exchange_manager,
            data_aggregator=mock_data_aggregator,
            config_service=mock_config_service,
            symbol_conversion_service=mock_symbol_conversion_service
        )
    
    @pytest.mark.asyncio
    async def test_get_spread_data_with_symbol_conversion(self, monitoring_service):
        """测试价差分析中的符号转换"""
        # 准备测试数据：不同交易所的相同交易对，但格式不同
        mock_price_data = {
            'hyperliquid_BTC/USDC:PERP': PriceData(
                symbol='BTC/USDC:PERP',
                exchange='hyperliquid',
                price=Decimal('50000.00'),
                volume=Decimal('100.0'),
                timestamp=datetime.now()
            ),
            'backpack_BTC_USDC_PERP': PriceData(
                symbol='BTC_USDC_PERP',
                exchange='backpack',
                price=Decimal('50100.00'),
                volume=Decimal('200.0'),
                timestamp=datetime.now()
            ),
            'edgex_BTC_USDT_PERP': PriceData(
                symbol='BTC_USDT_PERP',
                exchange='edgex',
                price=Decimal('50050.00'),
                volume=Decimal('150.0'),
                timestamp=datetime.now()
            )
        }
        
        # 模拟 get_price_data 方法
        with patch.object(monitoring_service, 'get_price_data', 
                         return_value=mock_price_data):
            
            # 调用 get_spread_data 方法
            spreads = await monitoring_service.get_spread_data()
            
            # 验证符号转换服务被调用
            assert monitoring_service.symbol_conversion_service.convert_from_exchange_format.call_count == 3
            
            # 验证转换调用的参数
            calls = monitoring_service.symbol_conversion_service.convert_from_exchange_format.call_args_list
            
            # 验证每个交易所的符号都被正确转换
            expected_calls = [
                ('BTC/USDC:PERP', 'hyperliquid'),
                ('BTC_USDC_PERP', 'backpack'),
                ('BTC_USDT_PERP', 'edgex')
            ]
            
            actual_calls = [(call[0][0], call[0][1]) for call in calls]
            
            for expected_call in expected_calls:
                assert expected_call in actual_calls
            
            # 验证价差数据被正确生成
            assert len(spreads) > 0
            
            # 验证标准化符号的价差分析
            # 所有三个交易所的BTC永续合约都应该被标准化为 'BTC-USDC-PERP'
            btc_spreads = [spread for spread in spreads.values() 
                          if spread.symbol == 'BTC-USDC-PERP']
            
            assert len(btc_spreads) > 0
            
            # 验证价差计算
            for spread in btc_spreads:
                assert spread.price1 > 0
                assert spread.price2 > 0
                assert spread.spread != 0
                assert spread.spread_pct != 0
    
    @pytest.mark.asyncio
    async def test_symbol_conversion_error_handling(self, monitoring_service):
        """测试符号转换错误处理"""
        # 准备测试数据
        mock_price_data = {
            'unknown_UNKNOWN_SYMBOL': PriceData(
                symbol='UNKNOWN_SYMBOL',
                exchange='unknown',
                price=Decimal('100.00'),
                volume=Decimal('10.0'),
                timestamp=datetime.now()
            )
        }
        
        # 模拟符号转换失败
        monitoring_service.symbol_conversion_service.convert_from_exchange_format.side_effect = Exception("转换失败")
        
        # 模拟 get_price_data 方法
        with patch.object(monitoring_service, 'get_price_data', 
                         return_value=mock_price_data):
            
            # 调用 get_spread_data 方法
            spreads = await monitoring_service.get_spread_data()
            
            # 验证错误处理：应该使用原始符号
            assert len(spreads) == 0  # 单个交易所无法生成价差
            
            # 验证符号转换服务被调用
            assert monitoring_service.symbol_conversion_service.convert_from_exchange_format.call_count == 1
    
    @pytest.mark.asyncio
    async def test_cross_exchange_spread_calculation(self, monitoring_service):
        """测试跨交易所价差计算"""
        # 准备测试数据：ETH在不同交易所的价格
        mock_price_data = {
            'hyperliquid_ETH/USDC:PERP': PriceData(
                symbol='ETH/USDC:PERP',
                exchange='hyperliquid',
                price=Decimal('3000.00'),
                volume=Decimal('50.0'),
                timestamp=datetime.now()
            ),
            'backpack_ETH_USDC_PERP': PriceData(
                symbol='ETH_USDC_PERP',
                exchange='backpack',
                price=Decimal('3020.00'),
                volume=Decimal('80.0'),
                timestamp=datetime.now()
            )
        }
        
        # 模拟 get_price_data 方法
        with patch.object(monitoring_service, 'get_price_data', 
                         return_value=mock_price_data):
            
            # 调用 get_spread_data 方法
            spreads = await monitoring_service.get_spread_data()
            
            # 验证价差计算
            assert len(spreads) == 1
            
            spread = list(spreads.values())[0]
            
            # 验证基本属性
            assert spread.symbol == 'ETH-USDC-PERP'
            assert spread.exchange1 in ['hyperliquid', 'backpack']
            assert spread.exchange2 in ['hyperliquid', 'backpack']
            assert spread.exchange1 != spread.exchange2
            
            # 验证价差计算
            assert spread.spread == Decimal('20.00')  # 3020 - 3000
            assert abs(spread.spread_pct - Decimal('0.67')) < Decimal('0.01')  # 20/3000 * 100
    
    def test_monitoring_service_has_symbol_conversion_service(self, monitoring_service):
        """测试监控服务是否正确注入了符号转换服务"""
        assert hasattr(monitoring_service, 'symbol_conversion_service')
        assert monitoring_service.symbol_conversion_service is not None
    
    def test_old_normalize_symbol_method_removed(self, monitoring_service):
        """测试旧的符号标准化方法是否被移除"""
        # 应该没有 _normalize_symbol 方法（或者被标记为废弃）
        if hasattr(monitoring_service, '_normalize_symbol'):
            # 如果方法存在，应该是被标记为废弃的注释版本
            import inspect
            method = getattr(monitoring_service, '_normalize_symbol')
            source = inspect.getsource(method)
            assert '已删除' in source or '废弃' in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"]) 