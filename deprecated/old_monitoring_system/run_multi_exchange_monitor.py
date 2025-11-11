#!/usr/bin/env python3
"""
多交易所价格监控系统启动脚本
Multi-Exchange Price Monitor System Launcher

使用示例:
    python run_multi_exchange_monitor.py
    python run_multi_exchange_monitor.py --config config/custom_monitor.yaml
    python run_multi_exchange_monitor.py --verbose
"""

import sys
import os
import asyncio
import argparse
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from tools.multi_exchange_monitor import MultiExchangeMonitor


def print_banner():
    """打印启动横幅"""
    banner = """
    ╔══════════════════════════════════════════════════════════════════════════════╗
    ║                        多交易所价格监控系统                                    ║
    ║                    Multi-Exchange Price Monitor                              ║
    ║                                                                              ║
    ║  支持交易所: Hyperliquid | Binance | OKX                                     ║
    ║  监控类型: 现货 | 永续合约                                                     ║
    ║  实时功能: WebSocket订阅 | 价差计算 | 套利提醒                                  ║
    ╚══════════════════════════════════════════════════════════════════════════════╝
    """
    print(banner)


def check_dependencies():
    """检查依赖项"""
    missing_deps = []
    
    try:
        import yaml
    except ImportError:
        missing_deps.append("PyYAML")
    
    try:
        import rich
    except ImportError:
        print("⚠️  Rich库未安装，将使用简单终端界面")
    
    try:
        import ccxt
    except ImportError:
        missing_deps.append("ccxt")
    
    try:
        import websockets
    except ImportError:
        missing_deps.append("websockets")
    
    if missing_deps:
        print(f"❌ 缺少依赖项: {', '.join(missing_deps)}")
        print("请运行: pip install " + " ".join(missing_deps))
        return False
    
    return True


def check_config_file(config_path: str) -> bool:
    """检查配置文件"""
    if not os.path.exists(config_path):
        print(f"❌ 配置文件不存在: {config_path}")
        
        # 提示创建默认配置
        default_config = project_root / "config" / "multi_exchange_monitor.yaml"
        if default_config.exists():
            print(f"💡 默认配置文件位置: {default_config}")
            print("您可以复制并修改该文件")
        else:
            print("💡 请先创建配置文件，参考项目文档")
        
        return False
    
    return True


def validate_environment():
    """验证运行环境"""
    print("🔍 检查运行环境...")
    
    # 检查 Python 版本
    if sys.version_info < (3, 8):
        print("❌ 需要 Python 3.8 或更高版本")
        return False
    
    print(f"✅ Python 版本: {sys.version}")
    
    # 检查依赖项
    if not check_dependencies():
        return False
    
    print("✅ 依赖项检查通过")
    return True


async def run_monitor(config_path: str, verbose: bool = False):
    """运行监控程序"""
    try:
        print(f"📋 使用配置文件: {config_path}")
        
        # 创建并启动监控应用
        app = MultiExchangeMonitor(config_path)
        
        print("🚀 正在启动监控系统...")
        print("💡 提示:")
        print("   - 使用 Ctrl+C 退出程序")
        print("   - 确保网络连接正常")
        print("   - 检查API密钥配置正确")
        print("")
        
        # 启动应用
        success = await app.start()
        
        if not success:
            print("❌ 监控系统启动失败")
            return False
        
        return True
        
    except KeyboardInterrupt:
        print("\n🛑 接收到退出信号")
        return True
    except Exception as e:
        print(f"❌ 运行异常: {e}")
        if verbose:
            import traceback
            traceback.print_exc()
        return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="多交易所价格监控系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python run_multi_exchange_monitor.py
  python run_multi_exchange_monitor.py --config config/my_config.yaml
  python run_multi_exchange_monitor.py --verbose

注意事项:
  1. 请确保配置文件中的API密钥正确
  2. 建议在网络稳定的环境下运行
  3. 首次运行建议使用 --verbose 查看详细日志
        """
    )
    
    parser.add_argument(
        "--config", "-c",
        default="config/multi_exchange_monitor.yaml",
        help="配置文件路径 (默认: config/multi_exchange_monitor.yaml)"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="显示详细日志信息"
    )
    
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="仅检查环境和配置，不启动监控"
    )
    
    args = parser.parse_args()
    
    # 打印横幅
    print_banner()
    
    # 验证环境
    if not validate_environment():
        sys.exit(1)
    
    # 检查配置文件
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = project_root / config_path
    
    if not check_config_file(str(config_path)):
        sys.exit(1)
    
    print("✅ 配置文件检查通过")
    
    # 如果只是检查模式，直接退出
    if args.check_only:
        print("✅ 环境检查完成，系统就绪")
        return
    
    # 设置日志级别
    import logging
    if args.verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    else:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
    
    # 运行监控程序
    try:
        success = asyncio.run(run_monitor(str(config_path), args.verbose))
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n👋 程序已退出")
        sys.exit(0)
    except Exception as e:
        print(f"❌ 程序异常退出: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
