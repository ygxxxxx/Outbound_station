from __future__ import annotations
from typing import TYPE_CHECKING
from dataclasses import dataclass, field
from collections import Counter

if TYPE_CHECKING:
    from src.business.task_manager import QueueTask
    
from src.utils.logger import logger
from src.models.containers import CabinetStore, SlotInfo
from src.models.outbound_plan_model import OutboundPlan, OutboundBatch, PackageSegment, StationBatchPlan, GripperAction, PlacedItem
from src.models.outbound_task_model import Package


logger = logger.bind(tag = "strategy")

MAX_GRIPPER_COUNT = 4
FRONT_POSITIONS = (1, 2)
BACK_POSITIONS = (3, 4)
BACK_TO_FRONT_POSITION = {3: 1, 4: 2}


# 策略算法内部用的库位级取货计划
@dataclass
class SlotPick:
    package_id: str             # 这个库位服务于哪个包裹
    target_line: str            # 这个包裹的流水线
    location_code: str          # 库位的编号
    station_code: str           # 工作站编号
    station_id: int             # 工作站id
    gripper_id: int             # 工作站内夹爪id
    global_gripper_id: int      # 全局夹爪id
    gripper_side: str           # 夹爪方向
    layer: int                  # 库位层数
    picked_goods: list[str]     # 夹爪从库位上实际夹起来的所有 SKU
    planned_goods: list[str]    # 这个包裹真正需要放到流水线上的 SKU


# 定义一个包裹在策略计算阶段的中间信息
@dataclass
class PackagePlanInfo:
    package: Package            # 包裹原始对象
    package_id: str             # 包裹ID
    target_line: str            # 目标流水线
    total_goods: int            # 包裹需要出的货物数量
    slot_picks: list[SlotPick]  # 包裹需要从哪些库位拿货
    station_codes: list[str]    # 涉及的工作站
    is_cross_station: bool      # 是否跨越工作站
    is_multi_slot: bool         # 是否涉及多个库位
    warnings: list[str] = field(default_factory=list)   # 保存这个包裹计算过程中的警告


# 根据 QueueTask 和当前库位库存生成出库计划
def strategy(queuetask: QueueTask, cabinet_store: CabinetStore) -> OutboundPlan:
    task = queuetask.task
    warnings: list[str] = []

    package_infos = build_package_infos(task.packages, cabinet_store, warnings)
    package_infos = sort_package_infos(package_infos)
    batches = build_batches(package_infos)
    package_segments = build_package_segments(package_infos, batches)

    plan = OutboundPlan(
        task_id=task.task_id,
        task_type=task.task_types,
        total_packages=len(task.packages),
        total_goods=sum(len(package.goods) for package in task.packages),
        batches=batches,
        package_segments=package_segments,
        warnings=warnings,
    )

    validate_plan(plan, cabinet_store)
    return plan


# 把包裹需求转换成PackagePlanInfo
def build_package_infos(packages: list[Package], cabinet_store: CabinetStore, warnings: list[str]) -> list[PackagePlanInfo]:

    reserved_depth: dict[str, int] = {}
    package_infos: list[PackagePlanInfo] = []
    
    for package in packages:
        package_warnings: list[str] = []
        slot_picks = choose_slots_for_package(
            package = package,
            cabinet_store = cabinet_store,
            reserved_depth = reserved_depth,
            warnings = package_warnings,
        )
        station_codes = sorted({slot_pick.station_code for slot_pick in slot_picks})
        target_line = normalize_line(package.packaging_line, package.manual_process_type)

        info = PackagePlanInfo(
            package = package,
            package_id = package.package_id,
            target_line = target_line,
            total_goods = len(package.goods),
            slot_picks = slot_picks,
            station_codes = station_codes,
            is_cross_station = len(station_codes) > 1,
            is_multi_slot = len(slot_picks) > 1,
            warnings = package_warnings,
        )
        warnings.extend(package_warnings)
        package_infos.append(info)

    return package_infos

# 给包裹选择库位
def choose_slots_for_package(package: Package,
    cabinet_store: CabinetStore,
    reserved_depth: dict[str, int],
    warnings: list[str],
) -> list[SlotPick]:
    
    need = Counter(package.goods)
    selected: list[SlotPick] = []
    slots = sorted(
        cabinet_store.get_all_slots(),
        key = lambda slot: location_sort_key(slot.location_code),
    )

    for slot in slots:
        if not need:
            break
        if slot.is_empty:
            continue
        if slot.qty > MAX_GRIPPER_COUNT:
            warnings.append(f"库位 {slot.location_code} 货物数量超过夹爪上限，已跳过")
            continue
        # 如果库位是夹爪取不到的，也就是在（3，4）位置上，跳过
        if not is_reachable_slot(slot.location_code):
            continue
        
        # 从这个库位中挑出所需货物sku列表
        planned_goods = goods_needed_from_slot(
            location_code = slot.location_code,
            slot_goods = slot.goods,
            need = need,
            reserved_depth = reserved_depth,
        )

        if not planned_goods:
            continue

        slot_pick = build_slot_pick(package, slot, planned_goods)
        selected.append(slot_pick)

        reserved_depth[slot.location_code] = (
            reserved_depth.get(slot.location_code, 0) + len(planned_goods)
        )

        for sku in planned_goods:
            need[sku] -= 1
            if need[sku] <= 0:
                del need[sku]

    if need:
        blocked_back_locations = find_blocked_back_locations_for_need(need, cabinet_store, reserved_depth)
        if blocked_back_locations:
            raise ValueError(
                f"包裹 {package.package_id} 所需货物当前在后排库位 {blocked_back_locations}，"
                f"必须先出完同层 1、2 位货物，后排货物移动到前排后才能继续出库"
            )
        raise ValueError(f"包裹 {package.package_id} 库存不足: {dict(need)}")

    return selected

