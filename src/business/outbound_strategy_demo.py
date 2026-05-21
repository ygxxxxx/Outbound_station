from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.models.containers import CabinetStore, SlotInfo

if TYPE_CHECKING:
    from src.business.task_manager import QueueTask
    from src.models.outbound_task_model import Package


STATION_CODES = ["A", "B", "C"]
LOCAL_GRIPPER_IDS = [1, 2]
MAX_GRIPPER_COUNT = 4


# 这个示范文件的定位：
# 1. 它是完整的出库策略算法示例，不是最终生产代码。
# 2. 它把模型、内部结构、生成步骤、校验步骤都放在一个文件里，方便对照文档阅读。
# 3. 后续正式实现时，建议把模型放到 models，把展开/排序/批次/校验拆成独立模块。
# 4. 这个示范文件仍使用保守的 reserved_locations，避免同一库位跨包裹复用。
#    正式实现应按综合文档改成 reserved_depth，以支持同一库位剩余货物继续服务后续包裹。


@dataclass
class PlacedItem:
    sequence: int
    place_batch_no: int
    goods_sku: str
    package_id: str
    target_line: str


@dataclass
class GripperAction:
    action_type: str
    station_id: int
    station_code: str
    gripper_id: int
    global_gripper_id: int
    gripper_side: str
    layer: int | None
    location_code: str | None
    picked_count: int
    place_count: int
    size: int | None
    batch_no: int
    target_line: str | None = None
    send_to_plc: bool = False
    picked_goods: list[str] = field(default_factory=list)
    placed_items: list[PlacedItem] = field(default_factory=list)
    reason: str = ""


@dataclass
class StationBatchPlan:
    station_id: int
    station_code: str
    target_line: str | None
    actions: list[GripperAction] = field(default_factory=list)


@dataclass
class OutboundBatch:
    batch_no: int
    target_line: str | None
    exclusive: bool
    exclusive_package_id: str | None
    package_ids: list[str]
    reason: str
    station_plans: list[StationBatchPlan] = field(default_factory=list)
    sequence_start: int | None = None
    sequence_end: int | None = None


@dataclass
class PackageSegment:
    package_id: str
    target_line: str
    total_goods: int
    batch_start: int
    batch_end: int
    sequence_start: int
    sequence_end: int
    station_codes: list[str]
    exclusive: bool
    reason: str = ""


@dataclass
class OutboundPlan:
    task_id: str
    task_type: str
    total_packages: int
    total_goods: int
    batches: list[OutboundBatch] = field(default_factory=list)
    package_segments: list[PackageSegment] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class SlotPick:
    package_id: str
    target_line: str
    location_code: str
    station_code: str
    station_id: int
    gripper_id: int
    global_gripper_id: int
    gripper_side: str
    layer: int
    picked_goods: list[str]
    planned_goods: list[str]

    @property
    def picked_count(self) -> int:
        return len(self.picked_goods)

    @property
    def place_count(self) -> int:
        return len(self.planned_goods)


@dataclass
class PackagePlanInfo:
    package: "Package"
    package_id: str
    target_line: str
    total_goods: int
    slot_picks: list[SlotPick]
    station_codes: list[str]
    is_cross_station: bool
    is_multi_slot: bool
    warnings: list[str] = field(default_factory=list)


def strategy(queuetask: "QueueTask", cabinet_store: CabinetStore) -> OutboundPlan:
    """根据 QueueTask 和当前库位库存生成出库计划。

    这份示范实现刻意写得比较直白，核心目标是把文档中的规则变成可读代码。
    正式生产代码可以继续拆分、优化和补充更多异常处理。
    """

    task = queuetask.task
    warnings: list[str] = []

    package_infos = build_package_infos(task.packages, cabinet_store, warnings)
    package_infos.sort(key=package_sort_key)

    batches: list[OutboundBatch] = []
    sequence = 1
    batch_no = 1

    for info in package_infos:
        new_batches, sequence, batch_no = build_batches_for_package(
            info=info,
            start_batch_no=batch_no,
            start_sequence=sequence,
        )
        batches.extend(new_batches)

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


