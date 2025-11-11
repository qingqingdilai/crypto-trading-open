#!/usr/bin/env python3
"""
双交易所永续合约监控系统 - 新架构版本

使用统一启动器提供监控守护进程模式
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent))

from core.system_launcher import SystemLauncher, StartupMode


async def main():
    """主函数 - 监控守护进程模式"""
    try:
        # 创建系统启动器（监控模式）
        launcher = SystemLauncher(StartupMode.MONITOR)
        
        # 启动监控守护进程模式（包含完整的监控循环）
        await launcher.start_monitor_daemon_mode()
        
        return 0
        
    except KeyboardInterrupt:
        print("\n👋 程序被用户中断")
        return 0
    except Exception as e:
        print(f"❌ 系统运行失败: {e}")
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except Exception as e:
        print(f"❌ 程序异常退出: {e}")
        sys.exit(1) 