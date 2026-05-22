from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


# 让这个脚本可以直接用下面的命令运行：
# .\.venv\Scripts\python.exe tests\strategy_process_demo.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


from src.business.strategy import strategy
from src.business.task_manager import QueueTask
from src.models.containers import CabinetStore
from src.models.outbound_plan_model import OutboundBatch, OutboundPlan
from src.models.outbound_task_model import OutboundTask, Package
from src.utils.logger import logger


MAX_SLOT_CAPACITY = 4


@dataclass
class DemoContext:
    store: CabinetStore
    task: OutboundTask
    slot_skus: dict[str, str] = field(default_factory=dict)
    package_sources: dict[str, list[str]] = field(default_factory=dict)


def main() -> None:
    print_title("1. 构造 100 件库存和真实包裹任务")
    context = build_demo_context()
    print_inventory_summary(context.store)
    print_task_summary(context.task)

    print_title("2. 调用 strategy 生成完整 OutboundPlan")
    print("说明：这里出现的“模拟后排补位”日志，是 strategy 在内存里推演完整计划。")
    print("它不是设备已经真实补位；真实设备仍然应该按 OutboundPlan 的批次顺序执行。")
    plan = strategy(QueueTask(context.task), context.store)
    logger.complete()
    print_plan_summary(plan)

    print_title("3. 批次摘要")
    print_batch_summary(plan)

    print_title("4. 关键规则样例")
    print_key_rule_examples(plan, context)

    print_title("5. 普通脚本校验，不使用 pytest")
    run_plain_checks(plan, context)
    print("演示完成：100 件货物完整出库计划已生成，并通过脚本内置检查。")


def build_demo_context() -> DemoContext:
    store = CabinetStore.create()
    context = DemoContext(
        store=store,
        task=OutboundTask(
            task_id="DEMO-STRATEGY-100-GOODS",
            task_types="outbound",
            timestamp="2026-05-22 10:40:00",
            station_id="ALL",
            packages_count=0,
            packages=[],
        ),
    )

    # 25 个库位，每个库位 4 件货，共 100 件。
    # 这些库位覆盖 A/B/C 三个工作站、前排 1/2 位、后排 3/4 位。
    for location_code in [
        "A11", "A12", "B11", "B12", "C11", "C12",
        "A21", "A22", "B21", "B22",
        "A31", "B31", "C21",
        "A32", "B32",
        "A41", "A42",
        "A13", "A14", "A23", "A24",
        "B13", "B14", "C13", "C14",
    ]:
        add_full_slot(context, location_code)

    # 前排 HS1 单件包裹：6 个库位、24 件。
    # 预期：会被合成 4 个批次，每批最多 6 个不同全局夹爪一起出。
    for location_code in ["A11", "A12", "B11", "B12", "C11", "C12"]:
        add_single_packages(context, location_code, line="HS1")

    # 前排 HS2 单件包裹：4 个库位、16 件。
    for location_code in ["A21", "A22", "B21", "B22"]:
        add_single_packages(context, location_code, line="HS2")

    # 跨 A/B/C 三个工作站的多件包裹：4 个包裹、每包 3 件。
    for _ in range(MAX_SLOT_CAPACITY):
        add_package_from_slots(context, ["A31", "B31", "C21"], line="MP1")

    # 普通同库位多件包裹。
    add_same_slot_packages(context, "A32", [2, 2], line="HS1")
    add_same_slot_packages(context, "B32", [2, 2], line="HS1")
    add_same_slot_packages(context, "A41", [4], line="HS1")
    add_same_slot_packages(context, "A42", [4], line="HS1")

    # 后排库位任务：这些包裹开始时无法直接取，必须等同层前排清空后才会在模拟库存中补位。
    add_same_slot_packages(context, "A13", [2, 2], line="HS1")
    add_same_slot_packages(context, "A14", [4], line="HS1")
    add_single_packages(context, "A23", line="HS2")
    add_same_slot_packages(context, "A24", [2, 2], line="HS2")
    add_single_packages(context, "B13", manual_process_type="G")
    add_same_slot_packages(context, "B14", [2, 2], manual_process_type="S")
    add_same_slot_packages(context, "C13", [4], line="MP1")
    add_same_slot_packages(context, "C14", [2, 2], line="HS1")

    context.task.packages_count = len(context.task.packages)
    return context


