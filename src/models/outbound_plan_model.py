from dataclasses import dataclass, field

# 表示一次夹爪动作中，实际放到流水线上的某一个货物
@dataclass
class PlacedItem:
    sequence: int               # 全局出库顺序，在整个任务中真正有出货的夹爪的顺序
    # 每个货物都有自己的sequence，每个货物还必须有自己的place_batch_no
    place_batch_no: int         # 表示这个货物是在整个计划的第几个批次被放到流水线上的
    goods_sku: str              # 货物sku
    package_id: str             # 包裹id
    target_line: str            # 目标流水线


# 表示某一批次里，某一个夹爪要做什么
@dataclass
class GripperAction:
    action_type: str            # 动作类型：pick取货,idle空闲
    station_id: int             # 工作站id
    station_code: str           # 工作站编码
    local_gripper_id: int       # 夹爪编码（单个工作站内）
    global_gripper_id: int      # 夹爪全局编码
    gripper_side: str           # 夹爪方向
    layer: int | None           # 取货层号，如果是空置动作就填None（传给plc是这个参数）
    location_code: str | None   # 取货库位，如果是空置动作就填None（用于日志查看）
    picked_count: int           # 夹爪本次从库位上夹起的数量（一定是库位上的全部货物）
    place_count: int            # 本次夹取后，该夹爪要连续参与几个出库批次的放置，0 <= place_count <= picked_count
    size: int | None            # 货物尺寸参数，用于传给 PLC 的 size
    batch_no: int               # 这个动作属于第几批
    target_line: str | None     # 目标流水线，如果是空置动作就填None 
    picked_goods: list[str] = field(default_factory=list)       # 夹爪本次从库位夹起的所有 SKU
    placed_items: list[PlacedItem] = field(default_factory=list)    # 本次真正放到流水线上的货物列表
    send_to_plc: bool = False   # 是否需要在该批次真正下发 PLC 命令；同一次夹取的后续连续批次只做计划跟踪


# 表示一批次里某一台工作站的两个夹爪安排
@dataclass
class StationBatchPlan:
    station_id: int             # 工作站id
    station_code: str           # 工作站编码
    target_line: str | None     # 一台工作站本批次的目标线，如果本批次两个夹爪都空置，可以是None，
    # 如果有取货动作，那么本批次内所有取货动作的目标线必须一致
    actions: list[GripperAction] = field(default_factory=list)      # 保存这台工作站两个夹爪的动作


# 表示三台工作站六个夹爪的一批出库安排
@dataclass
class OutboundBatch:
    batch_no: int               # 批次编号，从1开始
    target_line: str | None     # 这一批货主要是去往哪一条流水线
    exclusive: bool             # 这一批次是否是独占动作
    exclusive_package_id: str | None    # 如果 exclusive=True，这里填被独占处理的包裹 ID，如果不是独占批次，填None
    package_ids: list[str]      # 这一批包含哪些包裹
    station_plans: list[StationBatchPlan] = field(default_factory=list) # 保存三台工作站在这一批里的动作
    sequence_start: int | None = None   # 这一批真实落线货物的序号范围，假设有四个货物落线，则start: 7
    sequence_end: int | None = None     # 这一批真实落线货物的序号范围，假设有四个货物落线，则end：10
    outbound_count: int = 0      # 本批次真实放到出库流水线上的鞋盒数量，PLC 用它控制速度并校验出库数量


# 用于记录一个包裹在计划中的连续出库段
@dataclass
class PackageSegment:
    package_id: str             # 包裹id
    target_line: str            # 目标流水线
    total_goods: int            # 货物数量
    batch_start: int            # 批次起始编号
    batch_end: int              # 批次结束编号
    sequence_start: int         # 序号起始编号
    sequence_end: int           # 序号结束编号
    station_codes: list[str]    # 工作站编码（包裹出库涉及哪些工作站）
    exclusive: bool             # 是否独占


# 最终返回给任务执行模块的模型
@dataclass
class OutboundPlan:
    task_id: str                # 任务编号
    task_type: str              # 任务类型
    total_packages: int         # 全部出库包裹数量
    total_goods: int            # 全部出库货物数量
    batches: list[OutboundBatch] = field(default_factory=list)      # 整个任务批次列表，执行层可以按照batches[0],batcher[1]来执行
    package_segments: list[PackageSegment] = field(default_factory=list)     # 包裹连续段列表
