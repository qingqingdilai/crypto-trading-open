#!/usr/bin/env python3
"""
双交易所永续合约监控系统 - 终端客户端

连接到新架构的SocketIO服务器，实时显示价格数据和套利机会
增强功能：Backpack REST API 套利状态下的订单簿轮询
"""

import asyncio
import json
import logging
import time
import os
import sys
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass
from collections import defaultdict

# 确保能够导入socketio
try:
    import socketio
except ImportError:
    print("❌ 需要安装 python-socketio: pip install python-socketio")
    sys.exit(1)

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 导入 Backpack REST 适配器
try:
    from core.adapters.exchanges.adapters.backpack_rest import BackpackRest
    from core.infrastructure.config_manager import ConfigManager
    from core.logging.logger import get_logger
    BACKPACK_AVAILABLE = True
except ImportError as e:
    print(f"⚠️ Backpack适配器导入失败: {e}")
    BACKPACK_AVAILABLE = False

# 配置日志
logging.basicConfig(level=logging.WARNING)
logging.getLogger('socketio').setLevel(logging.ERROR)
logging.getLogger('engineio').setLevel(logging.ERROR)


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


class TerminalMonitor:
    """终端监控客户端"""
    
    def __init__(self, server_url: str = "http://localhost:8765"):
        self.server_url = server_url
        self.sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=0,  # 无限重连
            reconnection_delay=1,
            reconnection_delay_max=5,
            logger=False,
            engineio_logger=False
        )
        
        # 数据存储
        self.price_data: Dict[str, PriceData] = {}
        self.message_count = 0
        self.start_time = time.time()
        self.last_update_time = time.time()
        self.connected = False
        
        # 🔥 新增：Backpack REST API 相关
        self.backpack_adapter: Optional[BackpackRest] = None
        self.backpack_rest_data: Dict[str, BackpackRestData] = {}  # key: normalized_symbol
        self.active_polling_tasks: Dict[str, asyncio.Task] = {}  # key: normalized_symbol
        self.polling_symbols: set = set()  # 当前正在轮询的标准化符号
        
        # 显示配置
        self.refresh_interval = 1.0  # 1秒刷新一次显示
        self.max_display_symbols = 200  # 最多显示200个交易对
        
        # 🔥 新增：调试信息队列配置
        self.max_debug_lines = 8  # 最多显示8条调试信息
        self.debug_messages = []  # 调试信息队列
        
        # 数据类型统计
        self.data_types = set()
        
        # 注册事件处理器
        self.register_events()
        
        # 初始化 Backpack 适配器
        if BACKPACK_AVAILABLE:
            asyncio.create_task(self.init_backpack_adapter())
    
    async def init_backpack_adapter(self):
        """初始化 Backpack REST 适配器"""
        try:
            if not BACKPACK_AVAILABLE:
                return
                
            config_manager = ConfigManager()
            config = config_manager.get_exchange_config("backpack")
            logger = get_logger("BackpackRest")
            
            self.backpack_adapter = BackpackRest(config=config, logger=logger)
            await self.backpack_adapter.connect()
            
            self.add_debug_message("✅ Backpack REST适配器初始化成功")
            
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
    
    def register_events(self):
        """注册Socket.IO事件处理器"""
        
        @self.sio.event
        async def connect():
            self.connected = True
            self.add_debug_message("✅ Socket.IO连接成功")
            
            # 🔥 初始化 Backpack REST 适配器
            await self.init_backpack_adapter()
            
            # 🔥 显示适配器状态
            adapter_status = "✅ 可用" if self.backpack_adapter else "❌ 不可用"
            self.add_debug_message(f"🔧 Backpack REST适配器状态: {adapter_status}")
            
            # 订阅所有数据，包括Hyperliquid
            await self.sio.emit('subscribe', {
                'symbols': [],
                'exchanges': ['backpack', 'edgex', 'hyperliquid'],
                'timestamp': time.time()
            })
        
        @self.sio.event
        async def disconnect():
            self.connected = False
            self.add_debug_message("❌ Socket.IO连接断开")
        
        @self.sio.event
        async def connect_error(data):
            self.add_debug_message(f"❌ Socket.IO连接错误: {data}")
        
        @self.sio.event
        async def batch_update(data):
            """处理批量数据更新"""
            await self.handle_batch_update(data)
        
        @self.sio.event
        async def data_snapshot(data):
            """处理数据快照"""
            await self.handle_data_snapshot(data)
        
        @self.sio.event
        async def subscription_success(data):
            self.add_debug_message(f"✅ 订阅成功: {len(data.get('subscribed_symbols', []))}个交易对")
        
        @self.sio.event
        async def subscription_error(data):
            self.add_debug_message(f"❌ 订阅错误: {data.get('error')}")
    
    async def handle_batch_update(self, data: Dict[str, Any]):
        """处理批量数据更新"""
        try:
            self.message_count += 1
            self.last_update_time = time.time()
            
            # 🔥 使用调试信息队列，控制显示数量
            data_keys = list(data.keys())
            self.add_debug_message(f"🔍 收到批量更新，数据键: {data_keys}")
            
            # 处理ticker数据
            ticker_data = data.get('ticker_data', {})
            if ticker_data:
                self.add_debug_message(f"📊 Ticker数据: {len(ticker_data)}个")
                for key, ticker in ticker_data.items():
                    await self.update_price_data(key, ticker, "ticker")
            
            # 处理orderbook数据
            orderbook_data = data.get('orderbook_data', {})
            if orderbook_data:
                self.add_debug_message(f"📖 OrderBook数据: {len(orderbook_data)}个")
                for key, orderbook in orderbook_data.items():
                    await self.update_price_data(key, orderbook, "orderbook")
            
            # 处理其他数据类型
            trades_data = data.get('trades_data', {})
            user_data = data.get('user_data', {})
            
            if trades_data:
                self.add_debug_message(f"💹 Trades数据: {len(trades_data)}个")
            if user_data:
                self.add_debug_message(f"👤 User数据: {len(user_data)}个")
            
            # 更新数据类型统计
            if ticker_data:
                self.data_types.add("ticker")
            if orderbook_data:
                self.data_types.add("orderbook")
            if trades_data:
                self.data_types.add("trades")
            if user_data:
                self.data_types.add("user_data")
            
            # 🔥 检查是否需要更新 REST API 轮询
            await self.update_backpack_polling()
            
        except Exception as e:
            self.add_debug_message(f"❌ 处理批量更新失败: {e}")
            import traceback
            traceback.print_exc()
    
    async def handle_data_snapshot(self, data: Dict[str, Any]):
        """处理数据快照"""
        try:
            data_keys = list(data.keys())
            self.add_debug_message(f"📊 收到数据快照，数据键: {data_keys}")
            
            # 处理price_data (兼容旧版本)
            price_data = data.get('price_data', {})
            if price_data:
                self.add_debug_message(f"📊 Price数据 (兼容): {len(price_data)}个")
                for key, price_info in price_data.items():
                    await self.update_price_data(key, price_info, "ticker")
            
            # 处理新版本的分类数据
            ticker_data = data.get('ticker_data', {})
            if ticker_data:
                self.add_debug_message(f"📊 Ticker数据: {len(ticker_data)}个")
                for key, ticker in ticker_data.items():
                    await self.update_price_data(key, ticker, "ticker")
            
            orderbook_data = data.get('orderbook_data', {})
            if orderbook_data:
                self.add_debug_message(f"📖 OrderBook数据: {len(orderbook_data)}个")
                for key, orderbook in orderbook_data.items():
                    await self.update_price_data(key, orderbook, "orderbook")
            
            trades_data = data.get('trades_data', {})
            if trades_data:
                self.add_debug_message(f"💹 Trades数据: {len(trades_data)}个")
            
            user_data = data.get('user_data', {})
            if user_data:
                self.add_debug_message(f"👤 User数据: {len(user_data)}个")
            
            # 🔥 检查是否需要更新 REST API 轮询
            await self.update_backpack_polling()
            
        except Exception as e:
            self.add_debug_message(f"❌ 处理数据快照失败: {e}")
            import traceback
            traceback.print_exc()

    async def update_price_data(self, key: str, data: Dict[str, Any], data_type: str):
        """更新价格数据"""
        try:
            exchange = data.get('exchange', '')
            symbol = data.get('symbol', '')
            
            # 处理时间戳
            timestamp = self._parse_timestamp(data.get('timestamp'))
            last_update = self._parse_timestamp(data.get('last_update')) or time.time()
            
            if data_type == "ticker":
                # 处理ticker数据
                try:
                    price = float(data.get('price', 0))
                except (ValueError, TypeError):
                    price = 0.0
                    
                try:
                    volume = float(data.get('volume', 0))
                except (ValueError, TypeError):
                    volume = 0.0
                
                self.price_data[key] = PriceData(
                    symbol=symbol,
                    exchange=exchange,
                    price=price,
                    volume=volume,
                    timestamp=timestamp,
                    last_update=last_update,
                    data_type="ticker"
                )
                # 🔥 减少数据更新日志，只在特定条件下记录
                if self.message_count % 50 == 0:  # 每50次更新记录一次
                    self.add_debug_message(f"✅ 更新Ticker: {exchange}/{symbol} = ${price:.4f}")
                
            elif data_type == "orderbook":
                # 处理orderbook数据
                bids = data.get('bids', [])
                asks = data.get('asks', [])
                
                # 安全获取买1和卖1，增加验证
                bid_price = 0.0
                bid_volume = 0.0
                ask_price = 0.0
                ask_volume = 0.0
                
                if bids and len(bids) > 0 and len(bids[0]) >= 2:
                    try:
                        bid_price = float(bids[0][0])
                        bid_volume = float(bids[0][1])
                    except (ValueError, TypeError, IndexError):
                        pass
                
                if asks and len(asks) > 0 and len(asks[0]) >= 2:
                    try:
                        ask_price = float(asks[0][0])
                        ask_volume = float(asks[0][1])
                    except (ValueError, TypeError, IndexError):
                        pass
                
                # 计算中间价和总量 - 增加安全检查
                mid_price = 0.0
                if bid_price > 0 and ask_price > 0:
                    mid_price = (bid_price + ask_price) / 2
                
                total_volume = bid_volume + ask_volume
                
                self.price_data[key] = PriceData(
                    symbol=symbol,
                    exchange=exchange,
                    price=mid_price,
                    volume=total_volume,
                    timestamp=timestamp,
                    last_update=last_update,
                    bid_price=bid_price,
                    bid_volume=bid_volume,
                    ask_price=ask_price,
                    ask_volume=ask_volume,
                    data_type="orderbook"
                )
                # 🔥 减少orderbook更新日志，只在特定条件下记录
                if self.message_count % 100 == 0:  # 每100次更新记录一次
                    self.add_debug_message(f"✅ 更新OrderBook: {exchange}/{symbol} = 买1${bid_price:.4f} 卖1${ask_price:.4f}")
            
        except Exception as e:
            print(f"❌ 更新价格数据失败 {key}: {e}")
            import traceback
            traceback.print_exc()
    
    async def update_backpack_polling(self):
        """更新 Backpack REST API 轮询状态"""
        try:
            if not self.backpack_adapter:
                return
            
            # 计算当前的价差情况
            spreads = self.calculate_spreads()
            
            # 找出需要轮询的标准化符号（🔥状态且涉及Backpack）
            symbols_to_poll = set()
            
            for normalized_symbol, spread_data in spreads.items():
                # 检查是否有套利机会（🔥状态）
                has_arbitrage = len(spread_data['arbitrage_opportunities']) > 0
                
                # 🔥 检查套利机会是否涉及BP交易所
                has_bp_arbitrage = False
                bp_arbitrage_pairs = []
                if has_arbitrage:
                    for arb_opp in spread_data['arbitrage_opportunities']:
                        if arb_opp['buy_from'] == 'backpack' or arb_opp['sell_to'] == 'backpack':
                            has_bp_arbitrage = True
                            bp_arbitrage_pairs.append(arb_opp['direction'])
                
                # 🔥 新增：检查是否有大价差（与显示🔥图标的逻辑一致）
                has_large_spread = abs(spread_data['max_spread']) > 0.5
                
                # 检查是否涉及Backpack交易所
                has_backpack = 'backpack' in spread_data['exchanges']
                
                # 🔥 调试信息：显示每个符号的状态（控制频率）
                if has_backpack and self.message_count % 100 == 0:  # 每100次显示一次
                    arb_info = f", BP套利对: {', '.join(bp_arbitrage_pairs)}" if bp_arbitrage_pairs else ""
                    self.add_debug_message(f"🔍 {normalized_symbol}: 套利={has_arbitrage}, BP套利={has_bp_arbitrage}, 大价差={has_large_spread}({spread_data['max_spread']:.2f}%){arb_info}")
                
                # 🔥 修改条件：BP套利机会 OR (大价差 AND 涉及BP)
                if has_bp_arbitrage or (has_large_spread and has_backpack):
                    symbols_to_poll.add(normalized_symbol)
                    # 🔥 调试信息：显示触发原因（只在状态变化时显示）
                    if normalized_symbol not in self.polling_symbols:
                        trigger_reason = "BP套利机会" if has_bp_arbitrage else "大价差+涉及BP"
                        self.add_debug_message(f"✅ {normalized_symbol} 触发REST API轮询: {trigger_reason}")
                else:
                    # 🔥 调试信息：显示不触发的原因（只在状态变化时显示）
                    if normalized_symbol in self.polling_symbols:
                        if has_backpack and has_arbitrage and not has_bp_arbitrage:
                            all_arb_pairs = [arb['direction'] for arb in spread_data['arbitrage_opportunities']]
                            self.add_debug_message(f"❌ {normalized_symbol} 停止REST API: 套利机会不涉及BP ({', '.join(all_arb_pairs)})")
                        else:
                            self.add_debug_message(f"❌ {normalized_symbol} 停止REST API: 无BP套利机会或大价差")
            
            # 停止不再需要的轮询任务
            symbols_to_stop = self.polling_symbols - symbols_to_poll
            for symbol in symbols_to_stop:
                if symbol in self.active_polling_tasks:
                    self.active_polling_tasks[symbol].cancel()
                    del self.active_polling_tasks[symbol]
                    self.add_debug_message(f"🛑 停止轮询: {symbol}")
            
            # 启动新的轮询任务
            symbols_to_start = symbols_to_poll - self.polling_symbols
            for symbol in symbols_to_start:
                if symbol not in self.active_polling_tasks:
                    # 获取对应的 Backpack 符号
                    backpack_symbol = self.get_backpack_symbol_from_normalized(symbol, spreads)
                    if backpack_symbol:
                        task = asyncio.create_task(self.poll_backpack_orderbook(symbol, backpack_symbol))
                        self.active_polling_tasks[symbol] = task
                        self.add_debug_message(f"🚀 开始轮询: {symbol} -> {backpack_symbol}")
            
            # 更新当前轮询的符号集合
            self.polling_symbols = symbols_to_poll
            
            # 🔥 添加调试信息：显示轮询状态
            if symbols_to_poll != self.polling_symbols:
                if symbols_to_poll:
                    self.add_debug_message(f"🔄 当前轮询符号: {', '.join(symbols_to_poll)}")
                else:
                    self.add_debug_message("🔄 当前无符号需要轮询")
            
            # 🔥 添加调试信息：显示REST API数据状态
            if self.backpack_rest_data and self.message_count % 200 == 0:  # 每200次显示一次
                active_rest_symbols = list(self.backpack_rest_data.keys())
                self.add_debug_message(f"📊 REST API数据: {', '.join(active_rest_symbols)}")
            
        except Exception as e:
            self.add_debug_message(f"❌ 更新轮询状态失败: {e}")
    
    def get_backpack_symbol_from_normalized(self, normalized_symbol: str, spreads: Dict) -> Optional[str]:
        """从标准化符号获取对应的 Backpack 符号"""
        try:
            spread_data = spreads.get(normalized_symbol, {})
            backpack_data = spread_data.get('exchanges', {}).get('backpack')
            if backpack_data:
                return backpack_data['symbol']
            return None
        except Exception:
            return None
    
    async def poll_backpack_orderbook(self, normalized_symbol: str, backpack_symbol: str):
        """轮询 Backpack 订单簿数据"""
        try:
            while True:
                try:
                    # 调用 REST API 获取订单簿快照
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
                            
                            # 每10次记录一次成功日志
                            if self.message_count % 10 == 0:
                                self.add_debug_message(f"📡 REST API更新: {normalized_symbol} 买1${bid_price:.4f} 卖1${ask_price:.4f}")
                    
                except Exception as e:
                    self.add_debug_message(f"❌ REST API轮询失败: {normalized_symbol} (BackpackSymbol: {backpack_symbol}) - {e}")
                    # 清理失败的数据
                    if normalized_symbol in self.backpack_rest_data:
                        del self.backpack_rest_data[normalized_symbol]
                
                # 等待 0.5 秒
                await asyncio.sleep(0.5)
                
        except asyncio.CancelledError:
            # 任务被取消，清理数据
            if normalized_symbol in self.backpack_rest_data:
                del self.backpack_rest_data[normalized_symbol]
            self.add_debug_message(f"🧹 轮询任务已取消: {normalized_symbol}")
        except Exception as e:
            self.add_debug_message(f"❌ 轮询任务异常: {normalized_symbol} - {e}")
    
    def _parse_timestamp(self, timestamp_value) -> float:
        """解析时间戳，支持多种格式"""
        if timestamp_value is None:
            return time.time()
        
        # 如果已经是数字，直接返回
        if isinstance(timestamp_value, (int, float)):
            return float(timestamp_value)
        
        # 如果是字符串，尝试解析ISO格式
        if isinstance(timestamp_value, str):
            try:
                # 解析ISO格式时间戳
                from datetime import datetime
                dt = datetime.fromisoformat(timestamp_value.replace('Z', '+00:00'))
                return dt.timestamp()
            except ValueError:
                try:
                    # 尝试作为数字字符串解析
                    return float(timestamp_value)
                except ValueError:
                    # 如果都失败了，返回当前时间
                    return time.time()
        
        # 其他情况返回当前时间
        return time.time()
    
    def format_volume(self, volume: float) -> str:
        """格式化成交量"""
        if volume >= 1_000_000:
            return f"{volume/1_000_000:.2f}M"
        elif volume >= 1_000:
            return f"{volume/1_000:.2f}K"
        else:
            return f"{volume:.2f}"
    
    def get_freshness_indicator(self, last_update: float) -> str:
        """获取数据新鲜度指示器"""
        age = time.time() - last_update
        if age <= 2:
            return "🟢"  # 实时 (<2s)
        elif age <= 5:
            return "🟡"  # 延时 (2-5s)
        else:
            return "🔴"  # 过时 (>5s)
    
    def get_time_diff_str(self, last_update: float) -> str:
        """获取时间差字符串"""
        age = time.time() - last_update
        if age < 60:
            return f"{int(age)}s"
        elif age < 3600:
            return f"{int(age/60)}m"
        else:
            return f"{int(age/3600)}h"
    
    def get_exchange_short_name(self, exchange: str) -> str:
        """获取交易所简短名称"""
        exchange_mapping = {
            'backpack': 'bp',
            'edgex': 'edgex',
            'hyperliquid': 'hype'
        }
        return exchange_mapping.get(exchange, exchange)
    
    def format_exchange_pair(self, max_spread_pair: str) -> str:
        """格式化交易所对比信息，如 bp-hype, edgex-hype"""
        if not max_spread_pair:
            return "N/A"
        
        # max_spread_pair 格式: "exchange1_exchange2"
        parts = max_spread_pair.split('_')
        if len(parts) != 2:
            return "N/A"
        
        exchange1_short = self.get_exchange_short_name(parts[0])
        exchange2_short = self.get_exchange_short_name(parts[1])
        
        return f"{exchange1_short}-{exchange2_short}"
    
    def normalize_symbol(self, symbol: str, exchange: str) -> str:
        """标准化交易对符号"""
        # 移除交易所特有的后缀和前缀
        normalized = symbol.upper()
        
        if exchange == 'backpack':
            # Backpack: BTC_USDC_PERP -> BTC
            if normalized.endswith('_USDC_PERP'):
                normalized = normalized.replace('_USDC_PERP', '')
        elif exchange == 'edgex':
            # EdgeX: BTC_USDT -> BTC, 1000BONK_USDT -> BONK
            if normalized.endswith('_USDT'):
                normalized = normalized.replace('_USDT', '')
            # 处理特殊的1000倍符号
            if normalized.startswith('1000'):
                if normalized in ['1000BONK', '1000SHIB']:
                    normalized = normalized[4:]  # 移除1000前缀
        elif exchange == 'hyperliquid':
            # Hyperliquid: BTC-USD -> BTC, ETH-USD -> ETH
            if normalized.endswith('-USD'):
                normalized = normalized.replace('-USD', '')
            # 处理其他格式
            if '/' in normalized:
                normalized = normalized.split('/')[0]
        
        return normalized

    def calculate_spreads(self) -> Dict[str, Dict[str, Any]]:
        """计算价差（支持ticker和orderbook）"""
        spreads = {}
        
        # 按标准化符号分组
        symbols_data = defaultdict(dict)
        for key, data in self.price_data.items():
            normalized_symbol = self.normalize_symbol(data.symbol, data.exchange)
            symbols_data[normalized_symbol][data.exchange] = data
        
        # 计算价差 - 支持所有可能的交易所组合
        for normalized_symbol, exchanges in symbols_data.items():
            exchange_names = list(exchanges.keys())
            
            # 至少需要2个交易所才能计算价差
            if len(exchange_names) < 2:
                continue
            
            # 创建价差数据结构
            spread_data = {
                'symbol': normalized_symbol,
                'exchanges': {},
                'spreads': {},
                'arbitrage_opportunities': [],  # 套利机会
                'max_spread': 0,
                'max_spread_pair': None,
                'data_types': set(),
                'rest_api_spreads': {}  # 🔥 新增：REST API 价差
            }
            
            # 收集所有交易所的数据
            for exchange_name in exchange_names:
                data = exchanges[exchange_name]
                spread_data['data_types'].add(data.data_type)
                
                exchange_info = {
                    'symbol': data.symbol,
                    'price': data.mid_price,  # 使用中间价
                    'volume': data.volume,
                    'freshness': self.get_freshness_indicator(data.last_update),
                    'time': self.get_time_diff_str(data.last_update),
                    'last_update': data.last_update,
                    'data_type': data.data_type
                }
                
                # 添加orderbook特有信息
                if data.data_type == "orderbook":
                    exchange_info.update({
                        'bid_price': data.bid_price,
                        'bid_volume': data.bid_volume,
                        'ask_price': data.ask_price,
                        'ask_volume': data.ask_volume,
                        'spread': data.spread,
                        'spread_pct': data.spread_pct
                    })
                
                spread_data['exchanges'][exchange_name] = exchange_info
            
            # 计算传统价差（中间价对比）- 增加安全检查
            for i, exchange1 in enumerate(exchange_names):
                for j, exchange2 in enumerate(exchange_names):
                    if i >= j:  # 避免重复计算
                        continue
                    
                    data1 = exchanges[exchange1]
                    data2 = exchanges[exchange2]
                    
                    # 安全检查：确保价格大于0
                    if data1.mid_price > 0 and data2.mid_price > 0:
                        spread = data1.mid_price - data2.mid_price
                        # 安全计算百分比，避免除零错误
                        spread_pct = (spread / data2.mid_price) * 100 if data2.mid_price > 0 else 0.0
                        
                        pair_key = f"{exchange1}_{exchange2}"
                        spread_data['spreads'][pair_key] = {
                            'spread': spread,
                            'spread_pct': spread_pct,
                            'higher_exchange': exchange1 if spread > 0 else exchange2,
                            'lower_exchange': exchange2 if spread > 0 else exchange1
                        }
                        
                        # 记录最大价差
                        if abs(spread_pct) > abs(spread_data['max_spread']):
                            spread_data['max_spread'] = spread_pct
                            spread_data['max_spread_pair'] = pair_key
            
            # 🔥 计算 REST API 价差（如果有 REST API 数据）
            if normalized_symbol in self.backpack_rest_data and 'backpack' in exchanges:
                rest_data = self.backpack_rest_data[normalized_symbol]
                
                for exchange_name in exchange_names:
                    if exchange_name != 'backpack':
                        other_data = exchanges[exchange_name]
                        if other_data.mid_price > 0 and rest_data.mid_price > 0:
                            rest_spread = rest_data.mid_price - other_data.mid_price
                            rest_spread_pct = (rest_spread / other_data.mid_price) * 100 if other_data.mid_price > 0 else 0.0
                            
                            pair_key = f"backpack_{exchange_name}"
                            spread_data['rest_api_spreads'][pair_key] = {
                                'spread': rest_spread,
                                'spread_pct': rest_spread_pct,
                                'rest_mid_price': rest_data.mid_price,
                                'other_price': other_data.mid_price
                            }
            
            # 计算套利机会（仅限orderbook数据）- 增加安全检查
            orderbook_exchanges = [(name, data) for name, data in exchanges.items() 
                                 if data.data_type == "orderbook"]
            
            for i, (exchange1, data1) in enumerate(orderbook_exchanges):
                for j, (exchange2, data2) in enumerate(orderbook_exchanges):
                    if i >= j:  # 避免重复计算
                        continue
                    
                    # 检查套利机会：A的买1 > B的卖1
                    if data1.bid_price > 0 and data2.ask_price > 0 and data1.bid_price > data2.ask_price:
                        profit = data1.bid_price - data2.ask_price
                        # 安全计算百分比，避免除零错误
                        profit_pct = (profit / data2.ask_price) * 100 if data2.ask_price > 0 else 0.0
                        
                        spread_data['arbitrage_opportunities'].append({
                            'buy_from': exchange2,
                            'sell_to': exchange1,
                            'buy_price': data2.ask_price,
                            'sell_price': data1.bid_price,
                            'profit': profit,
                            'profit_pct': profit_pct,
                            'direction': f"{exchange2}→{exchange1}"
                        })
                    
                    # 检查反向套利机会：B的买1 > A的卖1
                    if data2.bid_price > 0 and data1.ask_price > 0 and data2.bid_price > data1.ask_price:
                        profit = data2.bid_price - data1.ask_price
                        # 安全计算百分比，避免除零错误
                        profit_pct = (profit / data1.ask_price) * 100 if data1.ask_price > 0 else 0.0
                        
                        spread_data['arbitrage_opportunities'].append({
                            'buy_from': exchange1,
                            'sell_to': exchange2,
                            'buy_price': data1.ask_price,
                            'sell_price': data2.bid_price,
                            'profit': profit,
                            'profit_pct': profit_pct,
                            'direction': f"{exchange1}→{exchange2}"
                        })
            
            if spread_data['spreads'] or spread_data['arbitrage_opportunities']:
                spreads[normalized_symbol] = spread_data
        
        return spreads
    
    def display_single_exchange_data(self, spreads: Dict[str, Dict[str, Any]]):
        """显示只在单个交易所有数据的交易对"""
        # 获取已经配对的符号
        paired_symbols = set()
        for symbol, data in spreads.items():
            for exchange_name, exchange_data in data['exchanges'].items():
                paired_symbols.add(exchange_data['symbol'])
        
        # 找出未配对的数据
        unpaired_data = []
        for key, data in self.price_data.items():
            if data.symbol not in paired_symbols and data.price > 0:
                unpaired_data.append(data)
        
        if unpaired_data:
            print()
            print("📋 单独交易所数据 (未配对):")
            print("-" * 100)
            print("交易所".ljust(12), "符号".ljust(30), "价格".ljust(15), "成交量".ljust(15), "时效".ljust(15))
            print("-" * 100)
            
            # 按交易所分组排序
            unpaired_data.sort(key=lambda x: (x.exchange, x.symbol))
            
            for data in unpaired_data[:30]:  # 最多显示30个
                exchange_name = {"backpack": "Backpack", "edgex": "EdgeX", "hyperliquid": "Hyperliquid"}.get(data.exchange, data.exchange)
                price = f"${data.price:.4f}"
                volume = self.format_volume(data.volume)
                freshness = self.get_freshness_indicator(data.last_update)
                time_str = self.get_time_diff_str(data.last_update) if freshness != "🟢" else ""
                
                print(exchange_name.ljust(12), end="")
                print(data.symbol.ljust(30), end="")
                print(price.ljust(15), end="")
                print(volume.ljust(15), end="")
                print(f"{freshness}{time_str}".ljust(15))
            
            if len(unpaired_data) > 30:
                print(f"... 还有 {len(unpaired_data) - 30} 个交易对未显示")
            
            print("-" * 100)
    
    def display_data(self):
        """显示数据表格（智能适配ticker和orderbook）"""
        try:
            # 清屏
            os.system('clear' if os.name == 'posix' else 'cls')
            
            # 显示标题和统计
            print("=" * 220)  # 🔥 增加宽度以适应新列
            print("🚀 智能交易监控系统 - 支持Ticker和OrderBook数据 + Backpack REST API")
            print("=" * 220)
            
            # 连接状态
            status = "🟢 已连接" if self.connected else "🔴 未连接"
            uptime = int(time.time() - self.start_time)
            msg_rate = self.message_count / max(uptime, 1)
            
            print(f"状态: {status} | 运行时间: {uptime}s | 消息总数: {self.message_count} | 消息/秒: {msg_rate:.1f}")
            
            # 显示数据统计
            total_data_points = len(self.price_data)
            exchanges = set(data.exchange for data in self.price_data.values())
            
            # 计算每个交易所的数据统计
            backpack_count = len([d for d in self.price_data.values() if d.exchange == 'backpack'])
            edgex_count = len([d for d in self.price_data.values() if d.exchange == 'edgex'])
            hyperliquid_count = len([d for d in self.price_data.values() if d.exchange == 'hyperliquid'])
            
            # 数据类型统计
            data_types_str = ", ".join(self.data_types) if self.data_types else "无"
            
            # 价差数据
            spreads = self.calculate_spreads()
            paired_count = len(spreads)
            
            # 套利机会统计
            total_arbitrage = sum(len(data['arbitrage_opportunities']) for data in spreads.values())
            
            # 🔥 REST API 统计
            rest_api_count = len(self.backpack_rest_data)
            polling_count = len(self.polling_symbols)
            
            print(f"数据点总数: {total_data_points} | 交易对配对: {paired_count} | 套利机会: {total_arbitrage}")
            print(f"数据类型: {data_types_str} | 交易所: {', '.join(exchanges) if exchanges else '无'}")
            print(f"Backpack: {backpack_count}个 | EdgeX: {edgex_count}个 | Hyperliquid: {hyperliquid_count}个")
            print(f"🔥 REST API: {rest_api_count}个活跃 | 轮询中: {polling_count}个 | 更新时间: {datetime.now().strftime('%H:%M:%S')}")
            
            # 🔥 显示调试信息队列（固定数量，不会覆盖价差表格）
            if self.debug_messages:
                print()
                print("📄 最近数据接收:")
                for debug_msg in self.debug_messages:
                    print(f"  {debug_msg}")
            
            print()
            
            if not spreads:
                print("📊 等待数据中...")
                if total_data_points > 0:
                    print("🔍 数据详情:")
                    
                    # 按交易所分组显示数据
                    for exchange_name in ['backpack', 'edgex', 'hyperliquid']:
                        exchange_data = {k: v for k, v in self.price_data.items() if v.exchange == exchange_name}
                        if exchange_data:
                            print(f"   {exchange_name.title()}数据 ({len(exchange_data)}个):")
                            for key, data in list(exchange_data.items())[:3]:
                                if data.data_type == "orderbook":
                                    print(f"     {data.symbol} = 买1${data.bid_price:.4f} 卖1${data.ask_price:.4f} 中间${data.mid_price:.4f}")
                                else:
                                    print(f"     {data.symbol} = ${data.price:.4f}")
                else:
                    print("⏳ 正在连接和获取数据...")
                return
            
            # 根据数据类型显示不同的表头
            has_orderbook = any("orderbook" in data['data_types'] for data in spreads.values())
            
            if has_orderbook:
                # OrderBook数据表头 - 🔥 增加 REST API 列
                print("币种".ljust(8), end="")
                print("Backpack".ljust(50), end="")
                print("BP-REST API".ljust(30), end="")  # 🔥 新增列
                print("EdgeX".ljust(50), end="")
                print("Hyperliquid".ljust(50), end="")
                print("套利分析".ljust(40))  # 🔥 增加宽度
                print("-" * 220)
                print("".ljust(8), end="")
                print("买1价/量".ljust(18), "卖1价/量".ljust(18), "价差".ljust(8), "时效".ljust(6), end="")
                print("买1/卖1/中间价".ljust(30), end="")  # 🔥 新增列标题
                print("买1价/量".ljust(18), "卖1价/量".ljust(18), "价差".ljust(8), "时效".ljust(6), end="")
                print("买1价/量".ljust(18), "卖1价/量".ljust(18), "价差".ljust(8), "时效".ljust(6), end="")
                print("实时%/API%".ljust(15), "机会".ljust(25))  # 🔥 修改价差列
                print("-" * 220)
            else:
                # Ticker数据表头 - 🔥 增加 REST API 列
                print("币种".ljust(8), end="")
                print("Backpack".ljust(35), end="")
                print("BP-REST API".ljust(25), end="")  # 🔥 新增列
                print("EdgeX".ljust(35), end="")
                print("Hyperliquid".ljust(35), end="")
                print("价差分析".ljust(40))  # 🔥 增加宽度
                print("-" * 180)
                print("".ljust(8), end="")
                print("价格".ljust(15), "成交量".ljust(10), "时效".ljust(10), end="")
                print("买1/卖1/中间价".ljust(25), end="")  # 🔥 修改列标题，在ticker模式也显示完整格式
                print("价格".ljust(15), "成交量".ljust(10), "时效".ljust(10), end="")
                print("价格".ljust(15), "成交量".ljust(10), "时效".ljust(10), end="")
                print("实时%".ljust(10), "API%".ljust(10), "对比".ljust(12), "状态".ljust(8))  # 🔥 修改价差列
                print("-" * 180)
            
            # 数据行 - 优先显示有套利机会的交易对
            sorted_spreads = sorted(spreads.items(), 
                                  key=lambda x: (len(x[1]['arbitrage_opportunities']), abs(x[1]['max_spread'])), 
                                  reverse=True)
            
            # 显示所有交易对
            displayed_count = 0
            for symbol, data in sorted_spreads:
                if displayed_count >= self.max_display_symbols:
                    break
                displayed_count += 1
                
                # 币种名称
                print(symbol.ljust(8), end="")
                
                # Backpack 数据
                if 'backpack' in data['exchanges']:
                    exchange_data = data['exchanges']['backpack']
                    
                    if has_orderbook and exchange_data['data_type'] == 'orderbook':
                        # OrderBook数据显示
                        bid_str = f"${exchange_data['bid_price']:.4f}({exchange_data['bid_volume']:.1f})"
                        ask_str = f"${exchange_data['ask_price']:.4f}({exchange_data['ask_volume']:.1f})"
                        spread_str = f"{exchange_data['spread_pct']:.2f}%"
                        
                        print(bid_str.ljust(18), end="")
                        print(ask_str.ljust(18), end="")
                        print(spread_str.ljust(8), end="")
                        print(f"{exchange_data['freshness']}{exchange_data['time']}".ljust(6), end="")
                    else:
                        # Ticker数据显示
                        price_str = f"${exchange_data['price']:.4f}"
                        volume = self.format_volume(exchange_data['volume'])
                        
                        if has_orderbook:
                            print(price_str.ljust(18), end="")
                            print("N/A".ljust(18), end="")
                            print("N/A".ljust(8), end="")
                            print(f"{exchange_data['freshness']}{exchange_data['time']}".ljust(6), end="")
                        else:
                            print(price_str.ljust(15), end="")
                            print(volume.ljust(10), end="")
                            print(f"{exchange_data['freshness']}{exchange_data['time']}".ljust(10), end="")
                else:
                    # Backpack 没有数据
                    if has_orderbook:
                        print("N/A".ljust(50), end="")
                    else:
                        print("N/A".ljust(35), end="")
                
                # 🔥 Backpack REST API 数据列
                if symbol in self.backpack_rest_data:
                    rest_data = self.backpack_rest_data[symbol]
                    
                    # 🔥 添加调试信息：显示REST API数据的具体值
                    if self.message_count % 50 == 0:  # 每50次显示一次，避免刷屏
                        self.add_debug_message(f"🔍 REST API数据 {symbol}: bid={rest_data.bid_price:.4f}, ask={rest_data.ask_price:.4f}, mid={rest_data.mid_price:.4f}")
                    
                    if has_orderbook:
                        # OrderBook模式：显示完整的买1/卖1/中间价
                        rest_str = f"${rest_data.bid_price:.4f}/${rest_data.ask_price:.4f}/${rest_data.mid_price:.4f}"
                        print(rest_str.ljust(30), end="")
                    else:
                        # Ticker模式：也显示完整的买1/卖1/中间价（因为REST API获取的是orderbook数据）
                        rest_str = f"${rest_data.bid_price:.4f}/${rest_data.ask_price:.4f}/${rest_data.mid_price:.4f}"
                        print(rest_str.ljust(25), end="")
                else:
                    if has_orderbook:
                        print("n/a".ljust(30), end="")
                    else:
                        print("n/a".ljust(25), end="")
                
                # EdgeX 数据
                if 'edgex' in data['exchanges']:
                    exchange_data = data['exchanges']['edgex']
                    
                    if has_orderbook and exchange_data['data_type'] == 'orderbook':
                        bid_str = f"${exchange_data['bid_price']:.4f}({exchange_data['bid_volume']:.1f})"
                        ask_str = f"${exchange_data['ask_price']:.4f}({exchange_data['ask_volume']:.1f})"
                        spread_str = f"{exchange_data['spread_pct']:.2f}%"
                        
                        print(bid_str.ljust(18), end="")
                        print(ask_str.ljust(18), end="")
                        print(spread_str.ljust(8), end="")
                        print(f"{exchange_data['freshness']}{exchange_data['time']}".ljust(6), end="")
                    else:
                        if has_orderbook:
                            price_str = f"${exchange_data['price']:.4f}"
                            print(price_str.ljust(18), end="")
                            print("N/A".ljust(18), end="")
                            print("N/A".ljust(8), end="")
                            print(f"{exchange_data['freshness']}{exchange_data['time']}".ljust(6), end="")
                        else:
                            price = f"${exchange_data['price']:.4f}"
                            volume = self.format_volume(exchange_data['volume'])
                            print(price.ljust(15), end="")
                            print(volume.ljust(10), end="")
                            print(f"{exchange_data['freshness']}{exchange_data['time']}".ljust(10), end="")
                else:
                    if has_orderbook:
                        print("N/A".ljust(50), end="")
                    else:
                        print("N/A".ljust(35), end="")
                
                # Hyperliquid 数据
                if 'hyperliquid' in data['exchanges']:
                    exchange_data = data['exchanges']['hyperliquid']
                    
                    if has_orderbook and exchange_data['data_type'] == 'orderbook':
                        bid_str = f"${exchange_data['bid_price']:.4f}({exchange_data['bid_volume']:.1f})"
                        ask_str = f"${exchange_data['ask_price']:.4f}({exchange_data['ask_volume']:.1f})"
                        spread_str = f"{exchange_data['spread_pct']:.2f}%"
                        
                        print(bid_str.ljust(18), end="")
                        print(ask_str.ljust(18), end="")
                        print(spread_str.ljust(8), end="")
                        print(f"{exchange_data['freshness']}{exchange_data['time']}".ljust(6), end="")
                    else:
                        if has_orderbook:
                            price_str = f"${exchange_data['price']:.4f}"
                            print(price_str.ljust(18), end="")
                            print("N/A".ljust(18), end="")
                            print("N/A".ljust(8), end="")
                            print(f"{exchange_data['freshness']}{exchange_data['time']}".ljust(6), end="")
                        else:
                            price = f"${exchange_data['price']:.4f}"
                            volume = self.format_volume(exchange_data['volume'])
                            print(price.ljust(15), end="")
                            print(volume.ljust(10), end="")
                            print(f"{exchange_data['freshness']}{exchange_data['time']}".ljust(10), end="")
                else:
                    if has_orderbook:
                        print("N/A".ljust(50), end="")
                    else:
                        print("N/A".ljust(35), end="")
                
                # 🔥 价差分析 - 显示双价差
                max_spread = data['max_spread']
                
                # 获取 REST API 价差
                rest_api_spread_str = "n/a"
                if symbol in self.backpack_rest_data and data['rest_api_spreads']:
                    # 找到最大的 REST API 价差
                    max_rest_spread = 0
                    for pair_key, rest_spread_data in data['rest_api_spreads'].items():
                        if abs(rest_spread_data['spread_pct']) > abs(max_rest_spread):
                            max_rest_spread = rest_spread_data['spread_pct']
                    rest_api_spread_str = f"{max_rest_spread:+.2f}%"
                
                if data['arbitrage_opportunities']:
                    # 显示最佳套利机会
                    best_arb = max(data['arbitrage_opportunities'], key=lambda x: x['profit_pct'])
                    if has_orderbook:
                        print(f"{max_spread:+.2f}%/{rest_api_spread_str}".ljust(15), end="")
                        print(f"🔥{best_arb['direction']} +{best_arb['profit_pct']:.2f}%".ljust(25))
                    else:
                        print(f"{max_spread:+.2f}%".ljust(10), end="")
                        print(f"{rest_api_spread_str}".ljust(10), end="")
                        print("套利".ljust(12), end="")
                        print("🔥".ljust(8))
                else:
                    # 显示传统价差
                    if has_orderbook:
                        if abs(max_spread) > 0.5:
                            status_icon = "📊"
                        elif abs(max_spread) > 0.1:
                            status_icon = "⚡"
                        else:
                            status_icon = "💚"
                        
                        print(f"{max_spread:+.2f}%/{rest_api_spread_str}".ljust(15), end="")
                        print(f"{status_icon}".ljust(25))
                    else:
                        # ticker模式的价差显示
                        if abs(max_spread) > 0.5:
                            status_icon = "🔥"
                        elif abs(max_spread) > 0.1:
                            status_icon = "⚡"
                        elif abs(max_spread) > 0.01:
                            status_icon = "📊"
                        else:
                            status_icon = "💚"
                        
                        # 显示百分比和交易所对比信息
                        exchange_pair = self.format_exchange_pair(data['max_spread_pair'])
                        print(f"{max_spread:+.2f}%".ljust(10), end="")
                        print(f"{rest_api_spread_str}".ljust(10), end="")
                        print(f"{exchange_pair}".ljust(12), end="")
                        print(f"{status_icon}".ljust(8))
            
            print("-" * (220 if has_orderbook else 180))
            
            # 显示说明
            if has_orderbook:
                print("📖 说明:")
                print("  • 买1价/量: 最高买入价格和数量")
                print("  • 卖1价/量: 最低卖出价格和数量")
                print("  • BP-REST API: Backpack REST API 获取的买1/卖1/中间价")
                print("  • 实时%/API%: 实时价差百分比/REST API价差百分比")
                print("  • 套利机会: 🔥表示存在正向套利机会")
                print("  • 时效性: 🟢=实时(<2s) 🟡=延时(2-5s) 🔴=过时(>5s)")
            else:
                print("📖 说明:")
                print("  • BP-REST API: Backpack REST API 获取的买1价格/卖1价格/中间价格")
                print("  • 时效性: 🟢=实时(<2s) 🟡=延时(2-5s) 🔴=过时(>5s)")
                print("  • 价差状态: 🔥=大价差(>0.5%) ⚡=中等(>0.1%) 📊=小价差(>0.01%) 💚=极小(≤0.01%)")
                print("  • 交易所对比: bp=Backpack, edgex=EdgeX, hype=Hyperliquid")
                print("  • 🔥 REST API: 在套利状态下自动轮询Backpack订单簿数据")
            
            print("按Ctrl+C退出")
            
        except Exception as e:
            print(f"❌ 显示数据失败: {e}")
    
    async def start_display_loop(self):
        """启动显示循环"""
        while True:
            try:
                self.display_data()
                await asyncio.sleep(self.refresh_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"❌ 显示循环错误: {e}")
                await asyncio.sleep(self.refresh_interval)
    
    async def cleanup(self):
        """清理资源"""
        try:
            # 取消所有轮询任务
            for task in self.active_polling_tasks.values():
                task.cancel()
            
            # 等待任务完成
            if self.active_polling_tasks:
                await asyncio.gather(*self.active_polling_tasks.values(), return_exceptions=True)
            
            # 断开 Backpack 适配器
            if self.backpack_adapter:
                await self.backpack_adapter.disconnect()
            
            self.add_debug_message("🧹 资源清理完成")
            
        except Exception as e:
            print(f"❌ 清理资源失败: {e}")
    
    async def run(self):
        """运行监控客户端"""
        try:
            print(f"🔗 正在连接到 {self.server_url}...")
            
            # 连接到服务器
            await self.sio.connect(self.server_url)
            
            # 启动显示循环
            display_task = asyncio.create_task(self.start_display_loop())
            
            # 等待用户中断
            try:
                await display_task
            except KeyboardInterrupt:
                print("\n👋 用户中断，正在退出...")
            
        except Exception as e:
            print(f"❌ 连接失败: {e}")
        finally:
            await self.cleanup()
            if self.sio.connected:
                await self.sio.disconnect()
            print("✅ 已断开连接")


async def main():
    """主函数"""
    print("🎉" * 20)
    print("双交易所永续合约监控系统")
    print("终端客户端 - 新架构版本 + REST API增强")
    print("🎉" * 20)
    
    monitor = TerminalMonitor()
    
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