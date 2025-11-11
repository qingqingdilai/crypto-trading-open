"""
主应用入口

使用统一启动器提供API服务器模式
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent))

from core.system_launcher import SystemLauncher, StartupMode
from api.gateway import app
import uvicorn


async def main():
    """主函数 - API服务器模式"""
    try:
        # 创建系统启动器（API模式）
        launcher = SystemLauncher(StartupMode.API)
        
        # 初始化服务
        await launcher.start_api_server_mode()
        
        # 启动API服务器
        print("🌐 启动API服务器...")
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=8000,
            reload=False,
            log_config=None  # 使用统一日志配置
        )
        
    except KeyboardInterrupt:
        print("\n✋ 用户中断，正在停止系统...")
        await launcher.stop_services()
    except Exception as e:
        print(f"❌ 系统启动失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
