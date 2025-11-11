#!/usr/bin/env python3
"""
交易策略系统 - 混合模式启动器

同时提供API服务器和监控守护进程功能
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent))

from core.system_launcher import SystemLauncher, StartupMode
from api.gateway import app
import uvicorn


async def start_api_server(launcher: SystemLauncher):
    """启动API服务器"""
    try:
        launcher.logger.info("🌐 启动API服务器...")
        
        # 创建uvicorn配置
        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=8000,
            loop="asyncio",
            log_config=None  # 使用统一日志配置
        )
        
        # 创建服务器实例
        server = uvicorn.Server(config)
        
        # 启动服务器
        await server.serve()
        
    except Exception as e:
        launcher.logger.error(f"❌ API服务器启动失败: {e}")
        raise


async def main():
    """主函数 - 混合模式"""
    try:
        # 创建系统启动器（混合模式）
        launcher = SystemLauncher(StartupMode.HYBRID)
        
        # 初始化混合模式
        await launcher.start_hybrid_mode()
        
        # 并行运行API服务器和监控循环
        await asyncio.gather(
            start_api_server(launcher),
            launcher.run_monitoring_loop(),
            return_exceptions=True
        )
        
        return 0
        
    except KeyboardInterrupt:
        print("\n👋 混合模式被用户中断")
        if 'launcher' in locals():
            await launcher.stop_services()
        return 0
    except Exception as e:
        print(f"❌ 混合模式运行失败: {e}")
        if 'launcher' in locals():
            await launcher.stop_services()
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except Exception as e:
        print(f"❌ 程序异常退出: {e}")
        sys.exit(1) 