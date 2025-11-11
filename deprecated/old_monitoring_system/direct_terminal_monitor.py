#!/usr/bin/env python3
"""
直接数据流终端监控系统

直接从数据聚合器获取数据，支持debug模式和表格显示
剔除SocketIO中间层，减少延迟和开销
"""

import asyncio
import json
import logging
import time
import os
import sys
import argparse
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass
from collections import defaultdict

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 导入核心模块
from core.data_aggregator import DataAggregator, AggregatedData
from core.domain.models import DataType
from core.di.container import DIContainer
from core.services.implementations.enhanced_monitoring_service import EnhancedMonitoringServiceImpl
from core.adapters.exchanges.adapters.backpack_rest import BackpackRest
from core.infrastructure.config_manager import ConfigManager
from core.logging.logger import get_logger

# 配置日志
logging.basicConfig(level=logging.WARNING)


@dataclass
class PriceData:
    """统一的价格数据结构"""
    symbol: str
    exchange: str
    # 统一字段，兼容ticker和orderbook
    price: float = 0.0  # ticker价格或中间价
    volume: float = 0.0  # ticker成交量或买1+卖1总量
    timestamp: float = 0.0
    last_update: float = 0.0
    
    # orderbook专用字段
    bid_price: float = 0.0  # 买1价格
    bid_volume: float = 0.0  # 买1数量
    ask_price: float = 0.0  # 卖1价格
    ask_volume: float = 0.0  # 卖1数量
    data_type: str = "ticker"  # 数据类型: ticker, orderbook
    
    @property
    def mid_price(self) -> float:
        """计算中间价"""
        if self.data_type == "orderbook" and self.bid_price > 0 and self.ask_price > 0:
            return (self.bid_price + self.ask_price) / 2
        return self.price
    
    @property
    def spread(self) -> float:
        """计算买卖价差"""
        if self.data_type == "orderbook" and self.bid_price > 0 and self.ask_price > 0:
            return self.ask_price - self.bid_price
        return 0.0
    
    @property
    def spread_pct(self) -> float:
        """计算价差百分比"""
        if self.spread > 0 and self.mid_price > 0:
            return (self.spread / self.mid_price) * 100
        return 0.0


@dataclass
class BackpackRestData:
    """Backpack REST API 数据结构"""
    symbol: str
    bid_price: float = 0.0
    ask_price: float = 0.0
    mid_price: float = 0.0
    last_update: float = 0.0
    
    def __post_init__(self):
        if self.bid_price > 0 and self.ask_price > 0:
            self.mid_price = (self.bid_price + self.ask_price) / 2