def build_package_infos(
    packages: list["Package"],
    cabinet_store: CabinetStore,
    warnings: list[str],
) -> list[PackagePlanInfo]:
    """把包裹需求转换成策略更容易处理的 PackagePlanInfo。

    这个阶段只做计划预占，不扣减真实库存。
    """

    reserved_locations: set[str] = set()
    infos: list[PackagePlanInfo] = []

    for package in packages:
        package_warnings: list[str] = []
        target_line = package.packaging_line or ""
        slot_picks = choose_slots_for_package(
            package=package,
            target_line=target_line,
            cabinet_store=cabinet_store,
            reserved_locations=reserved_locations,
            warnings=package_warnings,
        )

        station_codes = sorted({slot_pick.station_code for slot_pick in slot_picks})
        info = PackagePlanInfo(
            package=package,
            package_id=package.package_id,
            target_line=target_line,
            total_goods=len(package.goods),
            slot_picks=slot_picks,
            station_codes=station_codes,
            is_cross_station=len(station_codes) > 1,
            is_multi_slot=len(slot_picks) > 1,
            warnings=package_warnings,
        )
        warnings.extend(package_warnings)
        infos.append(info)

    return infos


def choose_slots_for_package(
    package: "Package",
    target_line: str,
    cabinet_store: CabinetStore,
    reserved_locations: set[str],
    warnings: list[str],
) -> list[SlotPick]:
    """为一个包裹选择要取的库位。

    硬件要求：夹爪一次必须夹起库位上全部货物。
    所以这里的选择单位不是单个 SKU，而是整个 SlotInfo。
    """

    need = Counter(package.goods)
    selected: list[SlotPick] = []

    candidate_slots = sorted(cabinet_store.get_all_slots(), key=lambda slot: location_sort_key(slot.location_code))

    for slot in candidate_slots:
        if not need:
            break
        if slot.location_code in reserved_locations:
            continue
        if slot.is_empty:
            continue
        if slot.qty > MAX_GRIPPER_COUNT:
            warnings.append(f"库位 {slot.location_code} 货物数量超过夹爪上限，已跳过")
            continue

        planned_goods = goods_needed_from_slot(slot.goods, need)
        if not planned_goods:
            continue

        slot_pick = build_slot_pick(
            package=package,
            target_line=target_line,
            slot=slot,
            planned_goods=planned_goods,
        )
        selected.append(slot_pick)
        reserved_locations.add(slot.location_code)

        for sku in planned_goods:
            need[sku] -= 1
            if need[sku] <= 0:
                del need[sku]

        held_but_not_placed = slot.goods[len(planned_goods) :]
        if held_but_not_placed:
            warnings.append(
                f"包裹 {package.package_id} 选择库位 {slot.location_code} 时会夹起但暂不放置 {held_but_not_placed}，"
                f"示范算法只把底部连续可放置货物写入 placed_items"
            )

    if need:
        raise ValueError(f"包裹 {package.package_id} 库存不足，缺少 {dict(need)}")

    return selected


def goods_needed_from_slot(slot_goods: list[str], need: Counter[str]) -> list[str]:
    """返回这个库位中当前包裹需要的那些货物。

    注意：这不是 picked_goods。
    picked_goods 必须是整个库位的全部货物，也就是 list(slot.goods)。
    slot_goods 约定为从最底下到最上方排列，算法不能跳过中间货物。
    """

    local_need = need.copy()
    planned_goods: list[str] = []

    for sku in slot_goods:
        if local_need.get(sku, 0) <= 0:
            break
        planned_goods.append(sku)
        local_need[sku] -= 1
        if local_need[sku] <= 0:
            del local_need[sku]

    return planned_goods


