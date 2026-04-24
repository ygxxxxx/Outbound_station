from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Goods:
    """货物信息"""
    goods_id: str  # 货物SKU编码
    count: int     # 数量


@dataclass
class Package:
    """出库包裹信息"""
    package_id: str                      # 包裹ID
    face_sheet: Optional[str] = None     # 面单信息
    logistics: Optional[str] = None       # 物流类型
    manual_process_type: Optional[str] = None  # 人工处理类型（无/赠品/软包）
    packaging_line: Optional[str] = None  # 目标包装线（高速线1/高速线2/多盒包装线/人工处理线/合单缓存线）
    goods: List[Goods] = field(default_factory = list)  # 货物列表


@dataclass
class Container:
    """出库工作站收纳柜货位上的货物数据"""
    location_id: str  # 货位ID
    goods_id: str     # 货物SKU编码
    count: int        # 数量


@dataclass
class OutboundTask:
    """出库任务接口根数据模型"""
    task_id: str                      # 任务流水号
    packages: List[Package] = field(default_factory = list)   # 出库包裹数据列表
    containers: List[Container] = field(default_factory = list)  # 出库工作站收纳柜货位数据