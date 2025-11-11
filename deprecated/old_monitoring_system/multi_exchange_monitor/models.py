"""
多交易所价格监控 - 数据模型
Multi-Exchange Price Monitor - Data Models
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, List, Any
from datetime import datetime
from decimal import Decimal
from enum import Enum


class MarketType(Enum):
    """市场类型枚举"""
    SPOT = "spot"
    PERPETUAL = "perpetual"
    FUTURES = "futures"
    OPTION = "option"


class ExchangeName(Enum):
    """交易所名称枚举"""
    BINANCE = "binance"
    OKX = "okx"
    HYPERLIQUID = "hyperliquid"


@dataclass
class PriceData:
    """价格数据模型"""
    exchange: str
    symbol: str
    market_type: MarketType
    price: Optional[Decimal] = None
    volume: Optional[Decimal] = None
    timestamp: Optional[datetime] = None
    is_available: bool = False
    error_message: Optional[str] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class SpreadData:
    """价差数据模型"""
    symbol: str
    market_type: MarketType
    prices: Dict[str, PriceData] = field(default_factory=dict)
    min_price: Optional[Decimal] = None
    max_price: Optional[Decimal] = None
    min_exchange: Optional[str] = None
    max_exchange: Optional[str] = None
    spread_amount: Optional[Decimal] = None
    spread_percentage: Optional[Decimal] = None
    timestamp: datetime = field(default_factory=datetime.now)
    
    def calculate_spread(self):
        """计算价差"""
        available_prices = {
            exchange: data.price 
            for exchange, data in self.prices.items() 
            if data.is_available and data.price is not None
        }
        
        if len(available_prices) < 2:
            # 少于2个价格无法计算价差
            self.reset_spread()
            return
            
        self.min_price = min(available_prices.values())
        self.max_price = max(available_prices.values())
        
        # 找到最低和最高价格的交易所
        for exchange, price in available_prices.items():
            if price == self.min_price:
                self.min_exchange = exchange
            if price == self.max_price:
                self.max_exchange = exchange
                
        # 计算价差
        self.spread_amount = self.max_price - self.min_price
        if self.min_price > 0:
            self.spread_percentage = (self.spread_amount / self.min_price) * 100
        else:
            self.spread_percentage = Decimal('0')
            
        self.timestamp = datetime.now()
    
    def reset_spread(self):
        """重置价差数据"""
        self.min_price = None
        self.max_price = None
        self.min_exchange = None
        self.max_exchange = None
        self.spread_amount = None
        self.spread_percentage = None


@dataclass
class MonitorConfig:
    """监控配置模型"""
    # 交易所配置
    exchanges: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # 监控符号
    symbols: Dict[str, List[str]] = field(default_factory=dict)
    
    # 界面配置
    display: Dict[str, Any] = field(default_factory=dict)
    
    # WebSocket配置
    websocket: Dict[str, Any] = field(default_factory=dict)
    
    # 日志配置
    logging: Dict[str, Any] = field(default_factory=dict)
    
    # 数据配置
    data: Dict[str, Any] = field(default_factory=dict)
    
    def get_enabled_exchanges(self) -> List[str]:
        """获取启用的交易所列表"""
        return [
            name for name, config in self.exchanges.items()
            if config.get('enabled', False)
        ]
    
    def get_all_symbols(self) -> Dict[str, List[str]]:
        """获取所有监控符号"""
        all_symbols = {}
        for market_type, symbols in self.symbols.items():
            all_symbols[market_type] = symbols
        return all_symbols
    
    def get_symbol_list_for_market(self, market_type: str) -> List[str]:
        """获取指定市场类型的符号列表"""
        return self.symbols.get(market_type, [])


@dataclass
class ConnectionStatus:
    """连接状态模型"""
    exchange: str
    is_connected: bool = False
    last_update: Optional[datetime] = None
    error_count: int = 0
    last_error: Optional[str] = None
    
    def update_status(self, connected: bool, error: Optional[str] = None):
        """更新连接状态"""
        self.is_connected = connected
        self.last_update = datetime.now()
        
        if error:
            self.error_count += 1
            self.last_error = error
        elif connected:
            # 连接成功时重置错误计数
            self.error_count = 0
            self.last_error = None


@dataclass
class MonitorStats:
    """监控统计数据"""
    start_time: datetime = field(default_factory=datetime.now)
    total_updates: int = 0
    successful_updates: int = 0
    failed_updates: int = 0
    max_spread_percentage: Optional[Decimal] = None
    max_spread_symbol: Optional[str] = None
    connection_status: Dict[str, ConnectionStatus] = field(default_factory=dict)
    
    def update_stats(self, success: bool = True):
        """更新统计数据"""
        self.total_updates += 1
        if success:
            self.successful_updates += 1
        else:
            self.failed_updates += 1
    
    def update_max_spread(self, spread_percentage: Decimal, symbol: str):
        """更新最大价差记录"""
        if (self.max_spread_percentage is None or 
            spread_percentage > self.max_spread_percentage):
            self.max_spread_percentage = spread_percentage
            self.max_spread_symbol = symbol
    
    def get_success_rate(self) -> float:
        """获取成功率"""
        if self.total_updates == 0:
            return 0.0
        return (self.successful_updates / self.total_updates) * 100
    
    def get_runtime(self) -> str:
        """获取运行时间字符串"""
        runtime = datetime.now() - self.start_time
        hours, remainder = divmod(runtime.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"


@dataclass
class DisplayThresholds:
    """显示阈值配置"""
    warning: Decimal = field(default_factory=lambda: Decimal('0.1'))
    critical: Decimal = field(default_factory=lambda: Decimal('0.5'))
    
    def get_color_level(self, spread_percentage: Optional[Decimal]) -> str:
        """根据价差百分比获取颜色级别"""
        if spread_percentage is None:
            return "unavailable"
        
        if spread_percentage >= self.critical:
            return "critical"
        elif spread_percentage >= self.warning:
            return "warning"
        else:
            return "normal"
