"""
多交易所价格监控 - 价差计算器
Multi-Exchange Price Monitor - Price Calculator
"""

from typing import Dict, List, Optional, Tuple
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta
import asyncio
from collections import defaultdict, deque

from .models import PriceData, SpreadData, MarketType, MonitorStats


class PriceCalculator:
    """价差计算器"""
    
    def __init__(self, price_cache_ttl: int = 60, max_history_records: int = 1000):
        """
        初始化价差计算器
        
        Args:
            price_cache_ttl: 价格缓存时间（秒）
            max_history_records: 最大历史记录数
        """
        self.price_cache_ttl = price_cache_ttl
        self.max_history_records = max_history_records
        
        # 当前价格数据存储
        # 格式: {(symbol, market_type): {exchange: PriceData}}
        self.current_prices: Dict[Tuple[str, MarketType], Dict[str, PriceData]] = defaultdict(dict)
        
        # 价差历史记录
        # 格式: {(symbol, market_type): deque[SpreadData]}
        self.spread_history: Dict[Tuple[str, MarketType], deque] = defaultdict(
            lambda: deque(maxlen=self.max_history_records)
        )
        
        # 当前价差数据
        # 格式: {(symbol, market_type): SpreadData}
        self.current_spreads: Dict[Tuple[str, MarketType], SpreadData] = {}
        
        # 统计数据
        self.stats = MonitorStats()
        
        # 锁机制，防止并发访问冲突
        self._lock = asyncio.Lock()
    
    async def update_price(self, price_data: PriceData) -> Optional[SpreadData]:
        """
        更新价格数据并计算价差
        
        Args:
            price_data: 新的价格数据
            
        Returns:
            SpreadData: 更新后的价差数据，如果无变化则返回None
        """
        async with self._lock:
            try:
                key = (price_data.symbol, price_data.market_type)
                
                # 更新当前价格
                self.current_prices[key][price_data.exchange] = price_data
                
                # 清理过期数据
                await self._cleanup_expired_data(key)
                
                # 计算价差
                spread_data = await self._calculate_spread(key)
                
                if spread_data:
                    # 更新当前价差
                    self.current_spreads[key] = spread_data
                    
                    # 添加到历史记录
                    self.spread_history[key].append(spread_data)
                    
                    # 更新统计数据
                    self._update_stats(spread_data, success=True)
                    
                    return spread_data
                
                self.stats.update_stats(success=True)
                return None
                
            except Exception as e:
                self.stats.update_stats(success=False)
                raise e
    
    async def _cleanup_expired_data(self, key: Tuple[str, MarketType]):
        """清理过期的价格数据"""
        current_time = datetime.now()
        ttl_threshold = timedelta(seconds=self.price_cache_ttl)
        
        # 找出过期的交易所数据
        expired_exchanges = []
        for exchange, price_data in self.current_prices[key].items():
            if price_data.timestamp and (current_time - price_data.timestamp) > ttl_threshold:
                expired_exchanges.append(exchange)
        
        # 删除过期数据
        for exchange in expired_exchanges:
            del self.current_prices[key][exchange]
    
    async def _calculate_spread(self, key: Tuple[str, MarketType]) -> Optional[SpreadData]:
        """
        计算指定符号和市场类型的价差
        
        Args:
            key: (symbol, market_type) 键
            
        Returns:
            SpreadData: 计算的价差数据
        """
        symbol, market_type = key
        
        if key not in self.current_prices or not self.current_prices[key]:
            return None
        
        # 创建价差数据对象
        spread_data = SpreadData(
            symbol=symbol,
            market_type=market_type,
            prices=self.current_prices[key].copy()
        )
        
        # 计算价差
        spread_data.calculate_spread()
        
        return spread_data
    
    def _update_stats(self, spread_data: SpreadData, success: bool = True):
        """更新统计数据"""
        self.stats.update_stats(success)
        
        # 更新最大价差记录
        if (spread_data.spread_percentage is not None and 
            spread_data.spread_percentage > 0):
            
            symbol_key = f"{spread_data.symbol}({spread_data.market_type.value})"
            self.stats.update_max_spread(spread_data.spread_percentage, symbol_key)
    
    async def get_current_spread(self, symbol: str, market_type: MarketType) -> Optional[SpreadData]:
        """
        获取当前价差数据
        
        Args:
            symbol: 交易符号
            market_type: 市场类型
            
        Returns:
            SpreadData: 当前价差数据
        """
        async with self._lock:
            key = (symbol, market_type)
            return self.current_spreads.get(key)
    
    async def get_all_current_spreads(self) -> Dict[Tuple[str, MarketType], SpreadData]:
        """获取所有当前价差数据"""
        async with self._lock:
            return self.current_spreads.copy()
    
    async def get_spread_history(self, symbol: str, market_type: MarketType, 
                               limit: Optional[int] = None) -> List[SpreadData]:
        """
        获取价差历史记录
        
        Args:
            symbol: 交易符号
            market_type: 市场类型
            limit: 限制返回数量
            
        Returns:
            List[SpreadData]: 价差历史列表（按时间倒序）
        """
        async with self._lock:
            key = (symbol, market_type)
            
            if key not in self.spread_history:
                return []
            
            history = list(self.spread_history[key])
            history.reverse()  # 按时间倒序
            
            if limit:
                history = history[:limit]
            
            return history
    
    async def get_price_trend(self, symbol: str, market_type: MarketType,
                            exchange: str, duration_minutes: int = 5) -> Dict[str, any]:
        """
        获取价格趋势分析
        
        Args:
            symbol: 交易符号
            market_type: 市场类型
            exchange: 交易所
            duration_minutes: 分析时长（分钟）
            
        Returns:
            Dict: 趋势分析结果
        """
        async with self._lock:
            key = (symbol, market_type)
            
            if key not in self.spread_history:
                return {"trend": "unknown", "change": Decimal('0'), "change_percentage": Decimal('0')}
            
            # 获取指定时间段的历史数据
            cutoff_time = datetime.now() - timedelta(minutes=duration_minutes)
            recent_data = [
                spread for spread in self.spread_history[key]
                if spread.timestamp >= cutoff_time and 
                   exchange in spread.prices and 
                   spread.prices[exchange].is_available
            ]
            
            if len(recent_data) < 2:
                return {"trend": "insufficient_data", "change": Decimal('0'), "change_percentage": Decimal('0')}
            
            # 计算价格变化
            first_price = recent_data[0].prices[exchange].price
            last_price = recent_data[-1].prices[exchange].price
            
            if first_price is None or last_price is None:
                return {"trend": "unknown", "change": Decimal('0'), "change_percentage": Decimal('0')}
            
            change = last_price - first_price
            change_percentage = (change / first_price * 100) if first_price > 0 else Decimal('0')
            
            # 判断趋势
            if change > 0:
                trend = "up"
            elif change < 0:
                trend = "down"
            else:
                trend = "stable"
            
            return {
                "trend": trend,
                "change": change,
                "change_percentage": change_percentage,
                "first_price": first_price,
                "last_price": last_price,
                "data_points": len(recent_data)
            }
    
    async def get_arbitrage_opportunities(self, min_spread_percentage: Decimal = Decimal('0.1')) -> List[Dict]:
        """
        获取套利机会
        
        Args:
            min_spread_percentage: 最小价差百分比阈值
            
        Returns:
            List[Dict]: 套利机会列表
        """
        async with self._lock:
            opportunities = []
            
            for key, spread_data in self.current_spreads.items():
                if (spread_data.spread_percentage is not None and 
                    spread_data.spread_percentage >= min_spread_percentage and
                    spread_data.min_exchange and spread_data.max_exchange):
                    
                    opportunities.append({
                        "symbol": spread_data.symbol,
                        "market_type": spread_data.market_type.value,
                        "buy_exchange": spread_data.min_exchange,
                        "sell_exchange": spread_data.max_exchange,
                        "buy_price": spread_data.min_price,
                        "sell_price": spread_data.max_price,
                        "spread_amount": spread_data.spread_amount,
                        "spread_percentage": spread_data.spread_percentage,
                        "timestamp": spread_data.timestamp
                    })
            
            # 按价差百分比降序排列
            opportunities.sort(key=lambda x: x["spread_percentage"], reverse=True)
            
            return opportunities
    
    def format_price(self, price: Optional[Decimal], precision: int = 4) -> str:
        """
        格式化价格显示
        
        Args:
            price: 价格值
            precision: 显示精度
            
        Returns:
            str: 格式化的价格字符串
        """
        if price is None:
            return "N/A"
        
        # 使用指定精度进行四舍五入
        rounded_price = price.quantize(
            Decimal('0.' + '0' * precision), 
            rounding=ROUND_HALF_UP
        )
        
        return f"{rounded_price:,.{precision}f}"
    
    def format_percentage(self, percentage: Optional[Decimal], precision: int = 2) -> str:
        """
        格式化百分比显示
        
        Args:
            percentage: 百分比值
            precision: 显示精度
            
        Returns:
            str: 格式化的百分比字符串
        """
        if percentage is None:
            return "N/A"
        
        rounded_percentage = percentage.quantize(
            Decimal('0.' + '0' * precision),
            rounding=ROUND_HALF_UP
        )
        
        return f"{rounded_percentage:+.{precision}f}%"
    
    async def clear_data(self):
        """清除所有数据"""
        async with self._lock:
            self.current_prices.clear()
            self.current_spreads.clear()
            self.spread_history.clear()
            self.stats = MonitorStats()
    
    async def clear_symbol_data(self, symbol: str, market_type: MarketType):
        """清除指定符号的数据"""
        async with self._lock:
            key = (symbol, market_type)
            
            if key in self.current_prices:
                del self.current_prices[key]
            
            if key in self.current_spreads:
                del self.current_spreads[key]
            
            if key in self.spread_history:
                del self.spread_history[key]
    
    def get_stats(self) -> MonitorStats:
        """获取统计数据"""
        return self.stats
    
    async def export_spread_history_csv(self, file_path: str, 
                                      symbol: Optional[str] = None,
                                      market_type: Optional[MarketType] = None):
        """
        导出价差历史到CSV文件
        
        Args:
            file_path: 导出文件路径
            symbol: 可选的符号过滤
            market_type: 可选的市场类型过滤
        """
        import csv
        
        async with self._lock:
            with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = [
                    'timestamp', 'symbol', 'market_type', 'min_exchange', 'max_exchange',
                    'min_price', 'max_price', 'spread_amount', 'spread_percentage'
                ]
                
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                for key, history in self.spread_history.items():
                    sym, mkt = key
                    
                    # 应用过滤器
                    if symbol and sym != symbol:
                        continue
                    if market_type and mkt != market_type:
                        continue
                    
                    for spread_data in history:
                        writer.writerow({
                            'timestamp': spread_data.timestamp.isoformat(),
                            'symbol': spread_data.symbol,
                            'market_type': spread_data.market_type.value,
                            'min_exchange': spread_data.min_exchange,
                            'max_exchange': spread_data.max_exchange,
                            'min_price': str(spread_data.min_price) if spread_data.min_price else '',
                            'max_price': str(spread_data.max_price) if spread_data.max_price else '',
                            'spread_amount': str(spread_data.spread_amount) if spread_data.spread_amount else '',
                            'spread_percentage': str(spread_data.spread_percentage) if spread_data.spread_percentage else ''
                        })
    
    def __str__(self) -> str:
        """字符串表示"""
        total_symbols = len(self.current_spreads)
        available_prices = sum(
            len([p for p in prices.values() if p.is_available])
            for prices in self.current_prices.values()
        )
        
        return (f"PriceCalculator(监控符号={total_symbols}, "
                f"可用价格={available_prices}, "
                f"成功率={self.stats.get_success_rate():.1f}%)")
    
    def __repr__(self) -> str:
        return self.__str__()
