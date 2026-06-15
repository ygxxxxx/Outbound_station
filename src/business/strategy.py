from __future__ import annotations
from typing import TYPE_CHECKING
from dataclasses import dataclass, field, replace
from collections import Counter

if TYPE_CHECKING:
    from src.business.task_manager import QueueTask

from src.utils.logger import logger
from src.models.containers import CabinetStore, SlotInfo
from src.models.outbound_plan_model import (
    OutboundPlan,
    OutboundBatch,
    PackageSegment,
    StationBatchPlan,
    GripperAction,
    PlacedItem,
    LocationMoveAction,
    CabinetBackwardAction,
    CabinetForwardAction,
)
from src.models.outbound_task_model import Package


logger = logger.bind(tag = "strategy")

MAX_GRIPPER_COUNT = 4
FRONT_POSITIONS = (1, 2)
BACK_POSITIONS = (3, 4)
BACK_TO_FRONT_POSITION = {3: 1, 4: 2}
STATION_CODES = ("A", "B", "C")
LOCAL_GRIPPER_IDS = (1, 2)

# 单件包裹合批时的库位顺序：先使用本轮还没有参与出库的全局夹爪。
# 这里覆盖 A/B/C 三个工作站的六个夹爪，不局限于同一个工作站内部的两个夹爪。
def slot_selection_sort_key(
    location_code: str,
    avoided_grippers: set[int],
) -> tuple[int, tuple[str, int, int]]:
    if not is_reachable_slot(location_code):
        return 2, location_sort_key(location_code)

    station_code, _, position = CabinetStore.parse_location(location_code)
    selected_gripper_id = global_gripper_id(
        station_id_from_code(station_code),
        gripper_id_from_position(position),
    )

    return (
        1 if selected_gripper_id in avoided_grippers else 0,
        location_sort_key(location_code),
    )


def _slot_clearance_sort_key(
    location_code: str,
    simulated_inventory: dict[str, list[str]],
) -> tuple:
    station_code, layer, position = CabinetStore.parse_location(location_code)

    has_back_goods = any(
        simulated_inventory.get(f"{station_code}{layer}{back_pos}", [])
        for back_pos in BACK_POSITIONS
    )

    front_total = sum(
        len(simulated_inventory.get(f"{station_code}{layer}{front_pos}", []))
        for front_pos in FRONT_POSITIONS
    )

    return (0 if has_back_goods else 1, front_total, station_code, layer, position)


# 策略算法内部用的库位级取货计划
@dataclass
class SlotPick:
    package_id: str             # 这个库位服务于哪个包裹
    target_line: str            # 这个包裹的流水线
    location_code: str          # 库位的编号
    station_code: str           # 工作站编号
    station_id: int             # 工作站id
    local_gripper_id: int       # 工作站内夹爪id，A/B/C 每个工作站内部都只有 1、2 号夹爪
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
    batch_group_id: int          # Planning barrier after simulated refill/location move; one batch cannot cross it
    clears_front_blocker: bool   # 是否正在清理会阻挡后排补位的前排库位
    before_backwards: list[CabinetBackwardAction] = field(default_factory=list) # 这个计划段执行前需要先做的库位后退
    before_moves: list[LocationMoveAction] = field(default_factory=list)        # 这个计划段执行前需要先做的库位移动
    before_forwards: list[CabinetForwardAction] = field(default_factory=list)    # 这个计划段执行前需要先做的后排补位


# 表示已经下发或准备下发的一次真实夹取动作。
# 同一次夹取可以在连续批次中为多个相邻包裹继续放货，因此这里需要跨批次追踪它。
@dataclass
class ActivePhysicalPick:
    command_action: GripperAction       # 第一次真正下发 PLC 的夹取动作
    actions: list[GripperAction]        # 计划中属于这次真实夹取的所有批次动作
    placed_count: int                   # 到当前已安排连续放置的货物数量
    last_batch_no: int                  # 这次夹取最后一次连续放置所在批次


# 根据 QueueTask 和当前库位库存生成出库计划
def strategy(queuetask: QueueTask, cabinet_store: CabinetStore) -> OutboundPlan:
    task = queuetask.task

    # build_package_infos() 会在模拟库存里动态选择“当前可出”的包裹，
    # 返回值已经是最终计划顺序；这里不要再二次排序，否则会破坏后排补位后的顺序。
    package_infos = build_package_infos(task.packages, cabinet_store)
    batches = build_batches(package_infos)
    reuse_consecutive_physical_picks(batches)
    package_segments = build_package_segments(package_infos, batches)

    plan = OutboundPlan(
        task_id=task.task_id,
        task_type=task.task_types,
        total_packages=len(task.packages),
        total_goods=sum(len(package.goods) for package in task.packages),
        batches=batches,
        package_segments=package_segments,
    )

    validate_plan(plan, cabinet_store)
    return plan