def build_slot_pick(
    package: "Package",
    target_line: str,
    slot: SlotInfo,
    planned_goods: list[str],
) -> SlotPick:
    station_code, layer, position = CabinetStore.parse_location(slot.location_code)
    station_id = station_id_from_code(station_code)
    gripper_id = gripper_id_from_position(position)

    return SlotPick(
        package_id=package.package_id,
        target_line=target_line,
        location_code=slot.location_code,
        station_code=station_code,
        station_id=station_id,
        gripper_id=gripper_id,
        global_gripper_id=global_gripper_id(station_id, gripper_id),
        gripper_side=gripper_side(gripper_id),
        layer=layer,
        picked_goods=list(slot.goods),
        planned_goods=list(planned_goods),
    )


def build_batches_for_package(
    info: PackagePlanInfo,
    start_batch_no: int,
    start_sequence: int,
) -> tuple[list[OutboundBatch], int, int]:
    """为单个包裹生成连续批次。

    示范算法采用最容易理解的保守策略：一个包裹生成一段连续批次。
    如果这个包裹需要超过 6 件，或者跨工作站/多库位，则标记为独占段。
    """

    exclusive = need_exclusive(info)
    reason = exclusive_reason(info) if exclusive else "普通包裹连续出库"

    active_commands = create_gripper_commands(
        info=info,
        start_batch_no=start_batch_no,
        start_sequence=start_sequence,
    )
    last_place_batch = max(
        (
            item.place_batch_no
            for action in active_commands
            for item in action.placed_items
        ),
        default=start_batch_no,
    )
    batch_count = max(1, last_place_batch - start_batch_no + 1)

    batches: list[OutboundBatch] = []

    for offset in range(batch_count):
        batch_no = start_batch_no + offset
        batch = empty_batch(
            batch_no=batch_no,
            target_line=info.target_line,
            exclusive=exclusive,
            exclusive_package_id=info.package_id if exclusive else None,
            package_ids=[info.package_id],
            reason=reason,
        )
        attach_actions_to_batch(batch, active_commands, batch_no)
        fill_idle_actions(batch)
        update_batch_sequence_range(batch)
        batches.append(batch)

    next_sequence = start_sequence + info.total_goods
    next_batch_no = start_batch_no + batch_count
    return batches, next_sequence, next_batch_no


def create_gripper_commands(
    info: PackagePlanInfo,
    start_batch_no: int,
    start_sequence: int,
) -> list[GripperAction]:
    """把 SlotPick 转成一次 PLC 夹爪命令。

    一个 GripperAction 只在 start_batch_no 发出一次夹爪命令。
    如果 place_count > 1，表示这个夹爪后续连续多个批次各放 1 个。
    """

    commands: list[GripperAction] = []
    gripper_next_batch: dict[int, int] = defaultdict(lambda: start_batch_no)

    for slot_pick in info.slot_picks:
        command_batch_no = gripper_next_batch[slot_pick.global_gripper_id]
        place_goods = slot_pick.picked_goods[: slot_pick.place_count]
        if place_goods != slot_pick.planned_goods:
            raise ValueError(f"库位 {slot_pick.location_code} planned_goods 必须是底部连续可放置货物")

        placed_items: list[PlacedItem] = []
        for index, sku in enumerate(place_goods):
            placed_items.append(
                PlacedItem(
                    sequence=0,
                    place_batch_no=command_batch_no + index,
                    goods_sku=sku,
                    package_id=info.package_id,
                    target_line=info.target_line,
                )
            )
        gripper_next_batch[slot_pick.global_gripper_id] = command_batch_no + slot_pick.place_count

        action = GripperAction(
            action_type="pick",
            station_id=slot_pick.station_id,
            station_code=slot_pick.station_code,
            gripper_id=slot_pick.gripper_id,
            global_gripper_id=slot_pick.global_gripper_id,
            gripper_side=slot_pick.gripper_side,
            layer=slot_pick.layer,
            location_code=slot_pick.location_code,
            picked_count=slot_pick.picked_count,
            place_count=len(place_goods),
            size=1,
            batch_no=command_batch_no,
            target_line=info.target_line,
            send_to_plc=True,
            picked_goods=list(slot_pick.picked_goods),
            placed_items=placed_items,
            reason="按库位整格夹取，按 place_count 连续批次放置",
        )
        commands.append(action)

    placement_order = [
        (item.place_batch_no, action.station_id, action.gripper_id, item)
        for action in commands
        for item in action.placed_items
    ]
    placement_order.sort(key=lambda value: (value[0], value[1], value[2]))

    sequence = start_sequence
    for _, _, _, item in placement_order:
        item.sequence = sequence
        sequence += 1

    return commands


