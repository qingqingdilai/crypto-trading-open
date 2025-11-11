"""
多交易所价格监控 - 配置加载器
Multi-Exchange Price Monitor - Configuration Loader
"""

import yaml
import os
from typing import Dict, Any, Optional
from pathlib import Path

from .models import MonitorConfig, DisplayThresholds
from decimal import Decimal


class ConfigLoader:
    """配置文件加载器"""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置加载器
        
        Args:
            config_path: 配置文件路径，默认为项目根目录的配置文件
        """
        if config_path is None:
            # 获取项目根目录
            project_root = Path(__file__).parent.parent.parent
            config_path = project_root / "config" / "multi_exchange_monitor.yaml"
        
        self.config_path = Path(config_path)
        self._raw_config: Dict[str, Any] = {}
        self.config: Optional[MonitorConfig] = None
        
    def load_config(self) -> MonitorConfig:
        """
        加载配置文件
        
        Returns:
            MonitorConfig: 加载的配置对象
            
        Raises:
            FileNotFoundError: 配置文件不存在
            yaml.YAMLError: YAML 解析错误
            ValueError: 配置格式错误
        """
        if not self.config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self._raw_config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"配置文件YAML解析错误: {e}")
        
        # 验证配置格式
        self._validate_config()
        
        # 创建配置对象
        self.config = self._create_monitor_config()
        
        return self.config
    
    def _validate_config(self):
        """验证配置文件格式"""
        required_sections = ['exchanges', 'symbols', 'display', 'websocket', 'logging', 'data']
        
        for section in required_sections:
            if section not in self._raw_config:
                raise ValueError(f"配置文件缺少必需的section: {section}")
        
        # 验证交易所配置
        exchanges = self._raw_config.get('exchanges', {})
        if not exchanges:
            raise ValueError("配置文件中必须至少配置一个交易所")
        
        # 验证符号配置
        symbols = self._raw_config.get('symbols', {})
        if not symbols:
            raise ValueError("配置文件中必须至少配置一个监控符号")
        
        # 检查是否有启用的交易所
        enabled_exchanges = [
            name for name, config in exchanges.items()
            if config.get('enabled', False)
        ]
        
        if not enabled_exchanges:
            raise ValueError("配置文件中必须至少启用一个交易所")
    
    def _create_monitor_config(self) -> MonitorConfig:
        """创建监控配置对象"""
        config = MonitorConfig()
        
        # 交易所配置
        config.exchanges = self._raw_config.get('exchanges', {})
        
        # 符号配置
        config.symbols = self._raw_config.get('symbols', {})
        
        # 界面配置
        config.display = self._raw_config.get('display', {})
        
        # WebSocket配置
        config.websocket = self._raw_config.get('websocket', {})
        
        # 日志配置
        config.logging = self._raw_config.get('logging', {})
        
        # 数据配置
        config.data = self._raw_config.get('data', {})
        
        return config
    
    def get_display_thresholds(self) -> DisplayThresholds:
        """获取显示阈值配置"""
        thresholds_config = self._raw_config.get('display', {}).get('price_difference_threshold', {})
        
        return DisplayThresholds(
            warning=Decimal(str(thresholds_config.get('warning', 0.1))),
            critical=Decimal(str(thresholds_config.get('critical', 0.5)))
        )
    
    def get_exchange_config(self, exchange_name: str) -> Dict[str, Any]:
        """
        获取指定交易所的配置
        
        Args:
            exchange_name: 交易所名称
            
        Returns:
            Dict[str, Any]: 交易所配置
        """
        if self.config is None:
            raise ValueError("配置尚未加载，请先调用 load_config()")
        
        return self.config.exchanges.get(exchange_name, {})
    
    def is_exchange_enabled(self, exchange_name: str) -> bool:
        """
        检查交易所是否启用
        
        Args:
            exchange_name: 交易所名称
            
        Returns:
            bool: 是否启用
        """
        exchange_config = self.get_exchange_config(exchange_name)
        return exchange_config.get('enabled', False)
    
    def get_refresh_interval(self) -> float:
        """获取刷新间隔"""
        if self.config is None:
            return 1.0
        return self.config.display.get('refresh_interval', 1.0)
    
    def get_precision(self) -> int:
        """获取价格显示精度"""
        if self.config is None:
            return 4
        return self.config.display.get('table', {}).get('precision', 4)
    
    def get_websocket_config(self) -> Dict[str, Any]:
        """获取WebSocket配置"""
        if self.config is None:
            return {}
        return self.config.websocket
    
    def should_show_timestamp(self) -> bool:
        """是否显示时间戳"""
        if self.config is None:
            return True
        return self.config.display.get('table', {}).get('show_timestamp', True)
    
    def should_show_volume(self) -> bool:
        """是否显示成交量"""
        if self.config is None:
            return False
        return self.config.display.get('table', {}).get('show_volume', False)
    
    def get_color_config(self) -> Dict[str, str]:
        """获取颜色配置"""
        if self.config is None:
            return {
                'normal': 'white',
                'warning': 'yellow', 
                'critical': 'red',
                'unavailable': 'gray'
            }
        return self.config.display.get('colors', {
            'normal': 'white',
            'warning': 'yellow',
            'critical': 'red', 
            'unavailable': 'gray'
        })
    
    def should_save_history(self) -> bool:
        """是否保存价差历史"""
        if self.config is None:
            return False
        return self.config.data.get('save_spread_history', False)
    
    def get_history_file(self) -> str:
        """获取历史文件路径"""
        if self.config is None:
            return "logs/spread_history.csv"
        return self.config.data.get('history_file', 'logs/spread_history.csv')
    
    def reload_config(self) -> MonitorConfig:
        """重新加载配置文件"""
        return self.load_config()
    
    def save_config(self, config_path: Optional[str] = None):
        """
        保存配置到文件
        
        Args:
            config_path: 保存路径，默认为原文件路径
        """
        if config_path is None:
            config_path = self.config_path
        
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(self._raw_config, f, default_flow_style=False, 
                     allow_unicode=True, sort_keys=False)
    
    def update_exchange_credentials(self, exchange_name: str, 
                                  api_key: str, api_secret: str, 
                                  passphrase: Optional[str] = None):
        """
        更新交易所认证信息
        
        Args:
            exchange_name: 交易所名称
            api_key: API密钥
            api_secret: API密码
            passphrase: API密语（OKX需要）
        """
        if exchange_name not in self._raw_config['exchanges']:
            raise ValueError(f"未知的交易所: {exchange_name}")
        
        self._raw_config['exchanges'][exchange_name]['api_key'] = api_key
        self._raw_config['exchanges'][exchange_name]['api_secret'] = api_secret
        
        if passphrase is not None:
            self._raw_config['exchanges'][exchange_name]['passphrase'] = passphrase
    
    def __str__(self) -> str:
        """字符串表示"""
        if self.config is None:
            return f"ConfigLoader(未加载配置)"
        
        enabled_exchanges = self.config.get_enabled_exchanges()
        total_symbols = sum(len(symbols) for symbols in self.config.symbols.values())
        
        return (f"ConfigLoader(配置文件={self.config_path}, "
                f"启用交易所={enabled_exchanges}, "
                f"监控符号数={total_symbols})")
    
    def __repr__(self) -> str:
        return self.__str__()
