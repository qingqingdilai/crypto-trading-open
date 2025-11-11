"""
多交易所价格监控 - 显示管理器
Multi-Exchange Price Monitor - Display Manager
"""

import os
import sys
from typing import Dict, List, Optional, Any
from datetime import datetime
from decimal import Decimal
import asyncio
from collections import defaultdict

try:
    from rich.console import Console
    from rich.table import Table
    from rich.live import Live
    from rich.panel import Panel
    from rich.layout import Layout
    from rich.text import Text
    from rich.columns import Columns
    from rich.align import Align
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

from .models import SpreadData, MarketType, MonitorStats, DisplayThresholds, ConnectionStatus
from .price_calculator import PriceCalculator


class DisplayManager:
    """显示管理器 - 负责界面渲染和实时更新"""
    
    def __init__(self, calculator: PriceCalculator, 
                 thresholds: DisplayThresholds,
                 config: Dict[str, Any]):
        """
        初始化显示管理器
        
        Args:
            calculator: 价差计算器
            thresholds: 显示阈值配置
            config: 显示配置
        """
        self.calculator = calculator
        self.thresholds = thresholds
        self.config = config
        
        # 界面配置
        self.precision = config.get('table', {}).get('precision', 4)
        self.show_timestamp = config.get('table', {}).get('show_timestamp', True)
        self.show_volume = config.get('table', {}).get('show_volume', False)
        self.refresh_interval = config.get('refresh_interval', 1.0)
        
        # 颜色配置
        self.colors = config.get('colors', {
            'normal': 'white',
            'warning': 'yellow',
            'critical': 'red',
            'unavailable': 'dim'
        })
        
        # Rich 控制台
        if RICH_AVAILABLE:
            self.console = Console()
            self.live_display: Optional[Live] = None
        else:
            self.console = None
            self.live_display = None
        
        # 连接状态
        self.connection_status: Dict[str, ConnectionStatus] = {}
        
        # 是否运行中
        self.is_running = False
        
        # 统计信息
        self.start_time = datetime.now()
    
    def add_connection_status(self, exchange: str, status: ConnectionStatus):
        """添加连接状态"""
        self.connection_status[exchange] = status
    
    def update_connection_status(self, exchange: str, connected: bool, error: Optional[str] = None):
        """更新连接状态"""
        if exchange in self.connection_status:
            self.connection_status[exchange].update_status(connected, error)
    
    async def start_display(self):
        """启动实时显示"""
        if not RICH_AVAILABLE:
            await self._start_simple_display()
            return
        
        self.is_running = True
        
        try:
            with Live(
                self._create_layout(),
                console=self.console,
                refresh_per_second=1/self.refresh_interval,
                screen=True
            ) as live:
                self.live_display = live
                
                while self.is_running:
                    # 更新显示内容
                    layout = await self._create_layout()
                    live.update(layout)
                    
                    # 等待刷新间隔
                    await asyncio.sleep(self.refresh_interval)
                    
        except KeyboardInterrupt:
            self.console.print("\n[yellow]接收到停止信号，正在退出...[/yellow]")
        finally:
            self.is_running = False
            self.live_display = None
    
    async def _start_simple_display(self):
        """启动简单终端显示（不依赖Rich）"""
        self.is_running = True
        
        try:
            while self.is_running:
                # 清屏
                os.system('cls' if os.name == 'nt' else 'clear')
                
                # 显示标题
                print("=" * 80)
                print("多交易所价格监控系统 | Multi-Exchange Price Monitor")
                print("=" * 80)
                
                # 显示连接状态
                await self._print_connection_status()
                
                # 显示价格表格
                await self._print_price_table()
                
                # 显示统计信息
                await self._print_stats()
                
                print(f"\n刷新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print("按 Ctrl+C 退出")
                
                # 等待刷新间隔
                await asyncio.sleep(self.refresh_interval)
                
        except KeyboardInterrupt:
            print("\n接收到停止信号，正在退出...")
        finally:
            self.is_running = False
    
    async def _create_layout(self) -> Layout:
        """创建Rich布局"""
        layout = Layout()
        
        # 分割布局
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="footer", size=5)
        )
        
        # 主区域分割
        layout["main"].split_row(
            Layout(name="table", ratio=3),
            Layout(name="sidebar", ratio=1)
        )
        
        # 设置各部分内容
        layout["header"].update(self._create_header())
        layout["table"].update(await self._create_price_table())
        layout["sidebar"].update(await self._create_sidebar())
        layout["footer"].update(await self._create_footer())
        
        return layout
    
    def _create_header(self) -> Panel:
        """创建头部面板"""
        title = Text("多交易所价格监控系统", style="bold blue")
        subtitle = Text("Multi-Exchange Price Monitor", style="dim")
        
        header_content = Align.center(
            Columns([title, subtitle], align="center")
        )
        
        return Panel(
            header_content,
            box=box.ROUNDED,
            style="blue"
        )
    
    async def _create_price_table(self) -> Table:
        """创建价格对比表格"""
        table = Table(
            title="实时价格对比",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan"
        )
        
        # 添加列
        table.add_column("代币", style="bold", width=12)
        table.add_column("类型", width=8)
        table.add_column("Hyperliquid", width=15)
        table.add_column("Binance", width=15)
        table.add_column("OKX", width=15)
        table.add_column("最大价差", width=12)
        table.add_column("价差%", width=10)
        
        if self.show_timestamp:
            table.add_column("更新时间", width=12)
        
        # 获取所有当前价差数据
        all_spreads = await self.calculator.get_all_current_spreads()
        
        # 按符号和市场类型分组
        grouped_data = defaultdict(dict)
        for (symbol, market_type), spread_data in all_spreads.items():
            grouped_data[symbol][market_type] = spread_data
        
        # 添加数据行
        for symbol in sorted(grouped_data.keys()):
            market_data = grouped_data[symbol]
            
            for market_type in [MarketType.SPOT, MarketType.PERPETUAL]:
                if market_type not in market_data:
                    continue
                
                spread_data = market_data[market_type]
                await self._add_table_row(table, spread_data)
        
        return table
    
    async def _add_table_row(self, table: Table, spread_data: SpreadData):
        """添加表格行"""
        symbol = spread_data.symbol
        market_type = spread_data.market_type.value.upper()
        
        # 获取各交易所价格
        hyperliquid_price = self._format_price_cell(spread_data.prices.get('hyperliquid'))
        binance_price = self._format_price_cell(spread_data.prices.get('binance'))
        okx_price = self._format_price_cell(spread_data.prices.get('okx'))
        
        # 计算价差显示
        if spread_data.spread_amount and spread_data.spread_percentage:
            max_spread = self.calculator.format_price(spread_data.spread_amount, self.precision)
            spread_percentage = self.calculator.format_percentage(spread_data.spread_percentage)
            
            # 根据价差百分比设置颜色
            color_level = self.thresholds.get_color_level(spread_data.spread_percentage)
            color = self.colors.get(color_level, 'white')
            
            spread_cell = f"[{color}]{spread_percentage}[/{color}]"
            max_spread_cell = f"[{color}]{max_spread}[/{color}]"
        else:
            max_spread_cell = "[dim]N/A[/dim]"
            spread_cell = "[dim]N/A[/dim]"
        
        # 准备行数据
        row_data = [
            f"[bold]{symbol}[/bold]",
            market_type,
            hyperliquid_price,
            binance_price,
            okx_price,
            max_spread_cell,
            spread_cell
        ]
        
        # 添加时间戳列
        if self.show_timestamp:
            timestamp = spread_data.timestamp.strftime('%H:%M:%S') if spread_data.timestamp else "N/A"
            row_data.append(f"[dim]{timestamp}[/dim]")
        
        table.add_row(*row_data)
    
    def _format_price_cell(self, price_data) -> str:
        """格式化价格单元格"""
        if not price_data or not price_data.is_available or price_data.price is None:
            return "[dim]N/A[/dim]"
        
        formatted_price = self.calculator.format_price(price_data.price, self.precision)
        
        # 根据数据新鲜度设置颜色
        if price_data.timestamp:
            age = (datetime.now() - price_data.timestamp).total_seconds()
            if age > 30:  # 超过30秒的数据显示为灰色
                return f"[dim]{formatted_price}[/dim]"
        
        return f"[green]{formatted_price}[/green]"
    
    async def _create_sidebar(self) -> Panel:
        """创建侧边栏"""
        content = []
        
        # 连接状态
        content.append(Text("连接状态", style="bold underline"))
        for exchange, status in self.connection_status.items():
            if status.is_connected:
                content.append(Text(f"✅ {exchange.upper()}", style="green"))
            else:
                error_text = f" ({status.last_error})" if status.last_error else ""
                content.append(Text(f"❌ {exchange.upper()}{error_text}", style="red"))
        
        content.append(Text(""))  # 空行
        
        # 套利机会
        content.append(Text("套利机会", style="bold underline"))
        opportunities = await self.calculator.get_arbitrage_opportunities(Decimal('0.1'))
        
        if opportunities:
            for opp in opportunities[:5]:  # 只显示前5个
                symbol = opp['symbol']
                spread_pct = self.calculator.format_percentage(opp['spread_percentage'])
                buy_exchange = opp['buy_exchange'].upper()
                sell_exchange = opp['sell_exchange'].upper()
                
                content.append(Text(f"{symbol}: {spread_pct}", style="yellow"))
                content.append(Text(f"  买入: {buy_exchange}", style="dim"))
                content.append(Text(f"  卖出: {sell_exchange}", style="dim"))
        else:
            content.append(Text("暂无套利机会", style="dim"))
        
        return Panel(
            Align.left("\n".join(str(line) for line in content)),
            title="监控信息",
            box=box.ROUNDED
        )
    
    async def _create_footer(self) -> Panel:
        """创建底部面板"""
        stats = self.calculator.get_stats()
        
        # 统计信息
        runtime = stats.get_runtime()
        success_rate = stats.get_success_rate()
        total_updates = stats.total_updates
        
        stats_text = (
            f"运行时间: {runtime} | "
            f"更新次数: {total_updates} | "
            f"成功率: {success_rate:.1f}% | "
            f"最大价差: {self.calculator.format_percentage(stats.max_spread_percentage)} "
            f"({stats.max_spread_symbol})" if stats.max_spread_symbol else "N/A"
        )
        
        # 操作提示
        help_text = "按 Ctrl+C 退出 | 实时更新中..."
        
        footer_content = f"{stats_text}\n{help_text}"
        
        return Panel(
            Align.center(footer_content),
            box=box.ROUNDED,
            style="dim"
        )
    
    async def _print_connection_status(self):
        """打印连接状态（简单模式）"""
        print("\n连接状态:")
        print("-" * 40)
        for exchange, status in self.connection_status.items():
            status_symbol = "✅" if status.is_connected else "❌"
            error_text = f" ({status.last_error})" if status.last_error else ""
            print(f"{status_symbol} {exchange.upper():<12} {error_text}")
    
    async def _print_price_table(self):
        """打印价格表格（简单模式）"""
        print("\n实时价格对比:")
        print("-" * 120)
        
        # 表头
        header = f"{'代币':<12} {'类型':<8} {'Hyperliquid':<15} {'Binance':<15} {'OKX':<15} {'最大价差':<12} {'价差%':<10}"
        if self.show_timestamp:
            header += f" {'更新时间':<12}"
        print(header)
        print("=" * len(header))
        
        # 获取数据并打印
        all_spreads = await self.calculator.get_all_current_spreads()
        
        grouped_data = defaultdict(dict)
        for (symbol, market_type), spread_data in all_spreads.items():
            grouped_data[symbol][market_type] = spread_data
        
        for symbol in sorted(grouped_data.keys()):
            market_data = grouped_data[symbol]
            
            for market_type in [MarketType.SPOT, MarketType.PERPETUAL]:
                if market_type not in market_data:
                    continue
                
                spread_data = market_data[market_type]
                await self._print_table_row(spread_data)
    
    async def _print_table_row(self, spread_data: SpreadData):
        """打印表格行（简单模式）"""
        symbol = spread_data.symbol
        market_type = spread_data.market_type.value.upper()
        
        # 获取价格
        def get_price_str(exchange):
            price_data = spread_data.prices.get(exchange)
            if not price_data or not price_data.is_available or price_data.price is None:
                return "N/A"
            return self.calculator.format_price(price_data.price, self.precision)
        
        hyperliquid_price = get_price_str('hyperliquid')
        binance_price = get_price_str('binance')
        okx_price = get_price_str('okx')
        
        # 价差信息
        if spread_data.spread_amount and spread_data.spread_percentage:
            max_spread = self.calculator.format_price(spread_data.spread_amount, self.precision)
            spread_percentage = self.calculator.format_percentage(spread_data.spread_percentage)
        else:
            max_spread = "N/A"
            spread_percentage = "N/A"
        
        # 构建行
        row = f"{symbol:<12} {market_type:<8} {hyperliquid_price:<15} {binance_price:<15} {okx_price:<15} {max_spread:<12} {spread_percentage:<10}"
        
        if self.show_timestamp:
            timestamp = spread_data.timestamp.strftime('%H:%M:%S') if spread_data.timestamp else "N/A"
            row += f" {timestamp:<12}"
        
        print(row)
    
    async def _print_stats(self):
        """打印统计信息（简单模式）"""
        stats = self.calculator.get_stats()
        
        print(f"\n统计信息:")
        print("-" * 40)
        print(f"运行时间: {stats.get_runtime()}")
        print(f"更新次数: {stats.total_updates}")
        print(f"成功率: {stats.get_success_rate():.1f}%")
        if stats.max_spread_percentage:
            print(f"最大价差: {self.calculator.format_percentage(stats.max_spread_percentage)} ({stats.max_spread_symbol})")
    
    def stop_display(self):
        """停止显示"""
        self.is_running = False
    
    async def take_screenshot(self, file_path: str):
        """截图保存（Rich模式）"""
        if not RICH_AVAILABLE or not self.live_display:
            return
        
        # 这里可以实现截图功能
        # Rich 库支持导出为 SVG 或其他格式
        pass
    
    def __str__(self) -> str:
        """字符串表示"""
        return (f"DisplayManager(Rich={RICH_AVAILABLE}, "
                f"精度={self.precision}, "
                f"刷新间隔={self.refresh_interval}s)")
    
    def __repr__(self) -> str:
        return self.__str__()