def empty_batch(
    batch_no: int,
    target_line: str | None,
    exclusive: bool,
    exclusive_package_id: str | None,
    package_ids: list[str],
    reason: str,
) -> OutboundBatch:
    station_plans = [
        StationBatchPlan(
            station_id=station_id_from_code(station_code),
            station_code=station_code,
            target_line=None,
            actions=[],
        )
        for station_code in STATION_CODES
    ]
    return OutboundBatch(
        batch_no=batch_no,
        target_line=target_line,
        exclusive=exclusive,
        exclusive_package_id=exclusive_package_id,
        package_ids=package_ids,
        reason=reason,
        station_plans=station_plans,
    )


def attach_actions_to_batch(
    batch: OutboundBatch,
    commands: list[GripperAction],
    batch_no: int,
) -> None:
    """把一次夹取命令映射到它参与的每个批次。

    start_batch 的动作是实际 PLC 命令。
    后续批次中复制出的动作表示这个夹爪继续放置 1 个货物。
    """

    for command in commands:
        placed_items = [
            item
            for item in command.placed_items
            if item.place_batch_no == batch_no
        ]
        if not placed_items:
            continue

        action = clone_action_for_batch(command, batch_no, placed_items)
        station_plan = batch.station_plans[action.station_id - 1]
        station_plan.actions.append(action)
        station_plan.target_line = action.target_line


def clone_action_for_batch(
    command: GripperAction,
    batch_no: int,
    placed_items: list[PlacedItem],
) -> GripperAction:
    """生成某个批次视角下的夹爪动作。

    第一批保留原始 picked_count 和 place_count，方便执行层下发 PLC。
    后续批次是持续放置视角，不应该重复下发夹取命令。
    """

    if batch_no == command.batch_no:
        picked_count = command.picked_count
        place_count = command.place_count
        picked_goods = list(command.picked_goods)
        reason = command.reason
        send_to_plc = True
    else:
        picked_count = command.picked_count
        place_count = command.place_count
        picked_goods = list(command.picked_goods)
        reason = "同一次夹取后的连续批次放置记录，不代表重复夹取"
        send_to_plc = False

    return GripperAction(
        action_type="pick",
        station_id=command.station_id,
        station_code=command.station_code,
        gripper_id=command.gripper_id,
        global_gripper_id=command.global_gripper_id,
        gripper_side=command.gripper_side,
        layer=command.layer,
        location_code=command.location_code,
        picked_count=picked_count,
        place_count=place_count,
        size=command.size,
        batch_no=batch_no,
        target_line=command.target_line,
        send_to_plc=send_to_plc,
        picked_goods=picked_goods,
        placed_items=placed_items,
        reason=reason,
    )


def fill_idle_actions(batch: OutboundBatch) -> None:
    """每个批次必须补齐 3 个工作站、每站 2 个夹爪槽位。"""

    for station_plan in batch.station_plans:
        used_grippers = {action.gripper_id for action in station_plan.actions}
        for gripper_id in LOCAL_GRIPPER_IDS:
            if gripper_id in used_grippers:
                continue
            station_plan.actions.append(
                idle_action(
                    batch_no=batch.batch_no,
                    station_id=station_plan.station_id,
                    station_code=station_plan.station_code,
                    gripper_id=gripper_id,
                )
            )
        station_plan.actions.sort(key=lambda action: action.gripper_id)


def idle_action(
    batch_no: int,
    station_id: int,
    station_code: str,
    gripper_id: int,
) -> GripperAction:
    return GripperAction(
        action_type="idle",
        station_id=station_id,
        station_code=station_code,
        gripper_id=gripper_id,
        global_gripper_id=global_gripper_id(station_id, gripper_id),
        gripper_side=gripper_side(gripper_id),
        layer=None,
        location_code=None,
        picked_count=0,
        place_count=0,
        size=None,
        batch_no=batch_no,
        target_line=None,
        send_to_plc=False,
        picked_goods=[],
        placed_items=[],
        reason="本批次该夹爪空置",
    )