# 把包裹需求转换成PackagePlanInfo
def build_package_infos(packages: list[Package], cabinet_store: CabinetStore) -> list[PackagePlanInfo]:
    # 不直接修改真实 CabinetStore，在内存里维护一份模拟库存
    # 后续每计划一个包裹，就从模拟库存里扣掉已经放到流水线的货物
    simulated_inventory = build_simulated_inventory_from_store(cabinet_store)
    pending_packages = list(packages)
    remaining_goods_by_package = {
        package.package_id: list(package.goods)
        for package in packages
    }
    package_infos: list[PackagePlanInfo] = []
    pending_before_backwards: list[CabinetBackwardAction] = []
    pending_before_moves: list[LocationMoveAction] = []
    pending_before_forwards: list[CabinetForwardAction] = []
    forced_package_id: str | None = None
    last_target_line: str | None = None
    same_line_batch_count = 0
    single_wave_line: str | None = None
    single_wave_grippers: set[int] = set()
    batch_group_id = 0
    
    while pending_packages:
        candidate_infos: list[PackagePlanInfo] = []

        # 每一轮只挑“当前模拟库存下已经可直接出库”的包裹
        for package in pending_packages:
            if forced_package_id is not None and package.package_id != forced_package_id:
                continue
            remaining_goods = remaining_goods_by_package.get(package.package_id, [])
            if not remaining_goods:
                continue
            plan_package = package_with_goods(package, remaining_goods)
            slot_picks = choose_slots_for_package(
                package = plan_package,
                simulated_inventory = simulated_inventory,
                mutate_inventory = False,
            )
            if not slot_picks:
                continue
            candidate_infos.append(
                build_package_info(
                    package = plan_package,
                    slot_picks = slot_picks,
                    simulated_inventory = simulated_inventory,
                    batch_group_id = batch_group_id,
                )
            )

        if candidate_infos:
            # 候选包裹之间按规则 3、规则 12 等排序
            selected_info = choose_next_package_info(
                candidate_infos = candidate_infos,
                last_target_line = last_target_line,
                same_line_batch_count = same_line_batch_count,
            )
            selected_package = find_package_by_id(pending_packages, selected_info.package_id)
            if selected_package is None:
                raise ValueError(f"包裹 {selected_info.package_id} 已不在待计划列表中")

            # 同一流水线的单件包裹不需要独占，应优先铺满 A/B/C 中能够供货的全局夹爪
            if is_single_package_info(selected_info):
                if selected_info.clears_front_blocker:
                    # 清障包裹的优先级高于单件合批铺满夹爪。
                    # 这里不能为了避开已使用夹爪而换到其他库位，否则真正挡住后排的前排库位可能没有被清掉。
                    avoided_grippers = set()
                elif selected_info.target_line != single_wave_line:
                    single_wave_line = selected_info.target_line
                    single_wave_grippers = set()
                    avoided_grippers = single_wave_grippers
                else:
                    avoided_grippers = single_wave_grippers
            else:
                single_wave_line = None
                single_wave_grippers = set()
                avoided_grippers = set()

            selected_plan_package = package_with_goods(
                selected_package,
                remaining_goods_by_package[selected_package.package_id],
            )
            selected_slot_picks = choose_slots_for_package(
                package = selected_plan_package,
                simulated_inventory = simulated_inventory,
                mutate_inventory = True,
                avoid_global_grippers = avoided_grippers,
            )
            selected_info = build_package_info(
                package = selected_plan_package,
                slot_picks = selected_slot_picks,
                simulated_inventory = simulated_inventory,
                batch_group_id = batch_group_id,
                before_backwards = pending_before_backwards,
                before_moves = pending_before_moves,
                before_forwards = pending_before_forwards,
            )
            package_infos.append(selected_info)
            pending_before_backwards = []
            pending_before_moves = []
            pending_before_forwards = []
            consume_remaining_goods(
                remaining_goods_by_package,
                selected_info.package_id,
                planned_goods_from_slot_picks(selected_slot_picks),
            )
            if not remaining_goods_by_package[selected_info.package_id]:
                remove_pending_package(pending_packages, selected_info.package_id)
                forced_package_id = None
            elif forced_package_id == selected_info.package_id:
                # 同一个包裹已经进入前后排连续处理，后续继续优先处理它，避免中途插入其他包裹。
                forced_package_id = selected_info.package_id

            if is_single_package_info(selected_info):
                selected_gripper_id = selected_info.slot_picks[0].global_gripper_id
                if selected_gripper_id in single_wave_grippers:
                    # 所有可匹配夹爪都已经尝试过或当前 SKU 只能由该夹爪提供，
                    # 该动作成为下一放置轮的起点，后续单件再优先选择其他夹爪。
                    single_wave_grippers = {selected_gripper_id}
                else:
                    single_wave_grippers.add(selected_gripper_id)

            selected_batch_count = estimate_package_batch_count(selected_info)
            if selected_info.target_line == last_target_line:
                same_line_batch_count += selected_batch_count
            else:
                last_target_line = selected_info.target_line
                same_line_batch_count = selected_batch_count
            continue

        # 当前没有任何包裹能直接出库时，尝试把已经清空前排的后排货物补位到 1、2 位。
        forward_actions = shift_back_goods_to_front(simulated_inventory)
        if forward_actions:
            # Refill changes the real slot state, so later single packages must not be merged into earlier batches.
            pending_before_forwards.extend(forward_actions)
            batch_group_id += 1
            single_wave_line = None
            single_wave_grippers = set()
            continue

        same_package_info = try_build_same_package_front_blocker_info(
            pending_packages = pending_packages,
            remaining_goods_by_package = remaining_goods_by_package,
            simulated_inventory = simulated_inventory,
            batch_group_id = batch_group_id,
        )
        if same_package_info is not None:
            same_package_info.before_backwards.extend(pending_before_backwards)
            same_package_info.before_moves.extend(pending_before_moves)
            same_package_info.before_forwards.extend(pending_before_forwards)
            package_infos.append(same_package_info)
            pending_before_backwards = []
            pending_before_moves = []
            pending_before_forwards = []
            consume_remaining_goods(
                remaining_goods_by_package,
                same_package_info.package_id,
                planned_goods_from_slot_picks(same_package_info.slot_picks),
            )
            if not remaining_goods_by_package[same_package_info.package_id]:
                remove_pending_package(pending_packages, same_package_info.package_id)
                forced_package_id = None
            else:
                forced_package_id = same_package_info.package_id
            single_wave_line = None
            single_wave_grippers = set()
            continue

        resolved = try_resolve_by_location_adjustment(
            pending_packages = pending_packages,
            remaining_goods_by_package = remaining_goods_by_package,
            simulated_inventory = simulated_inventory,
        )
        if resolved is not None:
            before_backwards, before_moves = resolved
            pending_before_backwards.extend(before_backwards)
            pending_before_moves.extend(before_moves)
            # Location adjustment changes real pick positions; later plans must start a new execution group.
            batch_group_id += 1
            single_wave_line = None
            single_wave_grippers = set()
            continue

        raise ValueError(build_unschedulable_message(pending_packages, simulated_inventory, remaining_goods_by_package))

    return package_infos

# 给包裹选择库位
def choose_slots_for_package(package: Package,
    simulated_inventory: dict[str, list[str]],
    mutate_inventory: bool,
    avoid_global_grippers: set[int] | None = None,
) -> list[SlotPick]:
    # need 保存这个包裹还缺哪些 SKU。
    # Counter 的值会随着已选中的 planned_goods 逐个扣减，扣到 0 后删除。
    need = Counter(package.goods)
    selected: list[SlotPick] = []
    selected_locations: list[tuple[str, int]] = []
    location_codes = sorted(simulated_inventory.keys(), key = location_sort_key)

    if avoid_global_grippers:
        location_codes = sorted(
            location_codes,
            key = lambda code: slot_selection_sort_key(code, avoid_global_grippers),
        )

    for location_code in location_codes:
        if not need:
            break
        slot_goods = simulated_inventory.get(location_code, [])
        if not slot_goods:
            continue
        if len(slot_goods) > MAX_GRIPPER_COUNT:
            logger.info(f"库位 {location_code} 货物数量超过夹爪上限，已跳过")
            continue
        # 如果库位是夹爪取不到的，也就是在（3，4）位置上，跳过
        if not is_reachable_slot(location_code):
            continue
        
        # 从这个库位中挑出所需货物sku列表
        planned_goods = goods_needed_from_slot(
            location_code = location_code,
            slot_goods = slot_goods,
            need = need,
        )

        if not planned_goods:
            continue

        # SlotPick 是“这个包裹使用这个库位的计划”。
        # picked_goods 必须记录整个库位当前被夹起的货物，因为硬件每次都会整库位夹取；
        # planned_goods 只记录本包裹本次真正要放到流水线上的货物数量。
        slot = SlotInfo(location_code = location_code, goods = list(slot_goods))
        slot_pick = build_slot_pick(package, slot, planned_goods)
        selected.append(slot_pick)
        selected_locations.append((location_code, len(planned_goods)))

        for sku in planned_goods:
            need[sku] -= 1
            if need[sku] <= 0:
                del need[sku]

    if need:
        return []

    if mutate_inventory:
        # 确认选择这个包裹后，才真正推进模拟库存。
        # place_count 是 planned_goods 的数量，剩余未放完的货物会回到同一个前排库位。
        # 因为只能放置底部连续货物，所以这里直接从列表头部扣掉 placed_count 个 SKU。
        for location_code, placed_count in selected_locations:
            simulated_inventory[location_code] = simulated_inventory[location_code][placed_count:]

    return selected

