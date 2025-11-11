#!/usr/bin/env python3
"""
完整的批量监控系统集成测试
测试从获取交易对到数据聚合再到WebSocket推送的完整流程
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Any
import json

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 导入核心组件
from core.exchanges.factory import ExchangeFactory
from core.exchanges.interface import ExchangeConfig
from core.exchanges.models import ExchangeType
from core.data_aggregator import DataAggregator
from core.websocket_server import WebSocketServer
from core.events.event_bus import EventBus
from core.events.event import Event

class BatchMonitoringSystem:
    """批量监控系统管理器"""
    
    def __init__(self):
        self.event_bus = EventBus()
        self.data_aggregator = DataAggregator(self.event_bus)
        self.websocket_server = WebSocketServer(data_aggregator=self.data_aggregator)
        self.exchange_adapters = {}
        self.running = False
        self.stats = {
            'total_symbols': 0,
            'active_subscriptions': 0,
            'messages_processed': 0,
            'last_update': None
        }
    
    async def initialize(self):
        """初始化系统"""
        try:
            logger.info("🚀 初始化批量监控系统...")
            
            # 1. 创建交易所适配器
            await self._create_exchange_adapters()
            
            # 2. 获取支持的交易对
            await self._fetch_supported_symbols()
            
            # 3. 启动WebSocket服务器
            await self.websocket_server.start()
            
            # 4. 批量订阅数据
            await self._batch_subscribe_all()
            
            logger.info("✅ 批量监控系统初始化完成")
            
        except Exception as e:
            logger.error(f"❌ 系统初始化失败: {e}")
            raise
    
    async def _create_exchange_adapters(self):
        """创建交易所适配器"""
        logger.info("📡 创建交易所适配器...")
        
        # Backpack配置
        backpack_config = ExchangeConfig(
            exchange_id="backpack",
            name="backpack",
            exchange_type=ExchangeType.PERPETUAL,
            api_key="",
            api_secret="",
            base_url="https://api.backpack.exchange",
            ws_url="wss://ws.backpack.exchange/"
        )
        
        # EdgeX配置
        edgex_config = ExchangeConfig(
            exchange_id="edgex",
            name="edgex",
            exchange_type=ExchangeType.PERPETUAL,
            api_key="",
            api_secret="",
            base_url="https://api.edgex.exchange",
            ws_url="wss://quote.edgex.exchange/api/v1/public/ws"
        )
        
        # 创建适配器
        factory = ExchangeFactory()
        self.exchange_adapters['backpack'] = factory.create_adapter('backpack', backpack_config)
        self.exchange_adapters['edgex'] = factory.create_adapter('edgex', edgex_config)
        
        # 连接适配器以初始化session
        connected_adapters = {}
        for name, adapter in self.exchange_adapters.items():
            try:
                await adapter.connect()
                connected_adapters[name] = adapter
                logger.info(f"✅ {name} 适配器连接成功")
            except Exception as e:
                logger.error(f"❌ {name} 适配器连接失败: {e}")
        
        # 只保留连接成功的适配器
        self.exchange_adapters = connected_adapters
        
        logger.info(f"✅ 成功创建 {len(self.exchange_adapters)} 个交易所适配器")
    
    async def _fetch_supported_symbols(self):
        """获取所有支持的交易对"""
        logger.info("🔍 获取交易所支持的交易对...")
        
        for exchange_name, adapter in self.exchange_adapters.items():
            try:
                symbols = await adapter.get_supported_symbols()
                logger.info(f"📊 {exchange_name}: {len(symbols)} 个交易对")
                
                # 显示前5个交易对作为示例
                if symbols:
                    example_symbols = symbols[:5]
                    logger.info(f"   示例: {', '.join(example_symbols)}")
                
                self.stats['total_symbols'] += len(symbols)
                
            except Exception as e:
                logger.error(f"❌ 获取 {exchange_name} 交易对失败: {e}")
        
        logger.info(f"📈 总计: {self.stats['total_symbols']} 个交易对")
    
    async def _batch_subscribe_all(self):
        """批量订阅所有交易对数据"""
        logger.info("🔔 开始批量订阅数据...")
        
        for exchange_name, adapter in self.exchange_adapters.items():
            try:
                # 获取该交易所的交易对
                symbols = await adapter.get_supported_symbols()
                
                if not symbols:
                    logger.warning(f"⚠️ {exchange_name} 没有可用的交易对")
                    continue
                
                # 选择前10个交易对进行测试（避免过多连接）
                test_symbols = symbols[:10]
                logger.info(f"📡 {exchange_name}: 订阅 {len(test_symbols)} 个交易对")
                
                # 批量订阅ticker数据
                await adapter.batch_subscribe_tickers(
                    test_symbols,
                    callback=self._handle_ticker_data
                )
                
                # 批量订阅orderbook数据
                await adapter.batch_subscribe_orderbooks(
                    test_symbols,
                    callback=self._handle_orderbook_data
                )
                
                self.stats['active_subscriptions'] += len(test_symbols) * 2  # ticker + orderbook
                
                logger.info(f"✅ {exchange_name} 订阅完成")
                
            except Exception as e:
                logger.error(f"❌ {exchange_name} 订阅失败: {e}")
        
        logger.info(f"🎯 总计活跃订阅: {self.stats['active_subscriptions']} 个")
    
    async def _handle_ticker_data(self, symbol: str, data):
        """处理ticker数据"""
        self.stats['messages_processed'] += 1
        self.stats['last_update'] = datetime.now()
        
        # 从数据对象中提取信息
        last = getattr(data, 'last', 'N/A')
        bid = getattr(data, 'bid', 'N/A') 
        ask = getattr(data, 'ask', 'N/A')
        
        logger.info(f"📊 {symbol} Ticker: Last={last}, Bid={bid}, Ask={ask}")
    
    async def _handle_orderbook_data(self, symbol: str, data):
        """处理orderbook数据"""
        self.stats['messages_processed'] += 1
        self.stats['last_update'] = datetime.now()
        
        # 从数据对象中提取信息
        bids = getattr(data, 'bids', [])
        asks = getattr(data, 'asks', [])
        
        # 转换为简单的列表格式用于spread计算
        bid_prices = [[float(bid.price), float(bid.size)] for bid in bids[:5]] if bids else []
        ask_prices = [[float(ask.price), float(ask.size)] for ask in asks[:5]] if asks else []
        
        logger.info(f"📖 {symbol} OrderBook: "
                   f"Bids={len(bids)}, "
                   f"Asks={len(asks)}, "
                   f"Spread={self._calculate_spread(bid_prices, ask_prices)}")
    
    def _calculate_spread(self, bids: List, asks: List) -> str:
        """计算买卖价差"""
        try:
            if bids and asks:
                best_bid = float(bids[0][0]) if bids[0] else 0
                best_ask = float(asks[0][0]) if asks[0] else 0
                if best_bid > 0 and best_ask > 0:
                    spread = best_ask - best_bid
                    return f"{spread:.6f}"
        except:
            pass
        return "N/A"
    
    async def run_monitoring(self, duration: int = 60):
        """运行监控系统"""
        logger.info(f"🚀 开始监控，持续时间: {duration} 秒")
        
        self.running = True
        start_time = datetime.now()
        
        try:
            # 运行指定时间
            await asyncio.sleep(duration)
            
        except KeyboardInterrupt:
            logger.info("⏹️ 接收到中断信号，停止监控...")
        
        finally:
            self.running = False
            end_time = datetime.now()
            
            # 显示统计信息
            await self._show_statistics(start_time, end_time)
            
            # 清理资源
            await self._cleanup()
    
    async def _show_statistics(self, start_time: datetime, end_time: datetime):
        """显示统计信息"""
        duration = (end_time - start_time).total_seconds()
        
        logger.info("📊 监控统计信息:")
        logger.info(f"   运行时间: {duration:.1f} 秒")
        logger.info(f"   总交易对数: {self.stats['total_symbols']}")
        logger.info(f"   活跃订阅数: {self.stats['active_subscriptions']}")
        logger.info(f"   处理消息数: {self.stats['messages_processed']}")
        
        if self.stats['messages_processed'] > 0:
            rate = self.stats['messages_processed'] / duration
            logger.info(f"   平均消息率: {rate:.2f} msg/s")
        
        if self.stats['last_update']:
            logger.info(f"   最后更新: {self.stats['last_update'].strftime('%H:%M:%S')}")
    
    async def _cleanup(self):
        """清理资源"""
        logger.info("🧹 清理系统资源...")
        
        try:
            # 停止WebSocket服务器
            await self.websocket_server.stop()
            
            # 停止数据聚合器
            await self.data_aggregator.stop()
            
            # 关闭交易所适配器
            for adapter in self.exchange_adapters.values():
                if hasattr(adapter, 'disconnect'):
                    await adapter.disconnect()
            
            logger.info("✅ 资源清理完成")
            
        except Exception as e:
            logger.error(f"❌ 清理失败: {e}")


async def main():
    """主函数"""
    logger.info("🎯 启动批量监控系统集成测试")
    
    # 创建监控系统
    monitoring_system = BatchMonitoringSystem()
    
    try:
        # 初始化系统
        await monitoring_system.initialize()
        
        # 运行监控（60秒）
        await monitoring_system.run_monitoring(60)
        
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        raise
    
    finally:
        logger.info("🏁 批量监控系统测试完成")


if __name__ == "__main__":
    asyncio.run(main()) 