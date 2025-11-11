# 旧监控系统（已废弃）

## 📋 概述

此文件夹包含旧的套利监控系统相关代码，已于2025-11-07废弃。

**废弃原因：**
- 架构过于复杂（6层依赖，4000+行代码）
- 历史包袱重（SocketIO残留等）
- 职责不清晰（监控+执行+历史功能混杂）
- 维护困难，扩展性差

**替代方案：** 全新的简洁套利监控系统（`run_arbitrage_monitor.py`）

---

## 📁 文件清单

### 主程序
- `run_monitor.py` - 旧的监控守护进程主程序
- `run_multi_exchange_monitor.py` - 多交易所监控主程序

### 终端工具
- `terminal_monitor.py` - SocketIO客户端终端监控工具
- `direct_terminal_monitor.py` - 直接连接的终端监控工具

### 服务实现
- `enhanced_monitoring_service.py` - 增强监控服务（629行）
  - 包含已删除的SocketIO服务器代码
  - 复杂的数据聚合和推送逻辑

### 配置文件
- `multi_exchange_monitor.yaml` - 多交易所监控配置
- `multi_exchange_monitor_example.yaml` - 示例配置
- `monitoring/` - 监控系统配置目录
  - `monitoring.yaml` - 监控服务配置

---

## 🔍 旧系统架构

```
SystemLauncher（启动器）
    ↓
EnhancedMonitoringService（监控服务，629行）
    ↓
DataAggregator（数据聚合器）
    ↓
ExchangeManager（交易所管理器）
    ↓
SymbolConversionService（符号转换）
    ↓
3个交易所适配器
```

**复杂度指标：**
- 核心代码：~4000行
- 模块层级：6层
- 配置系统：3套
- 依赖注入：复杂的DI容器

---

## ⚠️ 注意事项

1. **不要修改此文件夹中的代码** - 仅供参考
2. **不要运行这些脚本** - 可能与当前系统冲突
3. **查看代码时注意** - 可能包含已知的bug和设计问题

---

## 📚 参考文档

- `docs/fixes/socketio_cleanup.md` - SocketIO清理总结
- `docs/architecture/套利监控系统架构深度分析.md` - 旧系统架构分析

---

## 🗑️ 删除时间表

**保留期限：** 2025-12-07（保留1个月）

如果新系统运行稳定，1个月后可以安全删除此文件夹。

---

**废弃日期：** 2025-11-07  
**废弃原因：** 架构重构，采用简洁的全新实现  
**新系统位置：** `run_arbitrage_monitor.py`