def build_package_info(
    package: Package,
    slot_picks: list[SlotPick],
    simulated_inventory: dict[str, list[str]] | None = None,
    batch_group_id: int = 0,
    before_backwards: list[CabinetBackwardAction] | None = None,
    before_moves: list[LocationMoveAction] | None = None,
    before_forwards: list[CabinetForwardAction] | None = None,
) -> PackagePlanInfo:
    station_codes = sorted({slot_pick.station_code for slot_pick in slot_picks})
    target_line = normalize_line(package.packaging_line, package.manual_process_type)

    return PackagePlanInfo(
        package = package,
        package_id = package.package_id,
        target_line = target_line,
        total_goods = len(package.goods),
        slot_picks = slot_picks,
        station_codes = station_codes,
        is_cross_station = len(station_codes) > 1,
        is_multi_slot = len(slot_picks) > 1,
        clears_front_blocker = package_clears_front_blocker(slot_picks, simulated_inventory),
        batch_group_id = batch_group_id,
        before_backwards = list(before_backwards or []),
        before_moves = list(before_moves or []),
        before_forwards = list(before_forwards or []),
    )

def package_clears_front_blocker(
    slot_picks: list[SlotPick],
    simulated_inventory: dict[str, list[str]] | None,
) -> bool:
    if simulated_inventory is None:
        return False

    return any(
        is_front_slot_blocking_back_goods(
            location_code = slot_pick.location_code,
            simulated_inventory = simulated_inventory,
        )
        for slot_pick in slot_picks
    )

def is_front_slot_blocking_back_goods(
    location_code: str,
    simulated_inventory: dict[str, list[str]],
) -> bool:
    station_code, layer, position = CabinetStore.parse_location(location_code)

    if position not in FRONT_POSITIONS:
        return False

    # 当前后排补位逻辑要求同层两个前排都清空后才能整体补位。
    # 所以只要同层后排还有货，这个前排库位就属于清障优先候选。
    return any(
        simulated_inventory.get(f"{station_code}{layer}{back_position}", [])
        for back_position in BACK_POSITIONS
    )

def package_with_goods(package: Package, goods: list[str]) -> Package:
    return replace(package, goods=list(goods), count=len(goods))

def find_package_by_id(packages: list[Package], package_id: str) -> Package | None:
    for package in packages:
        if package.package_id == package_id:
            return package
    return None

def remove_pending_package(packages: list[Package], package_id: str) -> None:
    package = find_package_by_id(packages, package_id)
    if package is not None:
        packages.remove(package)

def planned_goods_from_slot_picks(slot_picks: list[SlotPick]) -> list[str]:
    return [
        sku
        for slot_pick in slot_picks
        for sku in slot_pick.planned_goods
    ]

def consume_remaining_goods(
    remaining_goods_by_package: dict[str, list[str]],
    package_id: str,
    planned_goods: list[str],
) -> None:
    remaining_goods = remaining_goods_by_package[package_id]
    for sku in planned_goods:
        if sku not in remaining_goods:
            raise ValueError(f"包裹 {package_id} 剩余需求中不存在已计划 SKU: {sku}")
        remaining_goods.remove(sku)

def front_location_for_back_slot(back_location: str) -> str:
    station_code, layer, position = CabinetStore.parse_location(back_location)
    if position not in BACK_TO_FRONT_POSITION:
        raise ValueError(f"{back_location} 不是后排库位")
    return f"{station_code}{layer}{BACK_TO_FRONT_POSITION[position]}"

def back_location_for_front_slot(front_location: str) -> str:
    station_code, layer, position = CabinetStore.parse_location(front_location)
    if position not in FRONT_POSITIONS:
        raise ValueError(f"{front_location} 不是前排库位")
    return f"{station_code}{layer}{position + 2}"

def try_build_same_package_front_blocker_info(
    pending_packages: list[Package],
    remaining_goods_by_package: dict[str, list[str]],
    simulated_inventory: dict[str, list[str]],
    batch_group_id: int,
) -> PackagePlanInfo | None:
    for package in pending_packages:
        remaining_goods = remaining_goods_by_package.get(package.package_id, [])
        if not remaining_goods:
            continue

        package_need = Counter(remaining_goods)
        for station_code in STATION_CODES:
            for layer in range(1, 5):
                front_locations = [
                    f"{station_code}{layer}{front_position}"
                    for front_position in FRONT_POSITIONS
                    if simulated_inventory.get(f"{station_code}{layer}{front_position}", [])
                ]
                if len(front_locations) != 1:
                    continue

                front_location = front_locations[0]
                front_goods = list(simulated_inventory.get(front_location, []))
                if not front_goods or len(front_goods) > MAX_GRIPPER_COUNT:
                    continue
                if not goods_all_in_need(front_goods, package_need):
                    continue

                back_locations = [f"{station_code}{layer}{back_position}" for back_position in BACK_POSITIONS]
                if not any(back_goods_needed_by_package(location, package_need, simulated_inventory) for location in back_locations):
                    continue

                plan_package = package_with_goods(package, front_goods)
                slot_pick = build_slot_pick(
                    package = plan_package,
                    slot = SlotInfo(location_code = front_location, goods = front_goods),
                    planned_goods = front_goods,
                )
                simulated_inventory[front_location] = simulated_inventory[front_location][len(front_goods):]
                logger.info(
                    f"同包裹前排阻挡先出: package={package.package_id}, "
                    f"location={front_location}, goods={front_goods}"
                )
                return build_package_info(
                    package = plan_package,
                    slot_picks = [slot_pick],
                    simulated_inventory = simulated_inventory,
                    batch_group_id = batch_group_id,
                )

    return None

def goods_all_in_need(goods: list[str], need: Counter[str]) -> bool:
    local_need = need.copy()
    for sku in goods:
        if local_need.get(sku, 0) <= 0:
            return False
        local_need[sku] -= 1
    return True

def back_goods_needed_by_package(
    location_code: str,
    need: Counter[str],
    simulated_inventory: dict[str, list[str]],
) -> bool:
    goods = simulated_inventory.get(location_code, [])
    return bool(goods and any(need.get(sku, 0) > 0 for sku in goods))

def try_resolve_by_location_adjustment(
    pending_packages: list[Package],
    remaining_goods_by_package: dict[str, list[str]],
    simulated_inventory: dict[str, list[str]],
) -> tuple[list[CabinetBackwardAction], list[LocationMoveAction]] | None:
    blocker = find_front_blocker_for_pending_back_goods(
        pending_packages = pending_packages,
        remaining_goods_by_package = remaining_goods_by_package,
        simulated_inventory = simulated_inventory,
    )
    if blocker is None:
        return None

    front_location, package_id, back_location = blocker
    before_backwards: list[CabinetBackwardAction] = []
    target_location = find_empty_front_buffer_slot(front_location, simulated_inventory)

    if target_location is None:
        backward_action = build_backward_action_for_buffer(front_location, simulated_inventory)
        if backward_action is None:
            logger.info(
                f"库位调控失败: package={package_id}, back_location={back_location}, "
                f"front_location={front_location}, front_goods={simulated_inventory.get(front_location, [])}"
            )
            return None

        apply_backward_to_simulation(backward_action, simulated_inventory)
        before_backwards.append(backward_action)
        _, _, position = CabinetStore.parse_location(front_location)
        target_location = f"{backward_action.station_code}{backward_action.layer}{position}"

    move_action = build_location_move_action(
        from_location = front_location,
        to_location = target_location,
        simulated_inventory = simulated_inventory,
    )
    apply_location_move_to_simulation(move_action, simulated_inventory)
    logger.info(
        f"策略生成库位调控: package={package_id}, blocked_back={back_location}, "
        f"move={move_action.from_location}->{move_action.to_location}, goods={move_action.goods}"
    )
    return before_backwards, [move_action]

