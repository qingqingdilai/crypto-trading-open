"""
多交易所价格监控 - WebSocket管理器
Multi-Exchange Price Monitor - WebSocket Manager
"""

import asyncio
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from decimal import Decimal
import logging

from core.adapters.exchanges.adapters.hyperliquid import HyperliquidAdapter
from core.adapters.exchanges.adapters.binance import BinanceAdapter
from core.adapters.exchanges.adapters.okx import OKXAdapter
from core.adapters.exchanges.interface import ExchangeConfig
from core.adapters.exchanges.models import TickerData, ExchangeType

from .models import (
    PriceData, MarketType, ExchangeName, MonitorConfig, 
    ConnectionStatus, SpreadData
)
from .price_calculator import PriceCalculator


class ExchangeAdapterManager:
    """交易所适配器管理器"""
    
    def __init__(self, exchange_name: str, config: Dict[str, Any], 
                 price_calculator: PriceCalculator):
        """
        初始化交易所适配器管理器
        
        Args:
            exchange_name: 交易所名称
            config: 交易所配置
            price_calculator: 价差计算器
        """
        self.exchange_name = exchange_name
        self.config = config
        self.calculator = price_calculator
        self.logger = logging.getLogger(f"monitor.{exchange_name}")
        
        # 适配器实例
        self.adapter: Optional[Any] = None
        
        # 连接状态
        self.connection_status = ConnectionStatus(exchange=exchange_name)
        
        # 订阅的符号列表
        self.subscribed_symbols: Dict[MarketType, List[str]] = {}
        
        # 是否启用
        self.enabled = config.get('enabled', False)
        
        # 错误重试计数
        self.retry_count = 0
        self.max_retries = 5
        
    async def initialize(self) -> bool:
        """
        初始化适配器
        
        Returns:
            bool: 初始化是否成功
        """
        if not self.enabled:
            self.logger.info(f"交易所 {self.exchange_name} 未启用")
            return False
        
        try:
            # 创建交易所配置（公共数据不需要API密钥）
            exchange_config = ExchangeConfig(
                exchange_id=self.exchange_name,
                name=self.exchange_name,
                exchange_type=ExchangeType.PERPETUAL,  # 默认类型（永续合约）
                api_key='',  # 公共数据不需要API密钥
                api_secret='',  # 公共数据不需要API密钥
                api_passphrase='',  # 公共数据不需要密语
                testnet=self.config.get('testnet', False),
                enable_websocket=True,  # 强制启用WebSocket
                enable_auto_reconnect=True  # 启用自动重连
            )
            
            # 创建适配器实例
            if self.exchange_name == ExchangeName.HYPERLIQUID.value:
                self.adapter = HyperliquidAdapter(exchange_config)
            elif self.exchange_name == ExchangeName.BINANCE.value:
                self.adapter = BinanceAdapter(exchange_config)
            elif self.exchange_name == ExchangeName.OKX.value:
                self.adapter = OKXAdapter(exchange_config)
            else:
                raise ValueError(f"不支持的交易所: {self.exchange_name}")
            
            # 连接适配器
            await self.adapter.connect()
            
            self.connection_status.update_status(True)
            self.retry_count = 0
            
            self.logger.info(f"✅ {self.exchange_name} 适配器初始化成功")
            return True
            
        except Exception as e:
            error_msg = str(e)
            self.connection_status.update_status(False, error_msg)
            self.logger.error(f"❌ {self.exchange_name} 适配器初始化失败: {error_msg}")
            return False
    
    async def subscribe_symbols(self, symbols_config: Dict[str, List[str]]) -> bool:
        """
        订阅交易符号
        
        Args:
            symbols_config: 符号配置 {market_type: [symbols]}
            
        Returns:
            bool: 订阅是否成功
        """
        if not self.adapter:
            self.logger.error("适配器未初始化")
            return False
        
        try:
            # 遍历不同市场类型
            for market_type_str, symbols in symbols_config.items():
                market_type = MarketType(market_type_str)
                
                # 过滤并转换符号格式
                valid_symbols = []
                for symbol in symbols:
                    try:
                        # 转换符号格式（适配不同交易所）
                        adapted_symbol = await self._adapt_symbol_format(symbol, market_type)
                        if adapted_symbol:
                            valid_symbols.append(adapted_symbol)
                            
                            # 订阅行情数据
                            await self.adapter.subscribe_ticker(
                                adapted_symbol, 
                                self._create_ticker_callback(symbol, market_type)
                            )
                            
                    except Exception as e:
                        self.logger.warning(f"符号 {symbol} 订阅失败: {e}")
                        continue
                
                self.subscribed_symbols[market_type] = valid_symbols
                self.logger.info(f"✅ {self.exchange_name} 订阅了 {len(valid_symbols)} 个 {market_type.value} 符号")
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ {self.exchange_name} 符号订阅失败: {e}")
            return False
    
    async def _adapt_symbol_format(self, symbol: str, market_type: MarketType) -> Optional[str]:
        """
        适配符号格式到具体交易所
        
        Args:
            symbol: 原始符号（如 BTC/USDT）
            market_type: 市场类型
            
        Returns:
            Optional[str]: 适配后的符号
        """
        try:
            if self.exchange_name == ExchangeName.HYPERLIQUID.value:
                # Hyperliquid 只有永续合约
                if market_type == MarketType.PERPETUAL:
                    # BTC/USDT -> BTC
                    base = symbol.split('/')[0]
                    return base
                else:
                    return None  # 不支持现货
                    
            elif self.exchange_name == ExchangeName.BINANCE.value:
                # Binance 格式转换
                if market_type == MarketType.SPOT:
                    # BTC/USDT -> BTCUSDT
                    return symbol.replace('/', '')
                elif market_type == MarketType.PERPETUAL:
                    # BTC/USDT -> BTCUSDT
                    return symbol.replace('/', '')
                else:
                    return None
                    
            elif self.exchange_name == ExchangeName.OKX.value:
                # OKX 格式转换
                if market_type == MarketType.SPOT:
                    # BTC/USDT -> BTC-USDT
                    return symbol.replace('/', '-')
                elif market_type == MarketType.PERPETUAL:
                    # BTC/USDT -> BTC-USDT-SWAP
                    return symbol.replace('/', '-') + '-SWAP'
                else:
                    return None
            
            return None
            
        except Exception as e:
            self.logger.error(f"符号格式转换失败 {symbol}: {e}")
            return None
    
    def _create_ticker_callback(self, original_symbol: str, market_type: MarketType) -> Callable:
        """
        创建行情数据回调函数
        
        Args:
            original_symbol: 原始符号
            market_type: 市场类型
            
        Returns:
            Callable: 回调函数
        """
        async def ticker_callback(ticker_data: TickerData):
            try:
                # 创建价格数据对象
                price_data = PriceData(
                    exchange=self.exchange_name,
                    symbol=original_symbol,  # 使用原始符号
                    market_type=market_type,
                    price=Decimal(str(ticker_data.last)) if ticker_data.last else None,
                    volume=Decimal(str(ticker_data.volume)) if ticker_data.volume else None,
                    timestamp=ticker_data.timestamp or datetime.now(),
                    is_available=True
                )
                
                # 更新到计算器
                spread_data = await self.calculator.update_price(price_data)
                
                if spread_data:
                    self.logger.debug(f"更新价格 {original_symbol}: {price_data.price}")
                
            except Exception as e:
                self.logger.error(f"处理行情数据失败 {original_symbol}: {e}")
                
                # 创建错误的价格数据
                error_price_data = PriceData(
                    exchange=self.exchange_name,
                    symbol=original_symbol,
                    market_type=market_type,
                    is_available=False,
                    error_message=str(e)
                )
                
                await self.calculator.update_price(error_price_data)
        
        return ticker_callback
    
    async def disconnect(self):
        """断开连接"""
        if self.adapter:
            try:
                await self.adapter.disconnect()
                self.connection_status.update_status(False)
                self.logger.info(f"✅ {self.exchange_name} 适配器已断开")
            except Exception as e:
                self.logger.error(f"❌ {self.exchange_name} 断开连接失败: {e}")
    
    async def reconnect(self) -> bool:
        """重新连接"""
        if self.retry_count >= self.max_retries:
            self.logger.error(f"{self.exchange_name} 重连次数已达上限")
            return False
        
        self.retry_count += 1
        self.logger.info(f"尝试重连 {self.exchange_name} (第{self.retry_count}次)")
        
        # 先断开
        await self.disconnect()
        
        # 等待一段时间
        await asyncio.sleep(5)
        
        # 重新初始化
        if await self.initialize():
            # 重新订阅
            if self.subscribed_symbols:
                symbols_config = {
                    market_type.value: symbols 
                    for market_type, symbols in self.subscribed_symbols.items()
                }
                return await self.subscribe_symbols(symbols_config)
        
        return False
    
    def get_status(self) -> ConnectionStatus:
        """获取连接状态"""
        return self.connection_status
    
    def is_connected(self) -> bool:
        """检查是否连接"""
        return self.connection_status.is_connected and self.adapter is not None


