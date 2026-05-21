from dataclasses import dataclass, field
from typing import List, Optional

from src.utils.logger import logger

logger = logger.bind(tag = "outbound_task_model")

# goods货物数据object
@dataclass
class Put_Goods:
    storage_location: str # 库位id
    abr_count: int # 库位货物数量
    good_sku: List[str] = field(default_factory = list) # 库位上货物SKU


# 包裹数据object
@dataclass
class Package:
    package_id: str                      # 包裹ID
    box_type: str                        # 纸箱类型
    face_sheet: Optional[str] = None     # 面单信息
    logistics: Optional[str] = None       # 物流类型
    manual_process_type: Optional[str] = None  # 人工处理类型
    packaging_line: Optional[str] = None  # 打包线
    count: int = 0                        # 包裹中货物数量
    goods: List[str] = field(default_factory = list)  # 货物信息


# 任务数据模型
@dataclass
class OutboundTask:
    task_id: str                      # 任务id
    task_types: str                   # 任务类型
    timestamp: str                    # 时间戳
    station_id: str                   # 工作站编号
    packages_count: int               # 包裹数量
    
    packages: List[Package] = field(default_factory = list)   # 包裹信息
    put_goods: List[Put_Goods] = field(default_factory = list) # ABR放货后工作站内的库位信息