def find_front_blocker_for_pending_back_goods(
    pending_packages: list[Package],
    remaining_goods_by_package: dict[str, list[str]],
    simulated_inventory: dict[str, list[str]],
) -> tuple[str, str, str] | None:
    for package in pending_packages:
        need = Counter(remaining_goods_by_package.get(package.package_id, []))
        if not need:
            continue

        for location_code in sorted(simulated_inventory.keys(), key = location_sort_key):
            _, _, position = CabinetStore.parse_location(location_code)
            if position not in BACK_POSITIONS:
                continue
            if not back_goods_needed_by_package(location_code, need, simulated_inventory):
                continue

            front_location = front_location_for_back_slot(location_code)
            if simulated_inventory.get(front_location, []):
                return front_location, package.package_id, location_code

    return None

def find_empty_front_buffer_slot(
    from_location: str,
    simulated_inventory: dict[str, list[str]],
) -> str | None:
    station_code, _, position = CabinetStore.parse_location(from_location)

    for layer in range(1, 5):
        candidate = f"{station_code}{layer}{position}"
        if candidate == from_location:
            continue
        if not simulated_inventory.get(candidate, []):
            return candidate

    return None

def build_backward_action_for_buffer(
    from_location: str,
    simulated_inventory: dict[str, list[str]],
) -> CabinetBackwardAction | None:
    station_code, from_layer, _ = CabinetStore.parse_location(from_location)

    for layer in range(1, 5):
        if layer == from_layer:
            continue
        back_left = f"{station_code}{layer}3"
        back_right = f"{station_code}{layer}4"
        if simulated_inventory.get(back_left, []) or simulated_inventory.get(back_right, []):
            continue

        station_id = station_id_from_code(station_code)
        moved_goods = {
            f"{station_code}{layer}1->{station_code}{layer}3": list(simulated_inventory.get(f"{station_code}{layer}1", [])),
            f"{station_code}{layer}2->{station_code}{layer}4": list(simulated_inventory.get(f"{station_code}{layer}2", [])),
        }
        return CabinetBackwardAction(
            station_code = station_code,
            station_id = station_id,
            layer = layer,
            moved_goods = {key: value for key, value in moved_goods.items() if value},
        )

    return None

def apply_backward_to_simulation(
    action: CabinetBackwardAction,
    simulated_inventory: dict[str, list[str]],
) -> None:
    station_code = action.station_code
    layer = action.layer
    left_front = f"{station_code}{layer}1"
    right_front = f"{station_code}{layer}2"
    left_back = f"{station_code}{layer}3"
    right_back = f"{station_code}{layer}4"

    if simulated_inventory.get(left_back, []) or simulated_inventory.get(right_back, []):
        raise ValueError(f"{station_code}{layer}层后排不为空，不能模拟后退")

    simulated_inventory[left_back] = list(simulated_inventory.get(left_front, []))
    simulated_inventory[right_back] = list(simulated_inventory.get(right_front, []))
    simulated_inventory[left_front] = []
    simulated_inventory[right_front] = []
    logger.info(f"模拟库位后退: 工作站={station_code}, layer={layer}, moved={action.moved_goods}")

def build_location_move_action(
    from_location: str,
    to_location: str,
    simulated_inventory: dict[str, list[str]],
) -> LocationMoveAction:
    from_station, from_layer, from_position = CabinetStore.parse_location(from_location)
    to_station, to_layer, to_position = CabinetStore.parse_location(to_location)

    if from_station != to_station:
        raise ValueError(f"库位移动不能跨工作站: {from_location}->{to_location}")
    if from_position != to_position:
        raise ValueError(f"库位移动不能跨夹爪列: {from_location}->{to_location}")

    goods = list(simulated_inventory.get(from_location, []))
    if not goods:
        raise ValueError(f"库位移动原库位为空: {from_location}")
    if simulated_inventory.get(to_location, []):
        raise ValueError(f"库位移动目标库位不为空: {to_location}")

    station_id = station_id_from_code(from_station)
    local_gripper_id = gripper_id_from_position(from_position)
    return LocationMoveAction(
        station_code = from_station,
        station_id = station_id,
        gripper_id = global_gripper_id(station_id, local_gripper_id),
        from_location = from_location,
        to_location = to_location,
        from_layer = from_layer,
        to_layer = to_layer,
        goods = goods,
    )

def apply_location_move_to_simulation(
    action: LocationMoveAction,
    simulated_inventory: dict[str, list[str]],
) -> None:
    if not simulated_inventory.get(action.from_location, []):
        raise ValueError(f"模拟库位移动失败，原库位为空: {action.from_location}")
    if simulated_inventory.get(action.to_location, []):
        raise ValueError(f"模拟库位移动失败，目标库位不为空: {action.to_location}")

    simulated_inventory[action.to_location] = list(simulated_inventory[action.from_location])
    simulated_inventory[action.from_location] = []

def build_simulated_inventory_from_store(cabinet_store: CabinetStore) -> dict[str, list[str]]:
    simulated_inventory: dict[str, list[str]] = {}
    for slot in cabinet_store.get_all_slots():
        simulated_inventory[slot.location_code] = list(slot.goods)
    return simulated_inventory

def shift_back_goods_to_front(simulated_inventory: dict[str, list[str]]) -> list[CabinetForwardAction]:
    actions: list[CabinetForwardAction] = []
    station_codes = sorted({location_code[0] for location_code in simulated_inventory})

    for station_code in station_codes:
        for layer in range(1, 5):
            front_locations = [f"{station_code}{layer}{position}" for position in FRONT_POSITIONS]

            # 这一层两个前排库位必须都清空，后排货物才允许整体补位。
            # 只清空 A11 但 A12 仍有货时，A13/A14 都不能补位，这是机械结构硬规则。
            if any(simulated_inventory.get(location_code, []) for location_code in front_locations):
                continue

            moved_goods: dict[str, list[str]] = {}
            for back_position, front_position in BACK_TO_FRONT_POSITION.items():
                back_location = f"{station_code}{layer}{back_position}"
                front_location = f"{station_code}{layer}{front_position}"
                back_goods = simulated_inventory.get(back_location, [])
                if not back_goods:
                    continue

                simulated_inventory[front_location] = list(back_goods)
                simulated_inventory[back_location] = []
                moved_goods[f"{back_location}->{front_location}"] = list(back_goods)
                logger.info(f"模拟后排补位: {back_location} -> {front_location}, goods={back_goods}")

            if moved_goods:
                actions.append(
                    CabinetForwardAction(
                        station_code = station_code,
                        station_id = station_id_from_code(station_code),
                        layer = layer,
                        moved_goods = moved_goods,
                    )
                )

    return actions

def build_unschedulable_message(
    pending_packages: list[Package],
    simulated_inventory: dict[str, list[str]],
    remaining_goods_by_package: dict[str, list[str]] | None = None,
) -> str:
    package_ids = [package.package_id for package in pending_packages]
    remaining_needs = {
        package.package_id: list(remaining_goods_by_package.get(package.package_id, package.goods))
        for package in pending_packages
    } if remaining_goods_by_package is not None else {
        package.package_id: list(package.goods)
        for package in pending_packages
    }
    remaining_goods = {
        location_code: goods
        for location_code, goods in simulated_inventory.items()
        if goods
    }
    blockers = find_blocking_details(pending_packages, remaining_needs, simulated_inventory)
    return (
        f"剩余包裹无法继续生成出库计划: packages={package_ids}, "
        f"remaining_needs={remaining_needs}, blockers={blockers}, "
        f"remaining_inventory={remaining_goods}"
    )

