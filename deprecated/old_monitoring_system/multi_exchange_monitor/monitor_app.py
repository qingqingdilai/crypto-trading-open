"""
多交易所价格监控 - 主应用
Multi-Exchange Price Monitor - Main Application
"""

import asyncio
import signal
import sys
import os
from pathlib import Path
from typing import Optional
import logging

from .config_loader import ConfigLoader
from .price_calculator import PriceCalculator
from .display_manager import DisplayManager
from .websocket_manager import WebSocketManager
from .models import MonitorConfig


class MultiExchangeMonitor:
    """多交易所价格监控主应用"""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初始化监控应用
        
        Args:
            config_path: 配置文件路径
        """
        self.config_path = config_path
        
        # 核心组件
        self.config_loader: Optional[ConfigLoader] = None
        self.config: Optional[MonitorConfig] = None
        self.price_calculator: Optional[PriceCalculator] = None
        self.websocket_manager: Optional[WebSocketManager] = None
        self.display_manager: Optional[DisplayManager] = None
        
        # 运行状态
        self.is_running = False
        self.shutdown_event = asyncio.Event()
        
        # 日志记录器
        self.logger = logging.getLogger("monitor.app")
        
        # 设置信号处理
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self):
        """设置信号处理器"""
        if sys.platform != 'win32':
            # Unix/Linux 系统
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
        else:
            # Windows 系统
            signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """信号处理函数"""
        self.logger.info(f"接收到信号 {signum}，准备退出...")
        self.shutdown_event.set()
    
    async def initialize(self) -> bool:
        """
        初始化所有组件
        
        Returns:
            bool: 初始化是否成功
        """
        try:
            self.logger.info("🚀 开始初始化多交易所价格监控系统...")
            
            # 1. 加载配置
            if not await self._load_config():
                return False
            
            # 2. 设置日志
            self._setup_logging()
            
            # 3. 创建核心组件
            if not await self._create_components():
                return False
            
            # 4. 初始化 WebSocket 管理器
            if not await self.websocket_manager.initialize():
                self.logger.error("❌ WebSocket 管理器初始化失败")
                return False
            
            self.logger.info("✅ 所有组件初始化完成")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 初始化失败: {e}")
            return False
    
    async def _load_config(self) -> bool:
        """加载配置文件"""
        try:
            self.logger.info("📋 加载配置文件...")
            
            self.config_loader = ConfigLoader(self.config_path)
            self.config = self.config_loader.load_config()
            
            # 验证配置
            enabled_exchanges = self.config.get_enabled_exchanges()
            if not enabled_exchanges:
                self.logger.error("❌ 没有启用任何交易所")
                return False
            
            total_symbols = sum(len(symbols) for symbols in self.config.symbols.values())
            if total_symbols == 0:
                self.logger.error("❌ 没有配置任何监控符号")
                return False
            
            self.logger.info(f"✅ 配置加载成功 - 启用交易所: {enabled_exchanges}")
            self.logger.info(f"✅ 配置加载成功 - 监控符号数: {total_symbols}")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 配置加载失败: {e}")
            return False
    
    def _setup_logging(self):
        """设置日志系统"""
        try:
            logging_config = self.config.logging
            
            # 设置日志级别
            log_level = logging_config.get('level', 'INFO')
            logging.getLogger().setLevel(getattr(logging, log_level))
            
            # 设置日志格式
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            
            # 控制台输出
            if logging_config.get('console', True):
                console_handler = logging.StreamHandler()
                console_handler.setFormatter(formatter)
                logging.getLogger().addHandler(console_handler)
            
            # 文件输出
            log_file = logging_config.get('file')
            if log_file:
                # 确保日志目录存在
                log_path = Path(log_file)
                log_path.parent.mkdir(parents=True, exist_ok=True)
                
                file_handler = logging.FileHandler(log_file)
                file_handler.setFormatter(formatter)
                logging.getLogger().addHandler(file_handler)
            
            self.logger.info("✅ 日志系统配置完成")
            
        except Exception as e:
            print(f"❌ 日志配置失败: {e}")
    
    async def _create_components(self) -> bool:
        """创建核心组件"""
        try:
            self.logger.info("🔧 创建核心组件...")
            
            # 创建价差计算器
            data_config = self.config.data
            self.price_calculator = PriceCalculator(
                price_cache_ttl=data_config.get('price_cache_ttl', 60),
                max_history_records=data_config.get('max_spread_records', 1000)
            )
            
            # 创建 WebSocket 管理器
            self.websocket_manager = WebSocketManager(
                config=self.config,
                price_calculator=self.price_calculator
            )
            
            # 创建显示管理器
            display_thresholds = self.config_loader.get_display_thresholds()
            self.display_manager = DisplayManager(
                calculator=self.price_calculator,
                thresholds=display_thresholds,
                config=self.config.display
            )
            
            # 将连接状态传递给显示管理器
            for exchange_name in self.config.get_enabled_exchanges():
                from .models import ConnectionStatus
                status = ConnectionStatus(exchange=exchange_name)
                self.display_manager.add_connection_status(exchange_name, status)
            
            self.logger.info("✅ 核心组件创建完成")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 组件创建失败: {e}")
            return False
    
    async def start(self) -> bool:
        """
        启动监控系统
        
        Returns:
            bool: 启动是否成功
        """
        try:
            self.logger.info("🚀 启动多交易所价格监控系统...")
            
            # 初始化
            if not await self.initialize():
                return False
            
            # 启动 WebSocket 订阅
            if not await self.websocket_manager.start_subscriptions():
                self.logger.error("❌ WebSocket 订阅启动失败")
                return False
            
            # 更新显示管理器的连接状态
            connection_status = self.websocket_manager.get_connection_status()
            for exchange_name, status in connection_status.items():
                self.display_manager.add_connection_status(exchange_name, status)
            
            self.is_running = True
            
            self.logger.info("🎉 监控系统启动成功！")
            self.logger.info("📊 开始实时价格监控和价差计算...")
            
            # 启动显示界面（这会阻塞直到退出）
            await self._run_display()
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 启动失败: {e}")
            return False
    
    async def _run_display(self):
        """运行显示界面"""
        # 创建显示任务
        display_task = asyncio.create_task(self.display_manager.start_display())
        
        # 创建状态更新任务
        status_update_task = asyncio.create_task(self._update_connection_status())
        
        # 创建历史保存任务
        history_save_task = asyncio.create_task(self._save_history_periodically())
        
        try:
            # 等待任务完成或接收到关闭信号
            await asyncio.gather(
                display_task,
                status_update_task, 
                history_save_task,
                self._wait_for_shutdown(),
                return_exceptions=True
            )
        except Exception as e:
            self.logger.error(f"显示界面运行异常: {e}")
        finally:
            # 取消所有任务
            for task in [display_task, status_update_task, history_save_task]:
                if not task.done():
                    task.cancel()
    
    async def _update_connection_status(self):
        """定期更新连接状态"""
        while self.is_running:
            try:
                # 获取最新连接状态
                connection_status = self.websocket_manager.get_connection_status()
                
                # 更新显示管理器
                for exchange_name, status in connection_status.items():
                    self.display_manager.update_connection_status(
                        exchange_name, 
                        status.is_connected, 
                        status.last_error
                    )
                
                await asyncio.sleep(5)  # 每5秒更新一次
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"连接状态更新异常: {e}")
                await asyncio.sleep(10)
    
    async def _save_history_periodically(self):
        """定期保存历史数据"""
        if not self.config_loader.should_save_history():
            return
        
        while self.is_running:
            try:
                # 保存价差历史
                history_file = self.config_loader.get_history_file()
                
                # 确保目录存在
                Path(history_file).parent.mkdir(parents=True, exist_ok=True)
                
                await self.price_calculator.export_spread_history_csv(history_file)
                
                # 每10分钟保存一次
                await asyncio.sleep(600)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"历史数据保存异常: {e}")
                await asyncio.sleep(300)  # 出错后5分钟再试
    
    async def _wait_for_shutdown(self):
        """等待关闭信号"""
        await self.shutdown_event.wait()
        self.logger.info("🛑 接收到关闭信号")
        await self.stop()
    
    async def stop(self):
        """停止监控系统"""
        if not self.is_running:
            return
        
        self.logger.info("🛑 正在停止监控系统...")
        
        self.is_running = False
        
        # 停止显示管理器
        if self.display_manager:
            self.display_manager.stop_display()
        
        # 停止 WebSocket 管理器
        if self.websocket_manager:
            await self.websocket_manager.stop()
        
        # 保存最终历史数据
        if (self.price_calculator and self.config_loader and 
            self.config_loader.should_save_history()):
            try:
                history_file = self.config_loader.get_history_file()
                await self.price_calculator.export_spread_history_csv(history_file)
                self.logger.info(f"✅ 历史数据已保存到: {history_file}")
            except Exception as e:
                self.logger.error(f"❌ 保存历史数据失败: {e}")
        
        self.logger.info("✅ 监控系统已完全停止")
    
    async def add_symbol(self, symbol: str, market_type_str: str) -> bool:
        """
        动态添加监控符号
        
        Args:
            symbol: 符号（如 BTC/USDT）
            market_type_str: 市场类型字符串
            
        Returns:
            bool: 添加是否成功
        """
        try:
            from .models import MarketType
            market_type = MarketType(market_type_str)
            
            if self.websocket_manager:
                success = await self.websocket_manager.add_symbol(symbol, market_type)
                if success:
                    self.logger.info(f"✅ 成功添加监控符号: {symbol} ({market_type.value})")
                return success
            
            return False
            
        except Exception as e:
            self.logger.error(f"❌ 添加符号失败: {e}")
            return False
    
    async def remove_symbol(self, symbol: str, market_type_str: str) -> bool:
        """
        动态移除监控符号
        
        Args:
            symbol: 符号（如 BTC/USDT）
            market_type_str: 市场类型字符串
            
        Returns:
            bool: 移除是否成功
        """
        try:
            from .models import MarketType
            market_type = MarketType(market_type_str)
            
            if self.websocket_manager:
                success = await self.websocket_manager.remove_symbol(symbol, market_type)
                if success:
                    self.logger.info(f"✅ 成功移除监控符号: {symbol} ({market_type.value})")
                return success
            
            return False
            
        except Exception as e:
            self.logger.error(f"❌ 移除符号失败: {e}")
            return False
    
    def get_stats(self) -> dict:
        """获取监控统计信息"""
        if not self.price_calculator:
            return {}
        
        stats = self.price_calculator.get_stats()
        
        return {
            "runtime": stats.get_runtime(),
            "total_updates": stats.total_updates,
            "success_rate": stats.get_success_rate(),
            "max_spread_percentage": float(stats.max_spread_percentage) if stats.max_spread_percentage else None,
            "max_spread_symbol": stats.max_spread_symbol,
            "connected_exchanges": (
                self.websocket_manager.get_connected_exchanges() 
                if self.websocket_manager else []
            )
        }
    
    async def get_current_spreads(self) -> dict:
        """获取当前所有价差数据"""
        if not self.price_calculator:
            return {}
        
        spreads = await self.price_calculator.get_all_current_spreads()
        
        result = {}
        for (symbol, market_type), spread_data in spreads.items():
            key = f"{symbol}_{market_type.value}"
            result[key] = {
                "symbol": symbol,
                "market_type": market_type.value,
                "min_price": float(spread_data.min_price) if spread_data.min_price else None,
                "max_price": float(spread_data.max_price) if spread_data.max_price else None,
                "spread_percentage": float(spread_data.spread_percentage) if spread_data.spread_percentage else None,
                "min_exchange": spread_data.min_exchange,
                "max_exchange": spread_data.max_exchange,
                "timestamp": spread_data.timestamp.isoformat() if spread_data.timestamp else None
            }
        
        return result
    
    def __str__(self) -> str:
        """字符串表示"""
        return f"MultiExchangeMonitor(运行中={self.is_running})"
    
    def __repr__(self) -> str:
        return self.__str__()


# 应用启动函数
async def main(config_path: Optional[str] = None):
    """
    主启动函数
    
    Args:
        config_path: 配置文件路径
    """
    app = MultiExchangeMonitor(config_path)
    
    try:
        success = await app.start()
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n接收到中断信号，正在退出...")
    except Exception as e:
        print(f"应用运行异常: {e}")
        sys.exit(1)
    finally:
        await app.stop()


if __name__ == "__main__":
    # 支持命令行参数
    import argparse
    
    parser = argparse.ArgumentParser(description="多交易所价格监控系统")
    parser.add_argument("--config", "-c", help="配置文件路径")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    
    args = parser.parse_args()
    
    # 设置日志级别
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    
    # 运行应用
    asyncio.run(main(args.config))