class WebSocketManager:
    """WebSocket 管理器 - 统一管理所有交易所的 WebSocket 连接"""
    
    def __init__(self, config: MonitorConfig, price_calculator: PriceCalculator):
        """
        初始化 WebSocket 管理器
        
        Args:
            config: 监控配置
            price_calculator: 价差计算器
        """
        self.config = config
        self.calculator = price_calculator
        self.logger = logging.getLogger("monitor.websocket")
        
        # 交易所适配器管理器
        self.adapters: Dict[str, ExchangeAdapterManager] = {}
        
        # 监控任务
        self.monitor_tasks: List[asyncio.Task] = []
        
        # 是否运行中
        self.is_running = False
        
    async def initialize(self) -> bool:
        """
        初始化所有交易所适配器
        
        Returns:
            bool: 初始化是否成功
        """
        self.logger.info("🚀 初始化多交易所 WebSocket 连接...")
        
        success_count = 0
        
        # 为每个启用的交易所创建适配器管理器
        for exchange_name, exchange_config in self.config.exchanges.items():
            if exchange_config.get('enabled', False):
                self.logger.info(f"初始化 {exchange_name} 适配器...")
                
                manager = ExchangeAdapterManager(
                    exchange_name=exchange_name,
                    config=exchange_config,
                    price_calculator=self.calculator
                )
                
                if await manager.initialize():
                    self.adapters[exchange_name] = manager
                    success_count += 1
                else:
                    self.logger.error(f"❌ {exchange_name} 适配器初始化失败")
        
        if success_count == 0:
            self.logger.error("❌ 没有任何交易所适配器初始化成功")
            return False
        
        self.logger.info(f"✅ 成功初始化 {success_count} 个交易所适配器")
        return True
    
    async def start_subscriptions(self) -> bool:
        """
        开始所有订阅
        
        Returns:
            bool: 订阅是否成功
        """
        self.logger.info("📡 开始订阅所有交易符号...")
        
        success_count = 0
        
        # 为每个适配器订阅符号
        for exchange_name, manager in self.adapters.items():
            self.logger.info(f"订阅 {exchange_name} 符号...")
            
            if await manager.subscribe_symbols(self.config.symbols):
                success_count += 1
            else:
                self.logger.error(f"❌ {exchange_name} 符号订阅失败")
        
        if success_count == 0:
            self.logger.error("❌ 没有任何交易所订阅成功")
            return False
        
        self.logger.info(f"✅ 成功订阅 {success_count} 个交易所")
        
        # 启动监控任务
        await self._start_monitoring()
        
        self.is_running = True
        return True
    
    async def _start_monitoring(self):
        """启动监控任务"""
        # 启动连接监控任务
        connection_monitor_task = asyncio.create_task(self._monitor_connections())
        self.monitor_tasks.append(connection_monitor_task)
        
        self.logger.info("✅ 监控任务已启动")
    
    async def _monitor_connections(self):
        """监控连接状态"""
        while self.is_running:
            try:
                # 检查每个适配器的连接状态
                for exchange_name, manager in self.adapters.items():
                    if not manager.is_connected():
                        self.logger.warning(f"⚠️ {exchange_name} 连接异常，尝试重连...")
                        
                        # 异步重连，不阻塞其他检查
                        asyncio.create_task(manager.reconnect())
                
                # 等待下次检查
                await asyncio.sleep(30)  # 每30秒检查一次
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"连接监控任务异常: {e}")
                await asyncio.sleep(10)
    
    async def stop(self):
        """停止所有连接和监控"""
        self.logger.info("🛑 停止多交易所监控...")
        
        self.is_running = False
        
        # 取消所有监控任务
        for task in self.monitor_tasks:
            if not task.done():
                task.cancel()
        
        # 等待任务完成
        if self.monitor_tasks:
            await asyncio.gather(*self.monitor_tasks, return_exceptions=True)
        
        # 断开所有适配器连接
        for exchange_name, manager in self.adapters.items():
            self.logger.info(f"断开 {exchange_name} 连接...")
            await manager.disconnect()
        
        self.logger.info("✅ 所有连接已断开")
    
    def get_connection_status(self) -> Dict[str, ConnectionStatus]:
        """获取所有交易所的连接状态"""
        return {
            exchange_name: manager.get_status()
            for exchange_name, manager in self.adapters.items()
        }
    
    def get_connected_exchanges(self) -> List[str]:
        """获取已连接的交易所列表"""
        return [
            exchange_name for exchange_name, manager in self.adapters.items()
            if manager.is_connected()
        ]
    
    def get_subscribed_symbols(self) -> Dict[str, Dict[str, List[str]]]:
        """获取已订阅的符号"""
        result = {}
        for exchange_name, manager in self.adapters.items():
            result[exchange_name] = {
                market_type.value: symbols
                for market_type, symbols in manager.subscribed_symbols.items()
            }
        return result
    
    async def add_symbol(self, symbol: str, market_type: MarketType) -> bool:
        """
        动态添加新的监控符号
        
        Args:
            symbol: 新符号
            market_type: 市场类型
            
        Returns:
            bool: 添加是否成功
        """
        success_count = 0
        
        for exchange_name, manager in self.adapters.items():
            try:
                # 转换符号格式
                adapted_symbol = await manager._adapt_symbol_format(symbol, market_type)
                if adapted_symbol:
                    # 订阅新符号
                    await manager.adapter.subscribe_ticker(
                        adapted_symbol,
                        manager._create_ticker_callback(symbol, market_type)
                    )
                    
                    # 更新订阅列表
                    if market_type not in manager.subscribed_symbols:
                        manager.subscribed_symbols[market_type] = []
                    
                    if adapted_symbol not in manager.subscribed_symbols[market_type]:
                        manager.subscribed_symbols[market_type].append(adapted_symbol)
                    
                    success_count += 1
                    self.logger.info(f"✅ {exchange_name} 成功添加符号 {symbol}")
                    
            except Exception as e:
                self.logger.error(f"❌ {exchange_name} 添加符号 {symbol} 失败: {e}")
        
        return success_count > 0
    
    async def remove_symbol(self, symbol: str, market_type: MarketType) -> bool:
        """
        动态移除监控符号
        
        Args:
            symbol: 要移除的符号
            market_type: 市场类型
            
        Returns:
            bool: 移除是否成功
        """
        success_count = 0
        
        for exchange_name, manager in self.adapters.items():
            try:
                # 转换符号格式
                adapted_symbol = await manager._adapt_symbol_format(symbol, market_type)
                if adapted_symbol:
                    # 取消订阅
                    await manager.adapter.unsubscribe(adapted_symbol)
                    
                    # 从订阅列表中移除
                    if (market_type in manager.subscribed_symbols and 
                        adapted_symbol in manager.subscribed_symbols[market_type]):
                        manager.subscribed_symbols[market_type].remove(adapted_symbol)
                    
                    success_count += 1
                    self.logger.info(f"✅ {exchange_name} 成功移除符号 {symbol}")
                    
            except Exception as e:
                self.logger.error(f"❌ {exchange_name} 移除符号 {symbol} 失败: {e}")
        
        # 清理计算器中的数据
        await self.calculator.clear_symbol_data(symbol, market_type)
        
        return success_count > 0
    
    def __str__(self) -> str:
        """字符串表示"""
        connected_count = len(self.get_connected_exchanges())
        total_count = len(self.adapters)
        
        return (f"WebSocketManager(连接={connected_count}/{total_count}, "
                f"运行中={self.is_running})")
    
    def __repr__(self) -> str:
        return self.__str__()