def find_blocking_details(
    pending_packages: list[Package],
    remaining_needs: dict[str, list[str]],
    simulated_inventory: dict[str, list[str]],
) -> list[dict]:
    details: list[dict] = []
    for package in pending_packages:
        need = Counter(remaining_needs.get(package.package_id, []))
        for location_code in sorted(simulated_inventory.keys(), key = location_sort_key):
            station_code, layer, position = CabinetStore.parse_location(location_code)
            if position not in BACK_POSITIONS:
                continue
            back_goods = simulated_inventory.get(location_code, [])
            if not back_goods or not any(need.get(sku, 0) > 0 for sku in back_goods):
                continue

            front_location = front_location_for_back_slot(location_code)
            front_goods = simulated_inventory.get(front_location, [])
            if front_goods:
                details.append({
                    "package_id": package.package_id,
                    "back_location": location_code,
                    "back_goods": list(back_goods),
                    "front_location": front_location,
                    "front_goods": list(front_goods),
                    "reason": "后排待出货物被前排货物阻挡，且未找到可用库位调控方案",
                    "station": station_code,
                    "layer": layer,
                })
    return details

def sort_package_infos(package_infos: list[PackagePlanInfo]) -> list[PackagePlanInfo]:
    return sorted(package_infos, key = package_sort_key)

def choose_next_package_info(
    candidate_infos: list[PackagePlanInfo],
    last_target_line: str | None,
    same_line_batch_count: int,
) -> PackagePlanInfo:
    sorted_infos = sort_package_infos(candidate_infos)

    # 规则 5：如果已经连续三批都是同一条流水线，下一次尽量切到其他流水线。
    # 这里的“下一次”只能发生在包裹边界，不能打断一个正在连续出库的多件包裹。
    # 单件包裹会在 build_batches() 阶段合并成同一个批次，所以不能在这里用“单件包裹个数”
    # 去提前判断三批同线，否则会把本来能同批出的单件包裹拆散。
    if is_single_package_info(sorted_infos[0]):
        return sorted_infos[0]

    if last_target_line is None or same_line_batch_count < 3:
        return sorted_infos[0]

    for info in sorted_infos:
        if info.target_line != last_target_line:
            return info

    return sorted_infos[0]

def estimate_package_batch_count(info: PackagePlanInfo) -> int:
    # 一次写入 PLC 的所有夹爪必须共同完成后，才允许写入下一组夹爪数据。
    # 所以包裹占用批次数应按“同步命令波次”的最长 place_count 累加计算。
    return sum(
        max(len(slot_pick.planned_goods) for slot_pick in command_wave)
        for command_wave in build_command_waves(info.slot_picks)
    )

def build_command_waves(slot_picks: list[SlotPick]) -> list[list[SlotPick]]:
    pending_slot_picks = list(slot_picks)
    command_waves: list[list[SlotPick]] = []

    while pending_slot_picks:
        command_wave: list[SlotPick] = []
        remaining_slot_picks: list[SlotPick] = []
        used_global_grippers: set[int] = set()

        # 一次 PLC 指令中，同一个夹爪最多接收一个新取货动作。
        # 没能进入当前波次的动作，必须等当前波次所有夹爪都结束后再统一下发。
        for slot_pick in pending_slot_picks:
            if slot_pick.global_gripper_id in used_global_grippers:
                remaining_slot_picks.append(slot_pick)
                continue

            command_wave.append(slot_pick)
            used_global_grippers.add(slot_pick.global_gripper_id)

        command_waves.append(command_wave)
        pending_slot_picks = remaining_slot_picks

    return command_waves

def build_batches(sorted_infos: list[PackagePlanInfo]) -> list[OutboundBatch]:
    batches: list[OutboundBatch] = []
    next_batch_no = 1
    next_sequence = 1
    index = 0

    while index < len(sorted_infos):
        info = sorted_infos[index]

        if is_single_package_info(info):
            batch_line = info.target_line
            batch_group_id = info.batch_group_id
            same_line_infos: list[PackagePlanInfo] = []

            # 单件包裹不需要独占批次。
            # 这里先把同一条流水线的连续单件包裹收集起来，后面再按 6 个全局夹爪分批。
            while index < len(sorted_infos):
                candidate = sorted_infos[index]
                if (
                    not is_single_package_info(candidate)
                    or candidate.target_line != batch_line
                    or candidate.batch_group_id != batch_group_id
                ):
                    break

                same_line_infos.append(candidate)
                index += 1

            single_batches, next_batch_no, next_sequence = build_single_package_batches(
                infos = same_line_infos,
                start_batch_no = next_batch_no,
                start_sequence = next_sequence,
            )
            batches.extend(single_batches)
            continue

        # 每个包裹从当前 next_batch_no / next_sequence 接着往后生成。
        # 返回的新编号会被下一个包裹继续使用，从而保证整个任务批次和 sequence 全局连续。
        package_batches, next_batch_no, next_sequence = build_batches_for_package(
            info = info,
            start_batch_no = next_batch_no,
            start_sequence = next_sequence,
        )
        batches.extend(package_batches)
        index += 1

    return batches

def is_single_package_info(info: PackagePlanInfo) -> bool:
    return (
        info.total_goods == 1
        and len(info.slot_picks) == 1
        and len(info.slot_picks[0].planned_goods) == 1
    )

def build_single_package_batches(
    infos: list[PackagePlanInfo],
    start_batch_no: int,
    start_sequence: int,
) -> tuple[list[OutboundBatch], int, int]:
    batches: list[OutboundBatch] = []
    pending_infos = list(infos)
    batch_no = start_batch_no
    next_sequence = start_sequence

    while pending_infos:
        batch_infos: list[PackagePlanInfo] = []
        remaining_infos: list[PackagePlanInfo] = []
        used_global_grippers: set[int] = set()

        # 单件包裹合批时，业务上只要求目标流水线一致。
        # 这里仍然按物理夹爪分批：同一批内同一个全局夹爪只能服务一个库位。
        for info in pending_infos:
            slot_pick = info.slot_picks[0]
            if slot_pick.global_gripper_id in used_global_grippers:
                remaining_infos.append(info)
                continue

            batch_infos.append(info)
            used_global_grippers.add(slot_pick.global_gripper_id)

        batch, batch_no, next_sequence = build_single_package_batch(
            infos = batch_infos,
            batch_no = batch_no,
            start_sequence = next_sequence,
        )
        batches.append(batch)
        pending_infos = remaining_infos

    return batches, batch_no, next_sequence

def build_single_package_batch(
    infos: list[PackagePlanInfo],
    batch_no: int,
    start_sequence: int,
) -> tuple[OutboundBatch, int, int]:
    command_actions: list[GripperAction] = []

    for info in infos:
        slot_pick = info.slot_picks[0]
        action = create_gripper_action(
            slot_pick = slot_pick,
            current_slot_goods = slot_pick.picked_goods,
            batch_no = batch_no,
            start_sequence = 0,
        )
        command_actions.append(action)

    next_sequence = renumber_placed_items(command_actions, start_sequence)
    batch = empty_batch(
        batch_no = batch_no,
        target_line = batch_target_line(infos),
        exclusive = False,
        exclusive_package_id = None,
        package_ids = [info.package_id for info in infos],
    )
    attach_pre_actions_to_batch(batch, infos)
    attach_actions_to_batch(batch, command_actions)
    fill_idle_actions(batch)
    update_batch_sequence_range(batch)

    return batch, batch_no + 1, next_sequence