def sort_package_infos(package_infos: list[PackagePlanInfo]) -> list[PackagePlanInfo]:
    return sorted(package_infos, key = package_sort_key)

def build_batches(sorted_infos):
    pass

def build_package_segments(batchers):
    pass

def count_placed_items(batchers):
    pass

def validate_plan(plan):
    pass

# 创建空批次
def empty_batch(batch_no: int, target_line: str | None, reason: str) -> OutboundBatch:
    station_plans = []
    for station_code in ("A", "B", "C"):
        station_id = station_id_from_code(station_code)
        station_plans.append(
            StationBatchPlan(
                station_id=station_id,
                station_code=station_code,
                target_line=None,
                actions=[],
            )
        )

    return OutboundBatch(
        batch_no=batch_no,
        target_line=target_line,
        exclusive=False,
        exclusive_package_id=None,
        package_ids=[],
        reason=reason,
        station_plans=station_plans,
    )

# 夹爪命令
def create_gripper_action(
    slot_pick: SlotPick,
    current_slot_goods: list[str],
    batch_no: int,
    start_sequence: int,
) -> GripperAction:
    place_goods = current_slot_goods[: len(slot_pick.planned_goods)]
    if place_goods != slot_pick.planned_goods:
        raise ValueError("planned_goods 必须等于当前库位底部连续可放置货物")

    placed_items = []
    for index, sku in enumerate(place_goods):
        placed_items.append(
            PlacedItem(
                sequence = start_sequence + index,
                place_batch_no = batch_no + index,
                goods_sku = sku,
                package_id = slot_pick.package_id,
                target_line = slot_pick.target_line,
            )
        )

    return GripperAction(
        action_type="pick",
        station_id=slot_pick.station_id,
        station_code=slot_pick.station_code,
        gripper_id=slot_pick.gripper_id,
        global_gripper_id=slot_pick.global_gripper_id,
        gripper_side=slot_pick.gripper_side,
        layer=slot_pick.layer,
        location_code=slot_pick.location_code,
        picked_count=len(current_slot_goods),
        place_count=len(place_goods),
        size=1,
        batch_no=batch_no,
        picked_goods=list(current_slot_goods),
        placed_items=placed_items,
        target_line=slot_pick.target_line,
        reason="整库位夹取，按 place_count 连续批次放置",
    )

# 构建SlotPick
def build_slot_pick(package: Package, slot: SlotInfo, planned_goods: list[str]) -> SlotPick:
    station_code, layer, position = CabinetStore.parse_location(slot.location_code)
    station_id = station_id_from_code(station_code)
    gripper_id = gripper_id_from_position(position)

    return SlotPick(
        package_id = package.package_id,
        target_line = normalize_line(package.packaging_line, package.manual_process_type),
        location_code = slot.location_code,
        station_code = station_code,
        station_id = station_id,
        gripper_id = gripper_id,
        global_gripper_id = global_gripper_id(station_id, gripper_id),
        gripper_side = gripper_side(gripper_id),
        layer = layer,
        picked_goods = list(slot.goods),
        planned_goods = list(planned_goods),
    )

# 在当前库位，计算当前包裹还能使用哪些货物
def goods_needed_from_slot(
    location_code: str,
    slot_goods: list[str], # 货物sku列表
    need: Counter[str],
    reserved_depth: dict[str, int],
) -> list[str]:
    
    start_index = reserved_depth.get(location_code, 0)
    if start_index > len(slot_goods):
        raise ValueError(f"库位 {location_code} 预占深度超过库存数量")
    available_stack = slot_goods[start_index:]
    local_need = need.copy()
    planned_goods: list[str] = []

    for sku in available_stack:
        if local_need.get(sku, 0) <= 0:
            break

        planned_goods.append(sku)
        local_need[sku] -= 1
        if local_need[sku] <= 0:
            del local_need[sku]

    return planned_goods

# 把工作站编号转成数字
def station_id_from_code(station_code: str) -> int:
    if station_code not in ("A", "B", "C"):
        raise ValueError(f"未知工作站编号: {station_code}")
    return ord(station_code) - ord("A") + 1