def add_full_slot(context: DemoContext, location_code: str) -> None:
    sku = f"SKU-{location_code}"
    context.slot_skus[location_code] = sku
    ok = context.store.put_goods_to_slot(location_code, [sku] * MAX_SLOT_CAPACITY)
    if not ok:
        raise RuntimeError(f"初始化库位失败: {location_code}")


def add_single_packages(
    context: DemoContext,
    location_code: str,
    line: str | None = None,
    manual_process_type: str | None = None,
) -> None:
    for _ in range(MAX_SLOT_CAPACITY):
        add_package_from_slots(
            context,
            [location_code],
            line=line,
            manual_process_type=manual_process_type,
        )


def add_same_slot_packages(
    context: DemoContext,
    location_code: str,
    sizes: list[int],
    line: str | None = None,
    manual_process_type: str | None = None,
) -> None:
    for size in sizes:
        sku = context.slot_skus[location_code]
        add_package(
            context,
            goods=[sku] * size,
            source_locations=[location_code],
            line=line,
            manual_process_type=manual_process_type,
        )


def add_package_from_slots(
    context: DemoContext,
    location_codes: list[str],
    line: str | None = None,
    manual_process_type: str | None = None,
) -> None:
    goods = [context.slot_skus[location_code] for location_code in location_codes]
    add_package(
        context,
        goods=goods,
        source_locations=location_codes,
        line=line,
        manual_process_type=manual_process_type,
    )


def add_package(
    context: DemoContext,
    goods: list[str],
    source_locations: list[str],
    line: str | None = None,
    manual_process_type: str | None = None,
) -> None:
    package_id = f"PKG{len(context.task.packages) + 1:03d}"
    package = Package(
        package_id=package_id,
        box_type="BOX-S" if len(goods) == 1 else "BOX-M",
        manual_process_type=manual_process_type,
        packaging_line=line,
        count=len(goods),
        goods=list(goods),
    )
    context.task.packages.append(package)
    context.package_sources[package_id] = list(source_locations)


def print_title(title: str) -> None:
    print()
    print("=" * 88)
    print(title)
    print("=" * 88)


def print_inventory_summary(store: CabinetStore) -> None:
    used_slots = [slot for slot in store.get_all_slots() if slot.goods]
    full_slots = [slot for slot in used_slots if slot.qty == MAX_SLOT_CAPACITY]
    station_counts = Counter(slot.location_code[0] for slot in used_slots)
    back_slots = [slot.location_code for slot in used_slots if slot.location_code[2] in ("3", "4")]

    print(f"库存货物总数: {sum(slot.qty for slot in used_slots)}")
    print(f"非空库位数量: {len(used_slots)}")
    print(f"满格库位数量: {len(full_slots)}")
    print(f"工作站分布: {dict(station_counts)}")
    print(f"后排库位数量: {len(back_slots)}, 后排库位: {back_slots}")
    print("前 12 个非空库位示例:")
    for slot in sorted(used_slots, key=lambda item: item.location_code)[:12]:
        print(f"  {slot.location_code}: qty={slot.qty}, sku={slot.goods[0]}")


def print_task_summary(task: OutboundTask) -> None:
    package_size_counts = Counter(len(package.goods) for package in task.packages)
    line_counts = Counter(package_target_line(package) for package in task.packages)
    goods_count = sum(len(package.goods) for package in task.packages)

    print(f"任务包裹数: {len(task.packages)}")
    print(f"任务货物数: {goods_count}")
    print(f"包裹件数分布: {dict(sorted(package_size_counts.items()))}")
    print(f"目标线分布: {dict(line_counts)}")
    print("前 10 个包裹示例:")
    for package in task.packages[:10]:
        print(
            f"  {package.package_id}: line={package_target_line(package)}, "
            f"count={len(package.goods)}, goods={package.goods}"
        )


def print_plan_summary(plan: OutboundPlan) -> None:
    print(f"task_id={plan.task_id}")
    print(f"task_type={plan.task_type}")
    print(f"total_packages={plan.total_packages}")
    print(f"total_goods={plan.total_goods}")
    print(f"total_batches={len(plan.batches)}")
    print(f"sum(batch.outbound_count)={sum(batch.outbound_count for batch in plan.batches)}")