def batch_target_line(infos: list[PackagePlanInfo]) -> str | None:
    target_lines = {info.target_line for info in infos if info.target_line}
    if not target_lines:
        return None
    if len(target_lines) == 1:
        return next(iter(target_lines))
    return "MIXED"

def build_batches_for_package(
    info: PackagePlanInfo,
    start_batch_no: int,
    start_sequence: int,
) -> tuple[list[OutboundBatch], int, int]:
    command_actions: list[GripperAction] = []

    if not info.slot_picks:
        return [], start_batch_no, start_sequence

    next_command_batch_no = start_batch_no
    for command_wave in build_command_waves(info.slot_picks):
        wave_actions: list[GripperAction] = []

        for slot_pick in command_wave:
            action = create_gripper_action(
                slot_pick = slot_pick,
                current_slot_goods = slot_pick.picked_goods,
                batch_no = next_command_batch_no,
                start_sequence = 0,
            )
            wave_actions.append(action)
            command_actions.append(action)

        # 这一组夹爪是同时写给 PLC 的命令。
        # 即使有夹爪 place_count 较小而提前空闲，也必须等待本组最长动作放完，
        # 下一组夹爪命令才能在后续批次一起写入 PLC。
        wave_duration = max(action.place_count for action in wave_actions)
        next_command_batch_no += wave_duration

    next_sequence = renumber_placed_items(command_actions, start_sequence)
    last_batch_no = max(
        (
            item.place_batch_no
            for action in command_actions
            for item in action.placed_items
        ),
        default = start_batch_no,
    )

    package_batches: list[OutboundBatch] = []
    for batch_no in range(start_batch_no, last_batch_no + 1):
        # 当前实现按包裹连续生成批次，避免一个包裹的连续段中被其他包裹插入。
        # 这比最大化并行利用率保守，但更容易严格满足连续出库和跨工作站包裹独占规则。
        batch = empty_batch(
            batch_no = batch_no,
            target_line = info.target_line,
            exclusive = should_keep_package_exclusive(info),
            exclusive_package_id = info.package_id if should_keep_package_exclusive(info) else None,
            package_ids = [info.package_id],
        )
        if batch_no == start_batch_no:
            attach_pre_actions_to_batch(batch, [info])
        attach_actions_to_batch(batch, command_actions)
        fill_idle_actions(batch)
        update_batch_sequence_range(batch)
        package_batches.append(batch)

    return package_batches, last_batch_no + 1, next_sequence

def attach_pre_actions_to_batch(batch: OutboundBatch, infos: list[PackagePlanInfo]) -> None:
    for info in infos:
        batch.before_backwards.extend(info.before_backwards)
        batch.before_moves.extend(info.before_moves)
        batch.before_forwards.extend(info.before_forwards)

def reuse_consecutive_physical_picks(batches: list[OutboundBatch]) -> None:
    active_picks: dict[tuple[int, str], ActivePhysicalPick] = {}

    for batch in batches:
        action_refs = batch_pick_action_refs(batch)
        new_command_refs = [
            action_ref
            for action_ref in action_refs
            if action_ref[2].send_to_plc
        ]
        continuing_refs = [
            action_ref
            for action_ref in action_refs
            if not action_ref[2].send_to_plc
        ]

        # 原始计划中如果本批次已经是同一次夹取的后续放置，
        # 只需要把它接到当前正在追踪的真实夹取上。
        if continuing_refs and not new_command_refs:
            for station_plan, action_index, action in continuing_refs:
                physical_pick = active_picks.get(physical_pick_key(action))
                if physical_pick is None or not can_append_to_physical_pick(physical_pick, action, batch.batch_no):
                    raise ValueError(f"批次 {batch.batch_no} 的连续放置动作找不到对应的原始夹取命令")
                append_action_to_physical_pick(
                    physical_pick = physical_pick,
                    batch_no = batch.batch_no,
                    placed_items = action.placed_items,
                    station_plan = station_plan,
                    action_index = action_index,
                )
            continue

        # 本批次本来准备重新夹取，但如果所有实际出货动作都能由上一批正在连续放置的
        # 夹爪继续提供，就应复用第一次整库位夹取，而不是让货物回库后重新抓取。
        if new_command_refs and can_reuse_previous_physical_picks(
            batch_no = batch.batch_no,
            action_refs = new_command_refs,
            active_picks = active_picks,
        ):
            for station_plan, action_index, action in new_command_refs:
                append_action_to_physical_pick(
                    physical_pick = active_picks[physical_pick_key(action)],
                    batch_no = batch.batch_no,
                    placed_items = action.placed_items,
                    station_plan = station_plan,
                    action_index = action_index,
                )
            logger.info(f"批次 {batch.batch_no} 复用上一批夹爪已夹起的剩余货物，不重新下发取货命令")
            continue

        # 不能整体复用时，本批次仍是一轮新的 PLC 夹取命令。
        # 这里整体替换追踪集合，是为了遵守“上一轮未结束时不能写新夹爪数据”的硬件约束。
        if new_command_refs:
            active_picks = {
                physical_pick_key(action): ActivePhysicalPick(
                    command_action = action,
                    actions = [action],
                    placed_count = len(action.placed_items),
                    last_batch_no = batch.batch_no,
                )
                for _, _, action in new_command_refs
            }
            continue

        active_picks = {}

def batch_pick_action_refs(
    batch: OutboundBatch,
) -> list[tuple[StationBatchPlan, int, GripperAction]]:
    return [
        (station_plan, action_index, action)
        for station_plan in batch.station_plans
        for action_index, action in enumerate(station_plan.actions)
        if action.action_type == "pick"
    ]

def physical_pick_key(action: GripperAction) -> tuple[int, str]:
    if action.location_code is None:
        raise ValueError("真实取货动作必须包含 location_code")
    return action.global_gripper_id, action.location_code

def can_reuse_previous_physical_picks(
    batch_no: int,
    action_refs: list[tuple[StationBatchPlan, int, GripperAction]],
    active_picks: dict[tuple[int, str], ActivePhysicalPick],
) -> bool:
    if not active_picks:
        return False

    return all(
        (
            physical_pick_key(action) in active_picks
            and can_append_to_physical_pick(
                active_picks[physical_pick_key(action)],
                action,
                batch_no,
            )
        )
        for _, _, action in action_refs
    )

def can_append_to_physical_pick(
    physical_pick: ActivePhysicalPick,
    action: GripperAction,
    batch_no: int,
) -> bool:
    if physical_pick.last_batch_no != batch_no - 1:
        return False
    if physical_pick.command_action.target_line != action.target_line:
        return False

    placed_skus = [item.goods_sku for item in action.placed_items]
    start_index = physical_pick.placed_count
    end_index = start_index + len(placed_skus)
    remaining_prefix = physical_pick.command_action.picked_goods[start_index:end_index]
    return remaining_prefix == placed_skus

def append_action_to_physical_pick(
    physical_pick: ActivePhysicalPick,
    batch_no: int,
    placed_items: list[PlacedItem],
    station_plan: StationBatchPlan,
    action_index: int,
) -> None:
    continued_action = clone_action_for_batch(
        command = physical_pick.command_action,
        batch_no = batch_no,
        placed_items = placed_items,
    )
    continued_action.send_to_plc = False
    station_plan.actions[action_index] = continued_action

    physical_pick.actions.append(continued_action)
    physical_pick.placed_count += len(placed_items)
    physical_pick.last_batch_no = batch_no

    # place_count 在第一次取货指令下发时就必须包含未来所有连续放置批次。
    # 因此识别出跨包裹复用后，要把同一次物理夹取的所有计划视图统一更新。
    for action in physical_pick.actions:
        action.place_count = physical_pick.placed_count