# 根据库位位置推导工作站内部夹爪编号
def gripper_id_from_position(position: int) -> int:
    if position == 1:
        return 1
    if position == 2:
        return 2
    raise ValueError(f"位置 {position} 不可由夹爪直接抓取")

# 获得每一位库位编号
def location_sort_key(location_code: str) -> tuple[str, int, int]:
    station_code, layer, position = CabinetStore.parse_location(location_code)
    return station_code, layer, position

# 判断货物是不是在（1，2）库位上
def is_reachable_slot(location_code: str) -> bool:
    _, _, position = CabinetStore.parse_location(location_code)
    return position in FRONT_POSITIONS

# 判断货物是不是在后排（3，4）库位上
def is_back_slot(location_code: str) -> bool:
    _, _, position = CabinetStore.parse_location(location_code)
    return position in BACK_POSITIONS

# 判断同一工作站同一层的前排 1、2 位是否还有未计划出完的货物
def layer_front_has_remaining_goods(
    cabinet_store: CabinetStore,
    station_code: str,
    layer: int,
    reserved_depth: dict[str, int],
) -> bool:
    for position in FRONT_POSITIONS:
        location_code = f"{station_code}{layer}{position}"
        slot = cabinet_store.get_slot(location_code)
        if slot is None:
            continue
        planned_count = reserved_depth.get(location_code, 0)
        if planned_count < slot.qty:
            return True
    return False

# 查找当前需求中是否有被同层前排货物挡住的后排库位
def find_blocked_back_locations_for_need(
    need: Counter[str],
    cabinet_store: CabinetStore,
    reserved_depth: dict[str, int],
) -> list[str]:
    blocked_locations: list[str] = []

    for slot in sorted(cabinet_store.get_all_slots(), key=lambda item: location_sort_key(item.location_code)):
        if slot.is_empty:
            continue
        if not is_back_slot(slot.location_code):
            continue

        station_code, layer, _ = CabinetStore.parse_location(slot.location_code)
        if not layer_front_has_remaining_goods(cabinet_store, station_code, layer, reserved_depth):
            continue

        remaining_goods = slot.goods[reserved_depth.get(slot.location_code, 0):]
        if any(need.get(sku, 0) > 0 for sku in remaining_goods):
            blocked_locations.append(slot.location_code)

    return blocked_locations

# 夹爪对应夹取库位，工作站内编号为1的夹爪只能夹取库位靠近机械臂左边的货物，为2的夹爪只能夹取库位靠近机械臂右边的货物
def reachable_position_from_local_gripper(local_gripper_id: int) -> int:
    if local_gripper_id == 1:
        return 1
    if local_gripper_id == 2:
        return 2
    raise ValueError(f"未知工作站内部夹爪编号: {local_gripper_id}")

# 返回夹爪的位置方向（在工作站的左右）
def gripper_side(gripper_id: int) -> str:
    if gripper_id == 1:
        return "left"
    if gripper_id == 2:
        return "right"
    raise ValueError(f"未知夹爪编号: {gripper_id}")

# 统一转换流水线的编码
def normalize_line(line: str | None, manual_process_type: str | None = None) -> str:
    if manual_process_type == "G":
        return "GIFT"
    if manual_process_type == "S":
        return "SOFT"
    mapping = {
        "HS1": "HS1",
        "高速线1": "HS1",
        "HS2": "HS2",
        "高速线2": "HS2",
        "MP1": "MP1",
        "多盒包装线": "MP1",
        "MA1": "MA1",
        "人工处理线": "MA1",
        "MO1": "MO1",
        "合单缓存线": "MO1",
    }
    return mapping.get(line or "", line or "")

# 排序函数
def package_sort_key(info: PackagePlanInfo) -> tuple[int, int, int, str]:
    if info.total_goods == 1:
        return (
            priority_group(info),
            line_priority(info.target_line),
            0,
            info.package_id,
        )
    return (
        priority_group(info),
        info.total_goods,
        line_priority(info.target_line),
        info.package_id,
    )

# 单个货物包裹先出，其次出跨越工作站的多盒包裹，最后出多盒在同一工作站的包裹
def priority_group(info: PackagePlanInfo) -> int:
    if info.total_goods == 1:
        return 0
    if info.is_cross_station:
        return 1
    return 2

# 流水线靠前的先出
def line_priority(target_line: str) -> int:
    priorities = {
        "HS1": 0,
        "HS2": 1,
        "GIFT": 2,
        "SOFT": 2,
        "MP1": 3,
        "MA1": 4,
        "MO1": 5,
    }
    return priorities.get(target_line or "", 9)

# 转换夹爪编号，工作站(1,2) -> 全局(1,2,3,4,5,6)
def global_gripper_id(station_id: int, gripper_id: int) -> int:
    if station_id not in (1, 2, 3):
        raise ValueError(f"未知工作站 ID: {station_id}")
    if gripper_id not in (1, 2):
        raise ValueError(f"未知工作站内部夹爪编号: {gripper_id}")
    return (station_id - 1) * 2 + gripper_id