def update_batch_sequence_range(batch: OutboundBatch) -> None:
    sequences = [
        item.sequence
        for station_plan in batch.station_plans
        for action in station_plan.actions
        for item in action.placed_items
    ]
    if not sequences:
        batch.sequence_start = None
        batch.sequence_end = None
        return
    batch.sequence_start = min(sequences)
    batch.sequence_end = max(sequences)


def build_package_segments(
    package_infos: list[PackagePlanInfo],
    batches: list[OutboundBatch],
) -> list[PackageSegment]:
    package_to_items: dict[str, list[PlacedItem]] = defaultdict(list)
    package_to_batches: dict[str, set[int]] = defaultdict(set)

    for batch in batches:
        for station_plan in batch.station_plans:
            for action in station_plan.actions:
                for item in action.placed_items:
                    package_to_items[item.package_id].append(item)
                    package_to_batches[item.package_id].add(batch.batch_no)

    info_by_id = {info.package_id: info for info in package_infos}
    segments: list[PackageSegment] = []

    for package_id, items in package_to_items.items():
        info = info_by_id[package_id]
        sequences = sorted(item.sequence for item in items)
        batch_numbers = sorted(package_to_batches[package_id])
        segments.append(
            PackageSegment(
                package_id=package_id,
                target_line=info.target_line,
                total_goods=len(items),
                batch_start=batch_numbers[0],
                batch_end=batch_numbers[-1],
                sequence_start=sequences[0],
                sequence_end=sequences[-1],
                station_codes=list(info.station_codes),
                exclusive=need_exclusive(info),
                reason=exclusive_reason(info) if need_exclusive(info) else "普通包裹连续段",
            )
        )

    segments.sort(key=lambda segment: segment.sequence_start)
    return segments


def validate_plan(plan: OutboundPlan, cabinet_store: CabinetStore) -> None:
    check_batch_shape(plan)
    check_station_target_line(plan)
    check_action_counts(plan, cabinet_store)
    check_location_layer_consistency(plan)
    check_sequence_continuous(plan)
    check_package_segments(plan)


def check_batch_shape(plan: OutboundPlan) -> None:
    for batch in plan.batches:
        if len(batch.station_plans) != len(STATION_CODES):
            raise ValueError(f"批次 {batch.batch_no} 工作站数量不正确")
        for station_plan in batch.station_plans:
            if len(station_plan.actions) != len(LOCAL_GRIPPER_IDS):
                raise ValueError(f"批次 {batch.batch_no} 工作站 {station_plan.station_code} 夹爪数量不正确")


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


def check_action_counts(plan: OutboundPlan, cabinet_store: CabinetStore) -> None:
    checked_command_locations: set[str] = set()

    for action in all_actions(plan):
        if action.action_type == "idle":
            if action.picked_count != 0 or action.place_count != 0:
                raise ValueError("空置动作的 picked_count/place_count 必须为 0")
            continue

        if not 1 <= action.picked_count <= MAX_GRIPPER_COUNT:
            raise ValueError(f"{action.location_code} picked_count 超出夹爪上限")
        if not 0 <= action.place_count <= action.picked_count:
            raise ValueError(f"{action.location_code} place_count 必须在 0 到 picked_count 之间")
        if action.picked_count != len(action.picked_goods):
            raise ValueError(f"{action.location_code} picked_count 必须等于 picked_goods 数量")

        placed_goods = [item.goods_sku for item in action.placed_items]
        if placed_goods != action.picked_goods[: action.place_count]:
            raise ValueError(f"{action.location_code} 放置货物必须是夹持堆叠底部连续段")

        if action.send_to_plc:
            if action.location_code and action.location_code not in checked_command_locations:
                slot = cabinet_store.get_slot(action.location_code)
                if slot is None:
                    raise ValueError(f"库位不存在: {action.location_code}")
                if action.picked_count != slot.qty:
                    raise ValueError(f"动作 {action.location_code} 的 picked_count 必须等于库位全部货物数量")
                checked_command_locations.add(action.location_code)