def build_package_segments(
    package_infos: list[PackagePlanInfo],
    batches: list[OutboundBatch],
) -> list[PackageSegment]:
    info_by_id = {info.package_id: info for info in package_infos}
    station_codes_by_id: dict[str, set[str]] = {}
    exclusive_by_id: dict[str, bool] = {}
    for info in package_infos:
        station_codes_by_id.setdefault(info.package_id, set()).update(info.station_codes)
        exclusive_by_id[info.package_id] = exclusive_by_id.get(info.package_id, False) or should_keep_package_exclusive(info)
    package_items: dict[str, list[PlacedItem]] = {}
    package_batches: dict[str, set[int]] = {}

    # 先从批次反查每个包裹实际落线了哪些货，以及这些货分布在哪些批次里。
    # PackageSegment 不参与 PLC 控制，它的价值是让执行层和校验层能快速确认包裹是否连续。
    for batch in batches:
        for station_plan in batch.station_plans:
            for action in station_plan.actions:
                for item in action.placed_items:
                    package_items.setdefault(item.package_id, []).append(item)
                    package_batches.setdefault(item.package_id, set()).add(batch.batch_no)

    segments: list[PackageSegment] = []
    for package_id, items in package_items.items():
        info = info_by_id[package_id]
        sequences = sorted(item.sequence for item in items)
        batch_numbers = sorted(package_batches[package_id])

        segments.append(
            PackageSegment(
                package_id = package_id,
                target_line = info.target_line,
                total_goods = len(items),
                batch_start = batch_numbers[0],
                batch_end = batch_numbers[-1],
                sequence_start = sequences[0],
                sequence_end = sequences[-1],
                station_codes = sorted(station_codes_by_id.get(package_id, set(info.station_codes))),
                exclusive = exclusive_by_id.get(package_id, should_keep_package_exclusive(info)),
            )
        )

    segments.sort(key = lambda segment: segment.sequence_start)
    return segments

def count_placed_items(batches: list[OutboundBatch]) -> int:
    # placed_items 才代表真正放到流水线上的货物。
    # picked_goods 不能用于计数，因为夹爪可能夹起 4 个但本次只放 1 到 4 个中的一部分。
    return sum(
        len(action.placed_items)
        for batch in batches
        for station_plan in batch.station_plans
        for action in station_plan.actions
    )

def validate_plan(plan: OutboundPlan, cabinet_store: CabinetStore) -> None:
    # cabinet_store 当前保留在签名里，方便后续补充“计划是否仍匹配当前库存”的交叉校验。
    # 现在这里先做不依赖外部状态的结构校验和规则校验。
    check_batch_shape(plan)
    check_batch_outbound_count(plan)
    check_action_counts(plan)
    check_command_wave_barrier(plan)
    check_location_layer_consistency(plan)
    check_station_target_line(plan)
    check_sequence_continuous(plan)
    check_package_segments(plan)

    if count_placed_items(plan.batches) != plan.total_goods:
        raise ValueError("计划出库货物数量和任务货物数量不一致")

# 创建空批次
def empty_batch(
    batch_no: int,
    target_line: str | None,
    exclusive: bool = False,
    exclusive_package_id: str | None = None,
    package_ids: list[str] | None = None,
) -> OutboundBatch:
    station_plans = []
    for station_code in STATION_CODES:
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
        exclusive=exclusive,
        exclusive_package_id=exclusive_package_id,
        package_ids=list(package_ids or []),
        station_plans=station_plans,
    )

# 夹爪命令
def create_gripper_action(
    slot_pick: SlotPick,
    current_slot_goods: list[str],
    batch_no: int,
    start_sequence: int,
) -> GripperAction:
    # current_slot_goods 是计划生成时模拟出来的“动作执行到这一刻库位上剩余货物”。
    # 夹爪会整库位夹起它们，但只能把底部连续的 planned_goods 放上流水线。
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
        local_gripper_id=slot_pick.local_gripper_id,
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
        send_to_plc=True,
    )

def attach_actions_to_batch(batch: OutboundBatch, command_actions: list[GripperAction]) -> None:
    for command in command_actions:
        placed_items = [
            item
            for item in command.placed_items
            if item.place_batch_no == batch.batch_no
        ]
        if not placed_items:
            continue

        action = clone_action_for_batch(command, batch.batch_no, placed_items)
        station_plan = batch.station_plans[action.station_id - 1]
        station_plan.actions.append(action)
        station_plan.target_line = action.target_line

def clone_action_for_batch(
    command: GripperAction,
    batch_no: int,
    placed_items: list[PlacedItem],
) -> GripperAction:
    is_command_batch = batch_no == command.batch_no

    # 一个 PLC 取货命令可能覆盖多个连续批次：
    # 第一个批次 send_to_plc=True，执行层真正下发 pick/place_count；
    # 后续批次只保留 placed_items 轨迹，表示同一次夹取的第 2、3、4 个货物分别在哪些批次落线。
    return GripperAction(
        action_type = "pick",
        station_id = command.station_id,
        station_code = command.station_code,
        local_gripper_id = command.local_gripper_id,
        global_gripper_id = command.global_gripper_id,
        gripper_side = command.gripper_side,
        layer = command.layer,
        location_code = command.location_code,
        picked_count = command.picked_count,
        place_count = command.place_count,
        size = command.size,
        batch_no = batch_no,
        target_line = command.target_line,
        picked_goods = list(command.picked_goods),
        placed_items = list(placed_items),
        send_to_plc = is_command_batch,
    )

def fill_idle_actions(batch: OutboundBatch) -> None:
    for station_plan in batch.station_plans:
        used_grippers = {action.local_gripper_id for action in station_plan.actions}
        for gripper_id in LOCAL_GRIPPER_IDS:
            if gripper_id in used_grippers:
                continue
            station_plan.actions.append(
                idle_action(
                    batch_no = batch.batch_no,
                    station_id = station_plan.station_id,
                    station_code = station_plan.station_code,
                    gripper_id = gripper_id,
                )
            )
        station_plan.actions.sort(key = lambda action: action.local_gripper_id)

def idle_action(
    batch_no: int,
    station_id: int,
    station_code: str,
    gripper_id: int,
) -> GripperAction:
    return GripperAction(
        action_type = "idle",
        station_id = station_id,
        station_code = station_code,
        local_gripper_id = gripper_id,
        global_gripper_id = global_gripper_id(station_id, gripper_id),
        gripper_side = gripper_side(gripper_id),
        layer = None,
        location_code = None,
        picked_count = 0,
        place_count = 0,
        size = None,
        batch_no = batch_no,
        target_line = None,
        picked_goods = [],
        placed_items = [],
        send_to_plc = False,
    )

def update_batch_sequence_range(batch: OutboundBatch) -> None:
    sequences = [
        item.sequence
        for station_plan in batch.station_plans
        for action in station_plan.actions
        for item in action.placed_items
    ]
    batch.outbound_count = len(sequences)
    if not sequences:
        batch.sequence_start = None
        batch.sequence_end = None
        return

    batch.sequence_start = min(sequences)
    batch.sequence_end = max(sequences)

def renumber_placed_items(actions: list[GripperAction], start_sequence: int) -> int:
    # sequence 是整个任务级别的真实落线顺序。
    # 同一批次内按工作站、夹爪编号排序，保证序号稳定、可复现。
    ordered_items = [
        (item.place_batch_no, action.station_id, action.local_gripper_id, item)
        for action in actions
        for item in action.placed_items
    ]
    ordered_items.sort(key = lambda value: (value[0], value[1], value[2]))

    sequence = start_sequence
    for _, _, _, item in ordered_items:
        item.sequence = sequence
        sequence += 1

    return sequence

