from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime

@dataclass
class TaskProgressReport:
    """任务进度上报"""
    task_id: str              # 任务ID
    status: str               # 任务状态
    completed_goods: int      # 已完成货物数量
    total_goods: int          # 总货物数量
    completed_packages: List[str] = field(default_factory=list)     # 已完成的包裹ID列表
    timestamp: datetime = field(default_factory = datetime.now)     # 上报时间戳


@dataclass
class AlarmReport:
    """告警上报"""
    alarm_id: str       # 告警ID
    level: str          # 告警级别
    device: str         # 设备标识
    alarm_type: str     # 告警类型
    description: str    # 告警描述
    timestamp: datetime = field(default_factory = datetime.now)     # 上报时间戳