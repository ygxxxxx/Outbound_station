from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class StationAction:
    """工作站单次动作"""
    action_id: str           # 动作ID
    container_location: str  # 从哪个收纳位取货
    goods_id: str            # 货物ID
    package_id: str          # 包裹ID
    target_line: str         # 目标包装线
    is_multi_box: bool       # 是否属于多盒包裹
    exclusive: bool          # 是否需要独占模式（R4规则）
    sequence: int            # 在输送线上的放置顺序


@dataclass
class StationPlan:
    """单台工作站执行计划"""
    station_id: int                     # 工作站编号 1/2/3
    actions: List[StationAction] = field(default_factory = list)  # 该工作站的动作列表


@dataclass
class OutboundPlan:
    """出库执行计划"""
    task_id: str               # 任务ID
    stations: List[StationPlan] = field(default_factory = list)  # 每台工作站的计划
    total_goods: int           # 任务总货物数量
    estimated_time: float      # 预计完成时间（分钟）