def print_batch_summary(plan: OutboundPlan) -> None:
    for batch in plan.batches:
        pick_actions = list(all_pick_actions(batch))
        plc_actions = [action for action in pick_actions if action.send_to_plc]
        placed_count = sum(len(action.placed_items) for action in pick_actions)
        line_set = sorted({action.target_line for action in pick_actions if action.target_line})
        package_text = short_list(batch.package_ids, limit=8)
        print(
            f"批次 {batch.batch_no:02d}: "
            f"line={batch.target_line}, "
            f"packages={package_text}, "
            f"pick_actions={len(pick_actions)}, "
            f"plc_commands={len(plc_actions)}, "
            f"outbound_count={batch.outbound_count}, "
            f"placed={placed_count}, "
            f"seq={batch.sequence_start}-{batch.sequence_end}, "
            f"lines={line_set}, "
            f"exclusive={batch.exclusive}"
        )


def print_key_rule_examples(plan: OutboundPlan, context: DemoContext) -> None:
    print("单件包裹合批示例:")
    for batch in plan.batches[:4]:
        print(
            f"  批次 {batch.batch_no}: packages={batch.package_ids}, "
            f"pick_actions={len(list(all_pick_actions(batch)))}, line={batch.target_line}"
        )

    print()
    print("跨工作站多件包裹示例:")
    for segment in plan.package_segments:
        if len(segment.station_codes) > 1:
            print(
                f"  {segment.package_id}: stations={segment.station_codes}, "
                f"batch={segment.batch_start}-{segment.batch_end}, exclusive={segment.exclusive}"
            )
            break

    print()
    print("同库位整库位夹取、分包裹连续放置示例:")
    for package_id in ["PKG045", "PKG046", "PKG047", "PKG048"]:
        actions = find_pick_actions(plan, package_id)
        if not actions:
            continue
        first_action = actions[0]
        print(
            f"  {package_id}: loc={first_action.location_code}, "
            f"picked_count={first_action.picked_count}, "
            f"place_count={first_action.place_count}, "
            f"batches={[action.batch_no for action in actions]}, "
            f"send_to_plc={[action.send_to_plc for action in actions]}"
        )

    print()
    print("后排补位后的取货示例:")
    for package_id, source_locations in context.package_sources.items():
        if not any(is_back_location(location_code) for location_code in source_locations):
            continue
        actions = find_pick_actions(plan, package_id)
        if not actions:
            continue
        print(
            f"  {package_id}: original={source_locations}, "
            f"planned_location={actions[0].location_code}, "
            f"batch={actions[0].batch_no}, line={actions[0].target_line}"
        )
        if package_id.endswith("060"):
            break


def run_plain_checks(plan: OutboundPlan, context: DemoContext) -> None:
    ensure(plan.total_goods == 100, f"计划货物数应该是 100，实际 {plan.total_goods}")
    ensure(plan.total_packages == len(context.task.packages), "计划包裹数和任务包裹数不一致")
    ensure(count_placed_items(plan) == 100, "实际 placed_items 数量必须等于 100")
    ensure_sequences_are_continuous(plan)
    ensure_all_batches_have_valid_shape(plan)
    ensure_single_batches_only_mix_same_line(plan)
    ensure_multi_packages_are_continuous(plan)
    ensure_cross_station_packages_are_exclusive(plan)
    ensure_back_packages_are_shifted_to_front(plan, context)


def ensure_all_batches_have_valid_shape(plan: OutboundPlan) -> None:
    for batch in plan.batches:
        ensure(len(batch.station_plans) == 3, f"批次 {batch.batch_no} 工作站数量不是 3")
        pick_actions = list(all_pick_actions(batch))
        placed_count = sum(len(action.placed_items) for action in pick_actions)
        ensure(
            batch.outbound_count == placed_count,
            f"批次 {batch.batch_no} outbound_count={batch.outbound_count}, 实际 placed={placed_count}",
        )
        ensure(len(pick_actions) <= 6, f"批次 {batch.batch_no} pick 动作超过 6 个")
        used_grippers = [action.global_gripper_id for action in pick_actions]
        ensure(
            len(used_grippers) == len(set(used_grippers)),
            f"批次 {batch.batch_no} 同一个全局夹爪被重复使用",
        )
        for action in pick_actions:
            ensure(action.picked_count <= 4, f"{action.location_code} picked_count 超过 4")
            ensure(len(action.placed_items) <= 1, f"批次 {batch.batch_no} 单夹爪一次放了多个货物")