class DirectTerminalMonitor:
    """直接数据流终端监控客户端"""
    
    def __init__(self, debug_mode: bool = False):
        self.debug_mode = debug_mode
        
        # 数据存储
        self.price_data: Dict[str, PriceData] = {}
        self.message_count = 0
        self.start_time = time.time()
        self.last_update_time = time.time()
        self.connected = False
        
        # 🔥 Backpack REST API 相关
        self.backpack_adapter: Optional[BackpackRest] = None
        self.backpack_rest_data: Dict[str, BackpackRestData] = {}  # key: normalized_symbol
        self.active_polling_tasks: Dict[str, asyncio.Task] = {}  # key: normalized_symbol
        self.polling_symbols: set = set()  # 当前正在轮询的标准化符号
        
        # 显示配置
        self.refresh_interval = 1.0  # 1秒刷新一次显示
        self.max_display_symbols = 200  # 最多显示200个交易对
        
        # 🔥 调试信息队列配置
        self.max_debug_lines = 8  # 最多显示8条调试信息
        self.debug_messages = []  # 调试信息队列
        
        # 数据类型统计
        self.data_types = set()
        
        # 核心服务
        self.container = None
        self.monitoring_service = None
        self.data_aggregator = None
        
        # 运行状态
        self.running = False
        
        # 初始化回调锁
        self.callback_lock = asyncio.Lock()
        
        # 日志配置
        self.logger = get_logger("DirectTerminalMonitor")
    
    async def initialize(self):
        """初始化核心服务"""
        try:
            self.add_debug_message("🔄 初始化依赖注入容器...")
            
            # 创建依赖注入容器
            self.container = DIContainer()
            self.container.initialize()
            
            # 获取监控服务
            self.monitoring_service = self.container.get(EnhancedMonitoringServiceImpl)
            
            # 获取数据聚合器
            self.data_aggregator = self.container.get(DataAggregator)
            
            # 启动监控服务
            self.add_debug_message("🚀 启动监控服务...")
            success = await self.monitoring_service.start()
            
            if success:
                self.add_debug_message("✅ 监控服务启动成功")
                self.connected = True
                
                # 注册数据回调
                self.add_debug_message("📡 注册数据回调...")
                await self.register_callbacks()
                
                # 初始化 Backpack 适配器
                await self.init_backpack_adapter()
                
                # 显示适配器状态
                adapter_status = "✅ 可用" if self.backpack_adapter else "❌ 不可用"
                self.add_debug_message(f"🔧 Backpack REST适配器状态: {adapter_status}")
                
                return True
            else:
                self.add_debug_message("❌ 监控服务启动失败")
                return False
                
        except Exception as e:
            self.add_debug_message(f"❌ 初始化失败: {e}")
            return False
    
    async def register_callbacks(self):
        """注册数据回调"""
        try:
            # 🔥 新增调试日志：记录回调注册过程
            self.add_debug_message("🔄 开始注册数据回调...")
            
            # 注册ticker数据回调
            self.data_aggregator.register_data_callback(
                DataType.TICKER, 
                self.handle_ticker_data
            )
            
            # 🔥 新增调试日志：检查数据聚合器状态
            aggregator_stats = self.data_aggregator.get_statistics()
            self.add_debug_message(f"📊 数据聚合器状态: {aggregator_stats}")
            
            # 🔥 新增调试日志：检查已注册的回调
            self.add_debug_message(f"📋 已注册的回调类型: {list(self.data_aggregator.callbacks.keys()) if hasattr(self.data_aggregator, 'callbacks') else '未知'}")
            
            # 🔥 用户要求删除订单数据功能，只保留ticker和REST API
            # 不再注册 orderbook, trades, user_data 回调
            
            self.add_debug_message("✅ 数据回调注册成功")
            
        except Exception as e:
            self.add_debug_message(f"❌ 注册数据回调失败: {e}")
            import traceback
            self.add_debug_message(f"❌ 错误详情: {traceback.format_exc()}")
            raise
    
    async def init_backpack_adapter(self):
        """初始化 Backpack REST 适配器 - 仅用于公开API"""
        try:
            config_manager = ConfigManager()
            config = config_manager.get_exchange_config("backpack")
            logger = get_logger("BackpackRest")
            
            self.backpack_adapter = BackpackRest(config=config, logger=logger)
            # 只连接，不进行认证 - 我们只使用公开API
            connection_result = await self.backpack_adapter.connect()
            
            if connection_result:
                self.add_debug_message("✅ Backpack REST适配器初始化成功")
                self.add_debug_message("🔧 Backpack REST适配器状态: ✅ 可用")
            else:
                self.add_debug_message("❌ Backpack连接失败")
                self.backpack_adapter = None
            
        except Exception as e:
            self.add_debug_message(f"❌ Backpack适配器初始化失败: {e}")
            self.backpack_adapter = None
    
    def add_debug_message(self, message: str):
        """添加调试信息到队列，自动管理数量"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        full_message = f"[{timestamp}] {message}"
        
        self.debug_messages.append(full_message)
        
        # 保持队列长度不超过最大限制
        if len(self.debug_messages) > self.max_debug_lines:
            self.debug_messages.pop(0)  # 移除最旧的消息
        
        # 在debug模式下立即打印
        if self.debug_mode:
            print(full_message)
    
    async def handle_ticker_data(self, aggregated_data: AggregatedData):
        """处理ticker数据回调"""
        async with self.callback_lock:
            try:
                # 构造数据键
                key = f"{aggregated_data.exchange}_{aggregated_data.symbol}"
                
                # 🔥 删除频繁的调试日志：数据接收日志
                # self.add_debug_message(f"📥 收到{aggregated_data.exchange}数据: {aggregated_data.symbol}")
                
                # 解析ticker数据
                ticker_data = aggregated_data.data
                
                # 🔥 删除频繁的调试日志：特定交易所数据接收日志
                # if aggregated_data.exchange == 'hyperliquid':
                #     self.add_debug_message(f"📥 收到Hyperliquid数据: {aggregated_data.symbol} - {aggregated_data.data}")
                # elif aggregated_data.exchange == 'edgex':
                #     self.add_debug_message(f"📥 收到EdgeX数据: {aggregated_data.symbol} - {aggregated_data.data}")
                
                # 更新价格数据
                await self.update_price_data(key, {
                    'symbol': aggregated_data.symbol,
                    'exchange': aggregated_data.exchange,
                    'price': float(ticker_data.last) if ticker_data.last else 0.0,
                    'volume': float(ticker_data.volume) if ticker_data.volume else 0.0,
                    'timestamp': ticker_data.timestamp.timestamp() if ticker_data.timestamp else time.time(),
                    'last_update': time.time(),
                    'bid_price': float(ticker_data.bid) if ticker_data.bid else 0.0,
                    'ask_price': float(ticker_data.ask) if ticker_data.ask else 0.0,
                }, 'ticker')
                
                # 🔥 删除频繁的调试日志：数据更新完成日志
                # if aggregated_data.exchange == 'hyperliquid':
                #     self.add_debug_message(f"✅ Hyperliquid数据已更新: {key} - 价格${float(ticker_data.last or 0):.4f}")
                # elif aggregated_data.exchange == 'edgex':
                #     self.add_debug_message(f"✅ EdgeX数据已更新: {key} - 价格${float(ticker_data.last or 0):.4f}")
                
                # 更新消息计数和时间戳
                self.message_count += 1
                self.last_update_time = time.time()
                self.data_types.add('ticker')
                
                # 触发Backpack轮询检查
                await self.update_backpack_polling()
                
            except Exception as e:
                # 保留错误日志
                self.add_debug_message(f"❌ 处理ticker数据失败: {e}")
                
                if aggregated_data.exchange == 'hyperliquid':
                    self.add_debug_message(f"❌ Hyperliquid数据处理失败: {aggregated_data.symbol} - {str(e)}")
                elif aggregated_data.exchange == 'edgex':
                    self.add_debug_message(f"❌ EdgeX数据处理失败: {aggregated_data.symbol} - {str(e)}")
    
    async def handle_orderbook_data(self, aggregated_data: AggregatedData):
        """处理orderbook数据回调 - 已禁用"""
        # 🔥 用户要求删除订单数据功能，只保留ticker和REST API
        pass
    
    async def handle_trades_data(self, aggregated_data: AggregatedData):
        """处理trades数据回调 - 已禁用"""
        # 🔥 用户要求删除订单数据功能，只保留ticker和REST API
        pass
    
    async def handle_user_data(self, aggregated_data: AggregatedData):
        """处理user数据回调 - 已禁用"""
        # 🔥 用户要求删除订单数据功能，只保留ticker和REST API
        pass
    
    async def update_price_data(self, key: str, data: Dict[str, Any], data_type: str):
        """更新价格数据"""
        try:
            # 记录数据类型
            self.data_types.add(data_type)
            
            # 🔥 删除频繁的调试日志：数据更新前状态
            # if data['exchange'] == 'hyperliquid':
            #     self.add_debug_message(f"🔄 更新Hyperliquid数据: {key} - 价格${data['price']:.4f}")
            
            # 解析时间戳
            timestamp = self._parse_timestamp(data.get('timestamp', 0))
            last_update = self._parse_timestamp(data.get('last_update', 0))
            
            # 创建或更新价格数据
            if key not in self.price_data:
                self.price_data[key] = PriceData(
                    symbol=data['symbol'],
                    exchange=data['exchange']
                )
                # 🔥 删除频繁的调试日志：新数据创建日志
                # if data['exchange'] == 'hyperliquid':
                #     self.add_debug_message(f"📊 创建新Hyperliquid数据项: {key}")
            
            price_obj = self.price_data[key]
            
            # 更新通用字段
            price_obj.price = float(data.get('price', 0))
            price_obj.volume = float(data.get('volume', 0))
            price_obj.timestamp = timestamp
            price_obj.last_update = last_update
            price_obj.data_type = data_type
            
            # 更新orderbook专用字段
            if data_type == "orderbook":
                price_obj.bid_price = float(data.get('bid_price', 0))
                price_obj.bid_volume = float(data.get('bid_volume', 0))
                price_obj.ask_price = float(data.get('ask_price', 0))
                price_obj.ask_volume = float(data.get('ask_volume', 0))
            
            # 🔥 删除频繁的调试日志：数据更新完成日志
            # if data['exchange'] == 'hyperliquid':
            #     self.add_debug_message(f"✅ Hyperliquid数据更新完成: {key} - 最终价格${price_obj.price:.4f}")
            
        except Exception as e:
            # 保留错误日志
            self.add_debug_message(f"❌ 更新价格数据失败: {e}")
            # 保留特定错误日志
            if data.get('exchange') == 'hyperliquid':
                self.add_debug_message(f"❌ Hyperliquid数据更新失败: {key} - {str(e)}")
                
    def _parse_timestamp(self, timestamp_value) -> float:
        """解析时间戳"""
        try:
            if isinstance(timestamp_value, str):
                # ISO格式时间戳
                if 'T' in timestamp_value:
                    try:
                        dt = datetime.fromisoformat(timestamp_value.replace('Z', '+00:00'))
                        return dt.timestamp()
                    except ValueError:
                        pass
                
                # 直接转换为浮点数
                return float(timestamp_value)
            elif isinstance(timestamp_value, (int, float)):
                return float(timestamp_value)
            else:
                return time.time()
        except:
            return time.time()
    
    async def update_backpack_polling(self):
        """更新Backpack REST API轮询状态 - 严格按照大价差套利机会触发"""
        try:
            if not self.backpack_adapter:
                return
            
            # 计算当前的价差情况
            spreads = self.calculate_spreads()
            
            # 找出需要轮询的标准化符号（🔥只有大价差套利机会且涉及Backpack）
            symbols_to_poll = set()
            
            for normalized_symbol, spread_data in spreads.items():
                # 🔥 严格的触发条件：大价差套利机会 (>0.5%) + 涉及Backpack
                has_large_arbitrage = spread_data['arbitrage_opportunity']  # 这已经是 >0.5% + has_backpack
                
                if has_large_arbitrage:
                    symbols_to_poll.add(normalized_symbol)
                    # 🔥 删除频繁的调试日志：触发轮询的日志
                    # if normalized_symbol not in self.polling_symbols:
                    #     self.add_debug_message(f"🚀 {normalized_symbol} 触发REST API轮询: 大价差套利机会 {spread_data['spread_pct']:.2f}%")
                else:
                    # 🔥 删除频繁的调试日志：停止轮询的日志
                    # if normalized_symbol in self.polling_symbols:
                    #     if spread_data['has_backpack']:
                    #         self.add_debug_message(f"🛑 {normalized_symbol} 停止REST API: 套利机会消失 (当前价差: {spread_data['spread_pct']:.2f}%)")
                    #     else:
                    #         self.add_debug_message(f"🛑 {normalized_symbol} 停止REST API: 不涉及Backpack")
                    pass
            
            # 停止不再需要的轮询任务
            symbols_to_stop = self.polling_symbols - symbols_to_poll
            for symbol in symbols_to_stop:
                if symbol in self.active_polling_tasks:
                    self.active_polling_tasks[symbol].cancel()
                    del self.active_polling_tasks[symbol]
                    # 清理REST API数据
                    if symbol in self.backpack_rest_data:
                        del self.backpack_rest_data[symbol]
                    self.add_debug_message(f"🧹 停止轮询并清理数据: {symbol}")
            
            # 启动新的轮询任务
            symbols_to_start = symbols_to_poll - self.polling_symbols
            for symbol in symbols_to_start:
                if symbol not in self.active_polling_tasks:
                    # 获取对应的 Backpack 符号
                    backpack_symbol = self.get_backpack_symbol_from_normalized(symbol, spreads)
                    if backpack_symbol:
                        task = asyncio.create_task(self.poll_backpack_orderbook(symbol, backpack_symbol))
                        self.active_polling_tasks[symbol] = task
                        self.add_debug_message(f"✅ 开始轮询: {symbol} -> {backpack_symbol}")
            
            # 更新当前轮询的符号集合
            self.polling_symbols = symbols_to_poll
            
            # 🔥 删除频繁的调试日志：轮询状态变化日志（这个可能很频繁）
            # if len(symbols_to_poll) != len(self.polling_symbols):
            #     if symbols_to_poll:
            #         self.add_debug_message(f"🔄 当前轮询符号 ({len(symbols_to_poll)}个): {', '.join(symbols_to_poll)}")
            #     else:
            #         self.add_debug_message("🔄 当前无符号需要轮询 - 没有大价差套利机会")
            
        except Exception as e:
            # 保留错误日志
            self.add_debug_message(f"❌ 更新轮询状态失败: {e}")
    
    def get_backpack_symbol_from_normalized(self, normalized_symbol: str, spreads: Dict) -> Optional[str]:
        """从标准化符号获取Backpack符号"""
        try:
            spread_data = spreads.get(normalized_symbol, {})
            backpack_data = spread_data.get('exchanges', {}).get('backpack', {})
            return backpack_data.get('symbol') if backpack_data else None
        except:
            return None
    
    async def poll_backpack_orderbook(self, normalized_symbol: str, backpack_symbol: str):
        """轮询Backpack订单簿 - 严格按照terminal_monitor.py的实现"""
        try:
            while True:
                try:
                    # 调用 REST API 获取订单簿快照 - 使用公开API
                    if not self.backpack_adapter:
                        break
                    
                    snapshot = await self.backpack_adapter.get_orderbook_snapshot(backpack_symbol)
                    
                    if snapshot:
                        bids = snapshot.get('bids', [])
                        asks = snapshot.get('asks', [])
                        
                        if bids and asks and len(bids[0]) >= 2 and len(asks[0]) >= 2:
                            bid_price = float(bids[0][0])
                            ask_price = float(asks[0][0])
                            
                            # 更新 REST API 数据
                            self.backpack_rest_data[normalized_symbol] = BackpackRestData(
                                symbol=backpack_symbol,
                                bid_price=bid_price,
                                ask_price=ask_price,
                                last_update=time.time()
                            )
                            
                except Exception as e:
                    # 静默处理错误，不影响正常流程
                    if normalized_symbol in self.backpack_rest_data:
                        del self.backpack_rest_data[normalized_symbol]
                        
                await asyncio.sleep(0.5)
                
        except asyncio.CancelledError:
            # 任务被取消
            if normalized_symbol in self.backpack_rest_data:
                del self.backpack_rest_data[normalized_symbol]
                
        except Exception as e:
            if normalized_symbol in self.backpack_rest_data:
                del self.backpack_rest_data[normalized_symbol]
    
    def calculate_spreads(self) -> Dict[str, Dict[str, Any]]:
        """计算价差数据 - 严格按照terminal_monitor.py的逻辑"""
        spreads = {}
        
        try:
            # 🔥 删除频繁的调试日志：计算前的数据状态
            # hyperliquid_data_count = len([k for k, v in self.price_data.items() if v.exchange == 'hyperliquid'])
            # if hyperliquid_data_count > 0:
            #     self.add_debug_message(f"📊 计算价差开始: Hyperliquid数据{hyperliquid_data_count}条")
            
            # 按标准化符号分组
            symbols_data = defaultdict(dict)
            for key, data in self.price_data.items():
                # 🔥 删除频繁的调试日志：符号标准化过程
                original_symbol = data.symbol
                normalized_symbol = self.normalize_symbol(data.symbol, data.exchange)
                
                # if data.exchange == 'hyperliquid':
                #     self.add_debug_message(f"🔄 Hyperliquid符号标准化: {original_symbol} -> {normalized_symbol}")
                
                symbols_data[normalized_symbol][data.exchange] = data
            
            # 🔥 删除频繁的调试日志：标准化后的数据分组日志
            # hyperliquid_symbols = set()
            # for symbol, exchanges in symbols_data.items():
            #     if 'hyperliquid' in exchanges:
            #         hyperliquid_symbols.add(symbol)
            # 
            # if hyperliquid_symbols:
            #     self.add_debug_message(f"📊 Hyperliquid标准化符号: {', '.join(hyperliquid_symbols)}")
            
            # 计算价差
            for symbol, exchanges in symbols_data.items():
                if len(exchanges) < 2:
                    # 🔥 删除频繁的调试日志：单一交易所数据日志
                    # if 'hyperliquid' in exchanges:
                    #     self.add_debug_message(f"⚠️ {symbol} 只有Hyperliquid数据，无法计算价差")
                    continue
                
                # 🔥 删除频繁的调试日志：参与价差计算的交易所日志
                # if 'hyperliquid' in exchanges:
                #     self.add_debug_message(f"📊 {symbol} 参与价差计算: {list(exchanges.keys())}")
                
                # 找到最大价差
                max_spread = 0
                max_spread_pair = ""
                
                exchange_list = list(exchanges.keys())
                spread_details = {}
                
                # 计算传统价差（基于现有数据）
                for i in range(len(exchange_list)):
                    for j in range(i + 1, len(exchange_list)):
                        exchange1 = exchange_list[i]
                        exchange2 = exchange_list[j]
                        
                        data1 = exchanges[exchange1]
                        data2 = exchanges[exchange2]
                        
                        if data1.mid_price > 0 and data2.mid_price > 0:
                            spread = abs(data1.mid_price - data2.mid_price)
                            spread_pct = (spread / min(data1.mid_price, data2.mid_price)) * 100
                            
                            # 🔥 删除频繁的调试日志：Hyperliquid相关价差日志
                            # if 'hyperliquid' in [exchange1, exchange2]:
                            #     self.add_debug_message(f"📊 {symbol} 价差 {exchange1}-{exchange2}: {spread_pct:.2f}%")
                            
                            if spread_pct > max_spread:
                                max_spread = spread_pct
                                max_spread_pair = f"{exchange1}-{exchange2}"
                            
                            spread_details[f"{exchange1}-{exchange2}"] = {
                                'spread': spread,
                                'spread_pct': spread_pct,
                                'price1': data1.mid_price,
                                'price2': data2.mid_price
                            }
                
                # 🔥 计算REST API价差（如果有REST API数据）- 严格按照terminal_monitor.py逻辑
                rest_api_spreads = {}
                if symbol in self.backpack_rest_data and 'backpack' in exchanges:
                    rest_data = self.backpack_rest_data[symbol]
                    
                    for exchange_name in exchange_list:
                        if exchange_name != 'backpack':
                            other_data = exchanges[exchange_name]
                            if other_data.mid_price > 0 and rest_data.mid_price > 0:
                                rest_spread = rest_data.mid_price - other_data.mid_price
                                rest_spread_pct = (rest_spread / other_data.mid_price) * 100 if other_data.mid_price > 0 else 0.0
                                
                                pair_key = f"backpack_{exchange_name}"
                                rest_api_spreads[pair_key] = {
                                    'spread': rest_spread,
                                    'spread_pct': rest_spread_pct,
                                    'rest_mid_price': rest_data.mid_price,
                                    'other_price': other_data.mid_price
                                }
                
                # 检查是否包含Backpack
                has_backpack = 'backpack' in exchanges
                
                # 🔥 按照原来的标准：大价差阈值为0.5%
                arbitrage_opportunity = max_spread > 0.5 and has_backpack
                
                spreads[symbol] = {
                    'spread_pct': max_spread,
                    'max_spread_pair': max_spread_pair,
                    'arbitrage_opportunity': arbitrage_opportunity,
                    'has_backpack': has_backpack,
                    'rest_api_spreads': rest_api_spreads,  # 🔥 添加REST API价差
                    'exchanges': {
                        exchange_id: {
                            'symbol': data.symbol,
                            'price': data.mid_price,
                            'volume': data.volume,
                            'data_type': data.data_type,
                            'last_update': data.last_update
                        }
                        for exchange_id, data in exchanges.items()
                    },
                    'spread_details': spread_details
                }
                
                # 🔥 新增调试日志：记录最终价差结果
                # if 'hyperliquid' in exchanges:
                #     self.add_debug_message(f"✅ {symbol} 价差计算完成: 最大价差{max_spread:.2f}% ({max_spread_pair})")
            
            # 🔥 删除频繁的调试日志：最终结果统计日志
            # hyperliquid_spreads = len([s for s in spreads.values() if 'hyperliquid' in s['exchanges']])
            # if hyperliquid_spreads > 0:
            #     self.add_debug_message(f"📊 价差计算完成: Hyperliquid参与{hyperliquid_spreads}个价差")
            
            return spreads
            
        except Exception as e:
            # 保留错误日志
            self.add_debug_message(f"❌ 计算价差失败: {e}")
            return {}
    
    def normalize_symbol(self, symbol: str, exchange: str) -> str:
        """标准化交易对符号"""
        try:
            symbol = symbol.upper()
            original_symbol = symbol
            
            # 交易所特定的标准化规则
            if exchange == 'backpack':
                # Backpack: SOL_USDC -> SOL/USDC
                if '_' in symbol:
                    parts = symbol.split('_')
                    if len(parts) >= 2:
                        result = f"{parts[0]}/USDC"
                        # 🔥 删除频繁的调试日志：符号转换日志
                        # if self.message_count % 100 == 0:  # 每100条记录一次，避免刷屏
                        #     self.add_debug_message(f"🔄 Backpack符号转换: {original_symbol} -> {result}")
                        return result
                return symbol
            
            elif exchange == 'hyperliquid':
                # Hyperliquid: BTC/USDC:USDC -> BTC/USDC
                if ':USDC' in symbol:
                    # 去掉 :USDC 后缀
                    result = symbol.replace(':USDC', '')
                    # 🔥 删除频繁的调试日志：符号转换日志
                    # self.add_debug_message(f"🔄 Hyperliquid符号转换: {original_symbol} -> {result}")
                    return result
                elif '/USDC' in symbol:
                    # 🔥 删除频繁的调试日志：符号转换日志
                    # if self.message_count % 100 == 0:
                    #     self.add_debug_message(f"🔄 Hyperliquid符号保持: {original_symbol}")
                    return symbol
                elif symbol.endswith('USDC'):
                    base = symbol[:-4]
                    result = f"{base}/USDC"
                    # 🔥 删除频繁的调试日志：符号转换日志
                    # self.add_debug_message(f"🔄 Hyperliquid符号转换: {original_symbol} -> {result}")
                    return result
                elif not '/' in symbol:
                    result = f"{symbol}/USDC"
                    # 🔥 删除频繁的调试日志：符号转换日志
                    # self.add_debug_message(f"🔄 Hyperliquid符号转换: {original_symbol} -> {result}")
                    return result
                return symbol
            
            elif exchange == 'edgex':
                # EdgeX: BTC_USDT -> BTC/USDC
                if '_' in symbol:
                    parts = symbol.split('_')
                    if len(parts) >= 2:
                        result = f"{parts[0]}/USDC"
                        # 🔥 删除频繁的调试日志：符号转换日志
                        # if self.message_count % 100 == 0:  # 每100条记录一次，避免刷屏
                        #     self.add_debug_message(f"🔄 EdgeX符号转换: {original_symbol} -> {result}")
                        return result
                return symbol
            
            else:
                # 默认处理
                if '_' in symbol:
                    parts = symbol.split('_')
                    if len(parts) >= 2:
                        result = f"{parts[0]}/USDC"
                        # 🔥 删除频繁的调试日志：符号转换日志
                        # if self.message_count % 100 == 0:
                        #     self.add_debug_message(f"🔄 默认符号转换: {original_symbol} -> {result}")
                        return result
                return symbol
                
        except Exception as e:
            # 保留错误日志
            self.add_debug_message(f"❌ 标准化符号失败: {e}")
            return symbol
    
    def format_volume(self, volume: float) -> str:
        """格式化成交量"""
        try:
            if volume >= 1_000_000:
                return f"{volume/1_000_000:.1f}M"
            elif volume >= 1_000:
                return f"{volume/1_000:.1f}K"
            else:
                return f"{volume:.1f}"
        except:
            return "0"
    
    def get_freshness_indicator(self, last_update: float) -> str:
        """获取数据新鲜度指示器"""
        try:
            age = time.time() - last_update
            if age < 5:
                return "🟢"
            elif age < 30:
                return "🟡"
            else:
                return "🔴"
        except:
            return "⚪"
    
    def get_time_diff_str(self, last_update: float) -> str:
        """获取时间差字符串"""
        try:
            diff = time.time() - last_update
            if diff < 60:
                return f"{int(diff)}s"
            elif diff < 3600:
                return f"{int(diff/60)}m"
            else:
                return f"{int(diff/3600)}h"
        except:
            return "∞"
    
    def get_exchange_short_name(self, exchange: str) -> str:
        """获取交易所简称"""
        short_names = {
            'backpack': 'BP',
            'hyperliquid': 'HL',
            'edgex': 'EX',
            'binance': 'BN'
        }
        return short_names.get(exchange.lower(), exchange.upper()[:2])
    
    def format_exchange_pair(self, max_spread_pair: str) -> str:
        """格式化交易所对"""
        try:
            if '-' in max_spread_pair:
                ex1, ex2 = max_spread_pair.split('-')
                return f"{self.get_exchange_short_name(ex1)}-{self.get_exchange_short_name(ex2)}"
            return max_spread_pair
        except:
            return max_spread_pair
    
    def display_data(self):
        """显示数据"""
        if self.debug_mode:
            self.display_debug_data()
        else:
            self.display_table_data()
    
    def display_debug_data(self):
        """显示Debug模式数据 - 智能筛选有价值的价差信息"""
        try:
            # 清屏
            os.system('clear' if os.name == 'posix' else 'cls')
            
            # 显示标题
            print("🔥" * 50)
            print("直接数据流终端监控系统 - DEBUG模式")
            print("🔥" * 50)
            
            # 显示统计信息
            uptime = int(time.time() - self.start_time)
            print(f"⏱️  运行时间: {uptime}s | 📊 总消息数: {self.message_count} | 🔗 连接状态: {'✅' if self.connected else '❌'}")
            print(f"💾 价格数据: {len(self.price_data)} 条 | 🎯 数据类型: {', '.join(self.data_types) if self.data_types else 'ticker'} | 🔄 轮询符号: {len(self.polling_symbols)} 个")
            print()
            
            # 🔥 新增：详细的交易所状态信息
            print("📊 交易所详细状态:")
            exchange_stats = {}
            exchange_latest_times = {}
            
            # 统计每个交易所的数据
            for key, data in self.price_data.items():
                exchange = data.exchange
                if exchange not in exchange_stats:
                    exchange_stats[exchange] = 0
                    exchange_latest_times[exchange] = 0
                exchange_stats[exchange] += 1
                exchange_latest_times[exchange] = max(exchange_latest_times[exchange], data.last_update)
            
            # 获取监控服务的交易所状态
            exchange_connections = {}
            if self.monitoring_service and hasattr(self.monitoring_service, 'exchange_manager'):
                try:
                    manager = self.monitoring_service.exchange_manager
                    for exchange_id in ['hyperliquid', 'backpack', 'edgex']:
                        if hasattr(manager, 'adapters') and exchange_id in manager.adapters:
                            adapter = manager.adapters[exchange_id]
                            if hasattr(adapter, 'is_connected'):
                                exchange_connections[exchange_id] = adapter.is_connected()
                            else:
                                exchange_connections[exchange_id] = True  # 假设连接
                        else:
                            exchange_connections[exchange_id] = False
                except Exception as e:
                    self.add_debug_message(f"获取交易所连接状态失败: {e}")
            
            # 显示每个交易所的详细信息
            expected_exchanges = ['hyperliquid', 'backpack', 'edgex']
            current_time = time.time()
            
            for exchange in expected_exchanges:
                # 连接状态
                connection_status = "✅" if exchange_connections.get(exchange, False) else "❌"
                
                # 数据条数
                data_count = exchange_stats.get(exchange, 0)
                
                # 最新数据时间
                latest_time = exchange_latest_times.get(exchange, 0)
                if latest_time > 0:
                    time_diff = current_time - latest_time
                    if time_diff < 5:
                        time_status = f"🟢 {time_diff:.1f}s前"
                    elif time_diff < 30:
                        time_status = f"🟡 {time_diff:.1f}s前"
                    else:
                        time_status = f"🔴 {time_diff:.1f}s前"
                else:
                    time_status = "❌ 无数据"
                
                # 显示交易所状态
                print(f"  {exchange.upper():<12} {connection_status} 连接 | 📊 {data_count:>3} 条数据 | ⏰ {time_status}")
            
            print()
            
            # 🔥 新增：显示数据聚合器详细状态
            try:
                if self.data_aggregator:
                    aggregator_stats = self.data_aggregator.get_statistics()
                    print("📈 数据聚合器状态:")
                    print(f"  📊 总交易所数: {aggregator_stats.get('total_exchanges', 0)}")
                    print(f"  📊 已连接交易所: {aggregator_stats.get('exchanges', [])}")
                    print(f"  📊 订阅符号数: {aggregator_stats.get('total_symbols', 0)}")
                    print(f"  📊 ticker数据条数: {aggregator_stats.get('ticker_data_count', 0)}")
                    print()
            except Exception as e:
                print(f"📈 数据聚合器状态获取失败: {e}")
                print()
            
            # 显示调试信息
            if self.debug_messages:
                print("📋 最新调试信息:")
                for msg in self.debug_messages[-5:]:  # 显示最新5条
                    print(f"  {msg}")
                print()
            
            # 显示最新价格数据（每个交易所最新3条）
            if self.price_data:
                print("💰 各交易所最新价格数据:")
                
                # 按交易所分组
                exchange_data = {}
                for key, data in self.price_data.items():
                    exchange = data.exchange
                    if exchange not in exchange_data:
                        exchange_data[exchange] = []
                    exchange_data[exchange].append((key, data))
                
                # 每个交易所显示最新3条
                for exchange in sorted(exchange_data.keys()):
                    # 按时间排序，取最新3条
                    latest_data = sorted(exchange_data[exchange], 
                                       key=lambda x: x[1].last_update, 
                                       reverse=True)[:3]
                    
                    print(f"  📈 {exchange.upper()} ({len(exchange_data[exchange])}条数据):")
                    for key, data in latest_data:
                        freshness = self.get_freshness_indicator(data.last_update)
                        time_str = self.get_time_diff_str(data.last_update)
                        volume_str = self.format_volume(data.volume)
                        print(f"    {freshness} {key}: ${data.price:.4f} Vol:{volume_str} ({time_str})")
                print()
            
            # 🔥 新增：如果某个交易所没有数据，显示诊断信息
            missing_exchanges = []
            for exchange in expected_exchanges:
                if exchange not in exchange_stats or exchange_stats[exchange] == 0:
                    missing_exchanges.append(exchange)
            
            if missing_exchanges:
                print("⚠️  数据缺失诊断:")
                for exchange in missing_exchanges:
                    connection_status = "已连接" if exchange_connections.get(exchange, False) else "未连接"
                    print(f"  ❌ {exchange.upper()}: {connection_status}但无数据传递")
                print("  💡 建议检查: 数据聚合器回调机制、符号映射、WebSocket连接状态")
                print()
            
            # 计算和显示价差信息
            spreads = self.calculate_spreads()
            
            # 🔥 新增：显示价差分析统计
            exchange_participation = {}
            for symbol, spread_data in spreads.items():
                for exchange in spread_data['exchanges']:
                    if exchange not in exchange_participation:
                        exchange_participation[exchange] = 0
                    exchange_participation[exchange] += 1
            
            print(f"🔍 价差分析 (总计{len(spreads)}个价差):")
            print("  交易所参与度:", end="")
            for exchange, count in sorted(exchange_participation.items()):
                print(f" {exchange.upper()}({count})", end="")
            print()
            print()
            
            # 显示有价值的价差信息
            displayed_spreads = 0
            # 🔥 按价差大小排序，显示所有价差
            sorted_spreads = sorted(spreads.items(), key=lambda x: x[1]['spread_pct'], reverse=True)
            
            for symbol, spread_data in sorted_spreads:
                max_spread = spread_data['spread_pct']
                has_backpack = spread_data['has_backpack']
                rest_api_spreads = spread_data.get('rest_api_spreads', {})
                max_spread_pair = spread_data.get('max_spread_pair', '')
                
                # 参与的交易所
                participating_exchanges = list(spread_data['exchanges'].keys())
                
                # 格式化交易所对比信息
                exchange_pair_info = ""
                if max_spread_pair:
                    formatted_pair = self.format_exchange_pair(max_spread_pair)
                    exchange_pair_info = f" {formatted_pair}"
                
                # 显示所有价差信息（不限制数量）
                if max_spread > 0.3:  # 高价差
                    emoji = "🚨"
                    print(f"  {emoji} {symbol}: 价差 {max_spread:.2f}%{exchange_pair_info} - 交易所: {participating_exchanges}")
                elif max_spread > 0.1:  # 中等价差
                    emoji = "⚠️"
                    print(f"  {emoji} {symbol}: 价差 {max_spread:.2f}%{exchange_pair_info} - 交易所: {participating_exchanges}")
                elif max_spread > 0.05:  # 小价差
                    emoji = "📊"
                    print(f"  {emoji} {symbol}: 价差 {max_spread:.2f}%{exchange_pair_info} - 交易所: {participating_exchanges}")
                else:  # 极小价差
                    emoji = "📉"
                    print(f"  {emoji} {symbol}: 价差 {max_spread:.2f}%{exchange_pair_info} - 交易所: {participating_exchanges}")
                
                displayed_spreads += 1
                
                # 显示REST API价差对比（如果有）
                if rest_api_spreads:
                    for pair_key, rest_data in rest_api_spreads.items():
                        rest_spread_pct = rest_data['spread_pct']
                        print(f"    ├─ 实时: {max_spread:.2f}% | REST API: {rest_spread_pct:+.2f}%")
            
            print(f"\n💡 共显示 {displayed_spreads} 个价差")
            
            # 显示REST API状态
            if self.backpack_rest_data:
                print(f"📡 REST API数据: {len(self.backpack_rest_data)} 个活跃")
                
            print("\n按Ctrl+C退出")
            
        except Exception as e:
            print(f"❌ 显示Debug数据失败: {e}")
            import traceback
            traceback.print_exc()
    
    def display_table_data(self):
        """显示表格模式数据"""
        try:
            # 清屏
            os.system('clear' if os.name == 'posix' else 'cls')
            
            # 计算价差
            spreads = self.calculate_spreads()
            
            # 显示标题
            print("🚀" * 25)
            print("直接数据流终端监控系统")
            print("🚀" * 25)
            print()
            
            # 显示统计信息
            uptime = time.time() - self.start_time
            print(f"⏱️  运行时间: {int(uptime)}s | 📊 总消息数: {self.message_count} | 🔗 连接状态: {'✅' if self.connected else '❌'}")
            print(f"💾 价格数据: {len(self.price_data)} 条 | 🎯 数据类型: {', '.join(self.data_types)} | 🔄 轮询符号: {len(self.polling_symbols)} 个")
            print()
            
            # 🔥 新增：详细的交易所状态信息
            print("📊 交易所状态:")
            exchange_stats = {}
            exchange_latest_times = {}
            
            # 统计每个交易所的数据
            for key, data in self.price_data.items():
                exchange = data.exchange
                if exchange not in exchange_stats:
                    exchange_stats[exchange] = 0
                    exchange_latest_times[exchange] = 0
                exchange_stats[exchange] += 1
                exchange_latest_times[exchange] = max(exchange_latest_times[exchange], data.last_update)
            
            # 获取监控服务的交易所状态
            exchange_connections = {}
            if self.monitoring_service and hasattr(self.monitoring_service, 'exchange_manager'):
                try:
                    manager = self.monitoring_service.exchange_manager
                    for exchange_id in ['hyperliquid', 'backpack', 'edgex']:
                        if hasattr(manager, 'adapters') and exchange_id in manager.adapters:
                            adapter = manager.adapters[exchange_id]
                            if hasattr(adapter, 'is_connected'):
                                exchange_connections[exchange_id] = adapter.is_connected()
                            else:
                                exchange_connections[exchange_id] = True
                        else:
                            exchange_connections[exchange_id] = False
                except Exception as e:
                    self.add_debug_message(f"获取交易所连接状态失败: {e}")
            
            # 显示每个交易所的详细信息（紧凑格式）
            expected_exchanges = ['hyperliquid', 'backpack', 'edgex']
            current_time = time.time()
            
            exchange_status_line = ""
            for i, exchange in enumerate(expected_exchanges):
                if i > 0:
                    exchange_status_line += " | "
                
                # 连接状态
                connection_status = "✅" if exchange_connections.get(exchange, False) else "❌"
                
                # 数据条数
                data_count = exchange_stats.get(exchange, 0)
                
                # 最新数据时间
                latest_time = exchange_latest_times.get(exchange, 0)
                if latest_time > 0:
                    time_diff = current_time - latest_time
                    if time_diff < 5:
                        time_status = "🟢"
                    elif time_diff < 30:
                        time_status = "🟡"  
                    else:
                        time_status = "🔴"
                else:
                    time_status = "❌"
                
                exchange_status_line += f"{exchange.upper():<8} {connection_status}{time_status} {data_count:>2}条"
            
            print(f"  {exchange_status_line}")
            
            # 🔥 新增：显示数据聚合器紧凑状态
            try:
                if self.data_aggregator:
                    aggregator_stats = self.data_aggregator.get_statistics()
                    total_exchanges = aggregator_stats.get('total_exchanges', 0)
                    total_symbols = aggregator_stats.get('total_symbols', 0)
                    ticker_count = aggregator_stats.get('ticker_data_count', 0)
                    print(f"📈 数据聚合器: {total_exchanges}个交易所 | {total_symbols}个符号 | {ticker_count}条ticker数据")
            except Exception as e:
                print(f"📈 数据聚合器状态获取失败: {e}")
            
            # 🔥 新增：价差分析统计（紧凑格式）
            if spreads:
                exchange_participation = {}
                for symbol, spread_data in spreads.items():
                    for exchange in spread_data['exchanges']:
                        if exchange not in exchange_participation:
                            exchange_participation[exchange] = 0
                        exchange_participation[exchange] += 1
                
                participation_line = "🔍 价差分析: " + f"{len(spreads)}个价差 | 参与度: "
                for exchange, count in sorted(exchange_participation.items()):
                    participation_line += f"{exchange.upper()}({count}) "
                print(participation_line.strip())
            
            # 🔥 新增：数据缺失诊断（紧凑格式）
            missing_exchanges = []
            for exchange in expected_exchanges:
                if exchange not in exchange_stats or exchange_stats[exchange] == 0:
                    missing_exchanges.append(exchange)
            
            if missing_exchanges:
                missing_line = "⚠️  数据缺失: " + ", ".join([ex.upper() for ex in missing_exchanges])
                print(missing_line)
            
            print()
            
            # 显示调试信息
            if self.debug_messages:
                print("📋 最新调试信息:")
                for msg in self.debug_messages[-3:]:  # 只显示最新3条
                    print(f"  {msg}")
                print()
            
            # 显示价差数据表格
            if spreads:
                print("💰 价差监控 (按价差百分比排序):")
                print(f"{'符号':<12} {'价差%':<8} {'交易所对':<8} {'状态':<4} {'BP价格':<12} {'其他价格':<25}")
                print("-" * 75)
                
                # 按价差百分比排序
                sorted_spreads = sorted(spreads.items(), key=lambda x: x[1]['spread_pct'], reverse=True)
                
                count = 0
                for symbol, spread_data in sorted_spreads:
                    if count >= self.max_display_symbols:
                        break
                    
                    spread_pct = spread_data['spread_pct']
                    max_spread_pair = self.format_exchange_pair(spread_data['max_spread_pair'])
                    has_arbitrage = spread_data['arbitrage_opportunity']
                    has_backpack = spread_data['has_backpack']
                    
                    # 状态指示器
                    if has_arbitrage:
                        status = "🔥"
                    elif spread_pct > 0.5:
                        status = "⚡"
                    else:
                        status = "📊"
                    
                    # 获取Backpack价格
                    backpack_info = "n/a"
                    if has_backpack:
                        bp_data = spread_data['exchanges']['backpack']
                        if bp_data['data_type'] == 'orderbook':
                            backpack_info = f"${bp_data['price']:.4f}"
                        else:
                            backpack_info = f"${bp_data['price']:.4f}"
                        
                        # 检查是否有REST数据
                        if symbol in self.backpack_rest_data:
                            rest_data = self.backpack_rest_data[symbol]
                            backpack_info = f"${rest_data.bid_price:.4f}/${rest_data.ask_price:.4f}/${rest_data.mid_price:.4f}"
                    
                    # 获取其他交易所价格
                    other_prices = []
                    for exchange_id, exchange_data in spread_data['exchanges'].items():
                        if exchange_id != 'backpack':
                            short_name = self.get_exchange_short_name(exchange_id)
                            price = exchange_data['price']
                            other_prices.append(f"{short_name}${price:.4f}")
                    
                    other_prices_str = " ".join(other_prices)
                    
                    print(f"{symbol:<12} {spread_pct:<7.2f}% {max_spread_pair:<8} {status:<4} {backpack_info:<12} {other_prices_str:<25}")
                    count += 1
            
            else:
                print("⏳ 等待价格数据...")
            
        except Exception as e:
            print(f"❌ 显示表格数据失败: {e}")
    
    async def start_display_loop(self):
        """启动显示循环"""
        while self.running:
            try:
                self.display_data()
                await asyncio.sleep(self.refresh_interval)
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.add_debug_message(f"❌ 显示循环错误: {e}")
                await asyncio.sleep(1)
    
    async def cleanup(self):
        """清理资源"""
        try:
            self.running = False
            
            # 取消所有轮询任务
            for task in self.active_polling_tasks.values():
                task.cancel()
            
            # 等待任务完成
            if self.active_polling_tasks:
                await asyncio.gather(*self.active_polling_tasks.values(), return_exceptions=True)
            
            # 清理Backpack适配器
            if self.backpack_adapter:
                await self.backpack_adapter.disconnect()
            
            # 停止监控服务
            if self.monitoring_service:
                await self.monitoring_service.stop()
            
            self.add_debug_message("✅ 资源清理完成")
            
        except Exception as e:
            self.add_debug_message(f"❌ 清理资源失败: {e}")
    
    async def run(self):
        """运行监控客户端"""
        try:
            # 初始化服务
            success = await self.initialize()
            if not success:
                print("❌ 初始化失败")
                return
            
            self.running = True
            
            # 启动显示循环
            display_task = asyncio.create_task(self.start_display_loop())
            
            # 等待显示循环结束
            await display_task
            
        except KeyboardInterrupt:
            self.add_debug_message("👋 用户中断")
        except Exception as e:
            self.add_debug_message(f"❌ 运行异常: {e}")
        finally:
            await self.cleanup()


async def main():
    """主函数"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='直接数据流终端监控系统')
    parser.add_argument('--debug', action='store_true', help='启用debug模式')
    parser.add_argument('--table', action='store_true', help='启用表格模式(默认)')
    args = parser.parse_args()
    
    # 确定显示模式
    debug_mode = args.debug
    
    if debug_mode:
        print("🔍" * 20)
        print("直接数据流终端监控系统 - DEBUG模式")
        print("🔍" * 20)
    else:
        print("📊" * 20)
        print("直接数据流终端监控系统 - 表格模式")
        print("📊" * 20)
    
    monitor = DirectTerminalMonitor(debug_mode=debug_mode)
    
    try:
        await monitor.run()
    except KeyboardInterrupt:
        print("\n👋 再见!")
    except Exception as e:
        print(f"\n❌ 运行失败: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 再见!")
    except Exception as e:
        print(f"\n❌ 启动失败: {e}")
        sys.exit(1) 