def check_batch_shape(plan: OutboundPlan) -> None:
    for batch in plan.batches:
        if len(batch.station_plans) != len(STATION_CODES):
            raise ValueError(f"批次 {batch.batch_no} 工作站数量不正确")

        for station_plan in batch.station_plans:
            if len(station_plan.actions) != len(LOCAL_GRIPPER_IDS):
                raise ValueError(f"批次 {batch.batch_no} 工作站 {station_plan.station_code} 夹爪数量不正确")

def check_batch_outbound_count(plan: OutboundPlan) -> None:
    for batch in plan.batches:
        actual_count = sum(
            len(action.placed_items)
            for station_plan in batch.station_plans
            for action in station_plan.actions
        )
        if batch.outbound_count != actual_count:
            raise ValueError(
                f"批次 {batch.batch_no} outbound_count 不正确，"
                f"模型值 {batch.outbound_count}，实际落线数量 {actual_count}"
            )

def check_action_counts(plan: OutboundPlan) -> None:
    for action in all_actions(plan):
        if action.action_type == "idle":
            if action.picked_count != 0 or action.place_count != 0:
                raise ValueError("空置动作的 picked_count/place_count 必须为 0")
            if action.picked_goods or action.placed_items:
                raise ValueError("空置动作不能包含货物记录")
            continue

        if not 1 <= action.picked_count <= MAX_GRIPPER_COUNT:
            raise ValueError(f"{action.location_code} picked_count 超出夹爪上限")
        if not 0 <= action.place_count <= action.picked_count:
            raise ValueError(f"{action.location_code} place_count 必须在 0 到 picked_count 之间")
        if action.picked_count != len(action.picked_goods):
            raise ValueError(f"{action.location_code} picked_count 必须等于 picked_goods 数量")
        if len(action.placed_items) > 1:
            raise ValueError(f"{action.location_code} 同一夹爪同一批次最多只能放置 1 个货物")
        if len(action.placed_items) > action.place_count:
            raise ValueError(f"{action.location_code} 当前批次 placed_items 数量不能超过 place_count")

def check_command_wave_barrier(plan: OutboundPlan) -> None:
    for batch in plan.batches:
        pick_actions = [
            action
            for station_plan in batch.station_plans
            for action in station_plan.actions
            if action.action_type == "pick"
        ]
        has_new_command = any(action.send_to_plc for action in pick_actions)
        has_continuing_action = any(not action.send_to_plc for action in pick_actions)

        if has_new_command and has_continuing_action:
            raise ValueError(
                f"批次 {batch.batch_no} 在旧夹爪仍连续放货时写入了新的夹爪命令"
            )

def check_location_layer_consistency(plan: OutboundPlan) -> None:
    for action in all_actions(plan):
        if action.action_type == "idle":
            continue
        if action.location_code is None or action.layer is None:
            raise ValueError("取货动作必须有 location_code 和 layer")

        station_code, layer, position = CabinetStore.parse_location(action.location_code)
        expected_position = reachable_position_from_local_gripper(action.local_gripper_id)

        if station_code != action.station_code:
            raise ValueError(f"{action.location_code} 工作站和 action.station_code 不一致")
        if layer != action.layer:
            raise ValueError(f"{action.location_code} 层号和 action.layer 不一致")
        if position != expected_position:
            raise ValueError(f"{action.location_code} 不在夹爪 {action.local_gripper_id} 的固定可达位置")

def check_station_target_line(plan: OutboundPlan) -> None:
    for batch in plan.batches:
        for station_plan in batch.station_plans:
            target_lines = {
                action.target_line
                for action in station_plan.actions
                if action.action_type == "pick" and action.target_line
            }
            if len(target_lines) > 1:
                raise ValueError(f"批次 {batch.batch_no} 工作站 {station_plan.station_code} 出现多条目标线")

def check_sequence_continuous(plan: OutboundPlan) -> None:
    sequences = sorted(
        item.sequence
        for action in all_actions(plan)
        for item in action.placed_items
    )
    if not sequences:
        return

    expected = list(range(1, len(sequences) + 1))
    if sequences != expected:
        raise ValueError(f"全局出库 sequence 不连续，实际 {sequences}，期望 {expected}")

def check_package_segments(plan: OutboundPlan) -> None:
    for segment in plan.package_segments:
        expected_total = segment.sequence_end - segment.sequence_start + 1
        if expected_total != segment.total_goods:
            raise ValueError(f"包裹 {segment.package_id} segment 数量不一致")

def all_actions(plan: OutboundPlan) -> list[GripperAction]:
    return [
        action
        for batch in plan.batches
        for station_plan in batch.station_plans
        for action in station_plan.actions
    ]

# 构建SlotPick
def build_slot_pick(package: Package, slot: SlotInfo, planned_goods: list[str]) -> SlotPick:
    station_code, layer, position = CabinetStore.parse_location(slot.location_code)
    station_id = station_id_from_code(station_code)
    local_gripper_id = gripper_id_from_position(position)

    return SlotPick(
        package_id = package.package_id,
        target_line = normalize_line(package.packaging_line, package.manual_process_type),
        location_code = slot.location_code,
        station_code = station_code,
        station_id = station_id,
        local_gripper_id = local_gripper_id,
        global_gripper_id = global_gripper_id(station_id, local_gripper_id),
        gripper_side = gripper_side(local_gripper_id),
        layer = layer,
        picked_goods = list(slot.goods),
        planned_goods = list(planned_goods),
    )

# 在当前库位，计算当前包裹还能使用哪些货物
def goods_needed_from_slot(
    location_code: str,
    slot_goods: list[str], # 货物sku列表
    need: Counter[str],
) -> list[str]:
    # 这里不能在库位里“跳着拿”SKU。
    # 如果库位是 [A, A, B]，包裹只需要 B，算法必须返回 []，
    # 因为夹爪放货时只能先放最底部/最前面的 A，不能直接放中间或后面的 B。
    available_stack = list(slot_goods)
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
def package_sort_key(info: PackagePlanInfo) -> tuple:
    if info.total_goods == 1:
        return (
            front_clearance_priority(info),
            priority_group(info),
            line_priority(info.target_line),
            0,
            info.package_id,
        )
    return (
        front_clearance_priority(info),
        priority_group(info),
        info.total_goods,
        line_priority(info.target_line),
        info.package_id,
    )

# 前排清障优先级最高：只要包裹当前使用的前排库位挡住了同层后排货物，
# 就必须排在普通单件包裹、跨工作站包裹等业务排序之前。
def front_clearance_priority(info: PackagePlanInfo) -> int:
    return 0 if info.clears_front_blocker else 1

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

def should_keep_package_exclusive(info: PackagePlanInfo) -> bool:
    return info.total_goods > 1 or info.is_cross_station or info.is_multi_slot

# 转换夹爪编号，工作站(1,2) -> 全局(1,2,3,4,5,6)
def global_gripper_id(station_id: int, gripper_id: int) -> int:
    if station_id not in (1, 2, 3):
        raise ValueError(f"未知工作站 ID: {station_id}")
    if gripper_id not in (1, 2):
        raise ValueError(f"未知工作站内部夹爪编号: {gripper_id}")
    return (station_id - 1) * 2 + gripper_id