def ensure_single_batches_only_mix_same_line(plan: OutboundPlan) -> None:
    for batch in plan.batches:
        if batch.exclusive or len(batch.package_ids) <= 1:
            continue
        target_lines = {
            item.target_line
            for action in all_pick_actions(batch)
            for item in action.placed_items
        }
        ensure(len(target_lines) == 1, f"批次 {batch.batch_no} 单件合批混入了多条流水线: {target_lines}")


def ensure_multi_packages_are_continuous(plan: OutboundPlan) -> None:
    goods_by_package = Counter(
        item.package_id
        for batch in plan.batches
        for station_plan in batch.station_plans
        for action in station_plan.actions
        for item in action.placed_items
    )
    for segment in plan.package_segments:
        if goods_by_package[segment.package_id] <= 1:
            continue
        expected_batches = list(range(segment.batch_start, segment.batch_end + 1))
        actual_batches = sorted(
            {
                batch.batch_no
                for batch in plan.batches
                for station_plan in batch.station_plans
                for action in station_plan.actions
                for item in action.placed_items
                if item.package_id == segment.package_id
            }
        )
        ensure(actual_batches == expected_batches, f"{segment.package_id} 批次不连续: {actual_batches}")


def ensure_cross_station_packages_are_exclusive(plan: OutboundPlan) -> None:
    for segment in plan.package_segments:
        if len(segment.station_codes) <= 1:
            continue
        ensure(segment.exclusive is True, f"{segment.package_id} 跨工作站但没有 exclusive")


def ensure_back_packages_are_shifted_to_front(plan: OutboundPlan, context: DemoContext) -> None:
    for package_id, source_locations in context.package_sources.items():
        back_locations = [location_code for location_code in source_locations if is_back_location(location_code)]
        if not back_locations:
            continue
        actions = find_pick_actions(plan, package_id)
        ensure(actions, f"后排包裹 {package_id} 没有生成动作")
        planned_locations = {action.location_code for action in actions}
        expected_locations = {front_location_for_back(location_code) for location_code in back_locations}
        ensure(
            planned_locations <= expected_locations,
            f"{package_id} 后排补位位置不正确: planned={planned_locations}, expected={expected_locations}",
        )


def ensure_sequences_are_continuous(plan: OutboundPlan) -> None:
    sequences = sorted(
        item.sequence
        for batch in plan.batches
        for station_plan in batch.station_plans
        for action in station_plan.actions
        for item in action.placed_items
    )
    ensure(sequences == list(range(1, plan.total_goods + 1)), f"sequence 不连续: {sequences}")


def count_placed_items(plan: OutboundPlan) -> int:
    return sum(
        len(action.placed_items)
        for batch in plan.batches
        for station_plan in batch.station_plans
        for action in station_plan.actions
    )


def find_pick_actions(plan: OutboundPlan, package_id: str):
    result = []
    for batch in plan.batches:
        for station_plan in batch.station_plans:
            for action in station_plan.actions:
                if action.action_type != "pick":
                    continue
                if any(item.package_id == package_id for item in action.placed_items):
                    result.append(action)
    return result


def all_pick_actions(batch: OutboundBatch):
    for station_plan in batch.station_plans:
        for action in station_plan.actions:
            if action.action_type == "pick":
                yield action


def package_target_line(package: Package) -> str:
    if package.manual_process_type == "G":
        return "GIFT"
    if package.manual_process_type == "S":
        return "SOFT"
    return package.packaging_line or ""


def is_back_location(location_code: str) -> bool:
    return location_code[2] in ("3", "4")


def front_location_for_back(location_code: str) -> str:
    position = location_code[2]
    if position == "3":
        return f"{location_code[:2]}1"
    if position == "4":
        return f"{location_code[:2]}2"
    raise ValueError(f"不是后排库位: {location_code}")


def short_list(values: list[str], limit: int) -> str:
    if len(values) <= limit:
        return str(values)
    shown = ", ".join(values[:limit])
    return f"[{shown}, ... +{len(values) - limit}]"


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    main()
