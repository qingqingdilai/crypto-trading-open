#!/usr/bin/env python3
"""
全市场监控功能测试

验证系统是否能正确订阅所有交易所的所有交易对
"""

import asyncio
import logging
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.di.container import DIContainer
from core.di.modules import ALL_MODULES
# 使用统一日志系统
from core.logging import get_logger
from core.services.interfaces.monitoring_service import MonitoringService

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_full_market_monitoring():
    """测试全市场监控功能"""
    logger.info("🧪 开始测试全市场监控功能...")
    
    try:
        # 1. 初始化依赖注入容器
        logger.info("📦 初始化DI容器...")
        di_container = DIContainer()
        for module in ALL_MODULES:
            di_container.register_module(module)
        
        # 2. 获取服务
        logger.info("🔧 获取监控服务...")
        injector = di_container.injector
        monitoring_service = injector.get(MonitoringService)
        
        # 3. 启动监控服务（但不运行完整的监控循环）
        logger.info("🚀 启动监控服务...")
        success = await monitoring_service.start()
        
        if not success:
            logger.error("❌ 监控服务启动失败")
            return False
        
        logger.info("✅ 监控服务启动成功")
        
        # 4. 等待一段时间让订阅建立
        logger.info("⏳ 等待30秒让订阅建立和数据流开始...")
        await asyncio.sleep(30)
        
        # 5. 检查订阅状态
        logger.info("🔍 检查订阅状态...")
        health = await monitoring_service.health_check()
        
        logger.info("📊 系统健康状态:")
        logger.info(f"   - 状态: {health.get('status', 'unknown')}")
        logger.info(f"   - 运行时间: {health.get('uptime', 0):.1f}秒")
        logger.info(f"   - 已订阅交易对: {health.get('subscribed_symbols', 0)}")
        logger.info(f"   - 价格数据数量: {health.get('price_data_count', 0)}")
        logger.info(f"   - 消息总数: {health.get('message_count', 0)}")
        
        # 6. 检查价格数据
        price_data = await monitoring_service.get_price_data()
        logger.info(f"💰 获取到 {len(price_data)} 个价格数据点")
        
        # 显示前10个价格数据样本
        if price_data:
            logger.info("📈 价格数据样本:")
            count = 0
            for key, data in price_data.items():
                if count >= 10:
                    break
                logger.info(f"   {key}: ${data.price:.6f} (成交量: {data.volume:.2f})")
                count += 1
        
        # 7. 检查价差数据
        spread_data = await monitoring_service.get_spread_data()
        logger.info(f"📊 计算出 {len(spread_data)} 个价差数据")
        
        # 显示价差数据
        if spread_data:
            logger.info("💹 价差数据:")
            for symbol, spread in spread_data.items():
                logger.info(f"   {symbol}: {spread.spread_pct:+.2f}% (${spread.spread:+.6f})")
        
        # 8. 统计信息
        stats = await monitoring_service.get_stats()
        logger.info("📊 详细统计:")
        logger.info(f"   - 运行时间: {stats.uptime:.1f}秒")
        logger.info(f"   - 连接的交易所: {stats.connected_exchanges}")
        logger.info(f"   - 总消息数: {stats.total_messages}")
        logger.info(f"   - 错误数: {stats.errors}")
        logger.info(f"   - 交易所消息分布: {dict(stats.exchange_messages)}")
        
        # 9. 停止监控服务
        logger.info("🛑 停止监控服务...")
        await monitoring_service.stop()
        
        # 10. 评估测试结果
        logger.info("🔍 评估测试结果...")
        
        success_criteria = {
            "服务启动": success,
            "有价格数据": len(price_data) > 0,
            "消息接收": stats.total_messages > 0,
            "多交易所": stats.connected_exchanges > 0,
            "健康状态": health.get('status') == 'healthy'
        }
        
        all_passed = all(success_criteria.values())
        
        logger.info("📋 测试结果总结:")
        for criterion, passed in success_criteria.items():
            status = "✅ 通过" if passed else "❌ 失败"
            logger.info(f"   - {criterion}: {status}")
        
        if all_passed:
            logger.info("🎉 全市场监控功能测试通过！")
            logger.info("✨ 系统成功订阅了所有交易所的所有交易对")
        else:
            logger.warning("⚠️ 部分测试项未通过，请检查系统配置")
        
        return all_passed
        
    except Exception as e:
        logger.error(f"❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主函数"""
    logger.info("🎯 启动全市场监控功能测试")
    
    try:
        success = await test_full_market_monitoring()
        
        if success:
            logger.info("🏆 所有测试通过！")
            return 0
        else:
            logger.error("💥 测试失败")
            return 1
            
    except KeyboardInterrupt:
        logger.info("👋 测试被用户中断")
        return 0
    except Exception as e:
        logger.error(f"💥 测试异常: {e}")
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n👋 再见!")
        sys.exit(0) 