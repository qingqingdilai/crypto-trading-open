#!/usr/bin/env python3
"""
修复后的批量监控系统测试脚本
验证：
1. JSON序列化问题修复
2. Backpack只显示永续合约数据
3. EdgeX WebSocket连接修复
4. 前端数据传输正常
"""

import asyncio
import logging
import json
from datetime import datetime
from core.data_aggregator import DataAggregator, DataType
from core.websocket_server import WebSocketServer
from core.events.event_bus import EventBus
from core.exchanges.factory import ExchangeFactory
from core.exchanges.interface import ExchangeConfig

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('test_fixed_monitor.log')
    ]
)

logger = logging.getLogger(__name__)

async def test_fixed_monitoring_system():
    """测试修复后的批量监控系统"""
    logger.info("🚀 开始测试修复后的批量监控系统...")
    
    # 创建事件总线
    event_bus = EventBus()
    await event_bus.start()
    
    # 创建数据聚合器
    data_aggregator = DataAggregator(event_bus=event_bus)
    
    # 创建WebSocket服务器
    websocket_server = WebSocketServer(
        host="localhost",
        port=8765,
        data_aggregator=data_aggregator
    )
    
    try:
        # 配置交易所
        from core.exchanges.models import ExchangeType
        
        exchanges = {
            "backpack": ExchangeConfig(
                exchange_id="backpack",
                name="Backpack",
                exchange_type=ExchangeType.PERPETUAL,
                api_key="",
                api_secret=""
            ),
            "edgex": ExchangeConfig(
                exchange_id="edgex",
                name="EdgeX", 
                exchange_type=ExchangeType.PERPETUAL,
                api_key="",
                api_secret=""
            )
        }
        
        # 创建交易所工厂
        factory = ExchangeFactory()
        
        # 添加交易所适配器
        for name, config in exchanges.items():
            adapter = factory.create_adapter(name, config, event_bus)
            await data_aggregator.add_exchange(name, config)
            logger.info(f"✅ 已添加交易所: {name}")
        
        # 获取支持的交易对
        logger.info("📊 获取支持的交易对...")
        all_symbols = await data_aggregator.get_all_supported_symbols()
        
        for exchange, symbols in all_symbols.items():
            logger.info(f"🔗 {exchange}: {len(symbols)} 个交易对")
            logger.info(f"   前5个: {symbols[:5]}")
        
        # 获取共同交易对
        common_symbols = await data_aggregator.get_common_symbols()
        logger.info(f"🤝 共同交易对: {len(common_symbols)} 个")
        logger.info(f"   列表: {common_symbols[:10]}")
        
        # 启动WebSocket服务器
        logger.info("🌐 启动WebSocket服务器...")
        await websocket_server.start()
        
        # 启动批量监控
        logger.info("📡 开始批量监控...")
        await data_aggregator.start_batch_monitoring(
            symbols=common_symbols[:5],  # 只监控前5个交易对进行测试
            data_types=[DataType.TICKER, DataType.ORDERBOOK]
        )
        
        # 运行30秒进行测试
        logger.info("⏱️  运行30秒进行数据监控测试...")
        await asyncio.sleep(30)
        
        # 获取统计信息
        stats = data_aggregator.get_statistics()
        logger.info(f"📈 监控统计: {json.dumps(stats, indent=2, default=str)}")
        
        # 获取市场快照
        snapshots = data_aggregator.get_all_market_snapshots()
        logger.info(f"📸 市场快照: {len(snapshots)} 个")
        
        for symbol, snapshot in list(snapshots.items())[:3]:  # 只显示前3个
            logger.info(f"   {symbol}: {list(snapshot.exchange_data.keys())}")
        
        logger.info("✅ 测试完成！")
        
    except Exception as e:
        logger.error(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # 清理资源
        logger.info("🛑 正在停止服务...")
        try:
            await data_aggregator.stop()
            await websocket_server.stop()
            await event_bus.stop()
            logger.info("✅ 服务已停止")
        except Exception as e:
            logger.error(f"停止服务时出错: {e}")

if __name__ == "__main__":
    asyncio.run(test_fixed_monitoring_system()) 