def check_location_layer_consistency(plan: OutboundPlan) -> None:
    for action in all_actions(plan):
        if action.action_type == "idle":
            continue
        if action.location_code is None or action.layer is None:
            raise ValueError("取货动作必须有 location_code 和 layer")

        station_code, layer, position = CabinetStore.parse_location(action.location_code)
        expected_position = reachable_position_from_gripper(action.gripper_id)

        if station_code != action.station_code:
            raise ValueError(f"{action.location_code} 工作站和 action.station_code 不一致")
        if layer != action.layer:
            raise ValueError(f"{action.location_code} 层号和 action.layer 不一致")
        if position != expected_position:
            raise ValueError(f"{action.location_code} 不在夹爪 {action.gripper_id} 的固定可达位置")


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
            raise ValueError(f"包裹 {segment.package_id} sequence 范围和 total_goods 不一致")


def all_actions(plan: OutboundPlan) -> list[GripperAction]:
    return [
        action
        for batch in plan.batches
        for station_plan in batch.station_plans
        for action in station_plan.actions
    ]


def build_plc_commands_for_batch(batch: OutboundBatch) -> list[dict]:
    """把某一批需要下发 PLC 的夹爪命令转换成字典。

    location_code 不会传给 PLC。
    PLC 需要的是 gripper_id、layer、count、size、place_count。
    """

    commands: list[dict] = []
    for station_plan in batch.station_plans:
        for action in station_plan.actions:
            if action.action_type != "pick":
                continue
            if not action.send_to_plc:
                continue
            commands.append(
                {
                    "gripper_id": action.global_gripper_id,
                    "layer": action.layer,
                    "count": action.picked_count,
                    "size": action.size,
                    "place_count": action.place_count,
                }
            )
    return commands


def need_exclusive(info: PackagePlanInfo) -> bool:
    return info.total_goods > 6 or info.is_cross_station or info.is_multi_slot


def exclusive_reason(info: PackagePlanInfo) -> str:
    reasons: list[str] = []
    if info.total_goods > 6:
        reasons.append("包裹货物数量大于 6")
    if info.is_cross_station:
        reasons.append("包裹跨工作站")
    if info.is_multi_slot:
        reasons.append("包裹涉及多个库位")
    return "、".join(reasons) or "无需独占"


def package_sort_key(info: PackagePlanInfo) -> tuple:
    return (
        priority_group(info),
        line_priority(info.target_line),
        -info.total_goods,
        info.package_id,
    )


def priority_group(info: PackagePlanInfo) -> int:
    if info.is_cross_station:
        return 0
    if info.total_goods > 1:
        return 1
    return 2


def line_priority(target_line: str) -> int:
    priorities = {
        "高速线1": 0,
        "高速线2": 1,
        "赠品区": 2,
        "软包区": 2,
    }
    return priorities.get(target_line or "", 9)


def location_sort_key(location_code: str) -> tuple[str, int, int]:
    station_code, layer, position = CabinetStore.parse_location(location_code)
    return station_code, layer, position


def station_id_from_code(station_code: str) -> int:
    return ord(station_code) - ord("A") + 1


def global_gripper_id(station_id: int, gripper_id: int) -> int:
    return (station_id - 1) * 2 + gripper_id


def gripper_id_from_position(position: int) -> int:
    if position == 1:
        return 1
    if position == 2:
        return 2
    raise ValueError(f"位置 {position} 不属于当前示范算法允许的近侧可达库位")


def reachable_position_from_gripper(gripper_id: int) -> int:
    if gripper_id == 1:
        return 1
    if gripper_id == 2:
        return 2
    raise ValueError(f"未知夹爪编号: {gripper_id}")


def gripper_side(gripper_id: int) -> str:
    if gripper_id == 1:
        return "left"
    if gripper_id == 2:
        return "right"
    raise ValueError(f"未知夹爪编号: {gripper_id}")
