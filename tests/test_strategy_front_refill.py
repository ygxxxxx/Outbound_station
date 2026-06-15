from types import SimpleNamespace

from src.business.strategy import strategy
from src.business.task_manager import QueueTask
from src.business.task_processing import Task_Processing
from src.models.containers import CabinetStore
from src.models.outbound_task_model import OutboundTask, Package


class _IdlePlc:
    def __init__(self):
        self.location_moves: list[tuple[int, int, int]] = []
        self.front_refills: list[tuple[int, int]] = []
        self.front_refill_started = False

    def is_emergency_stop(self) -> bool:
        return False

    def get_gripper_state(self, gripper_id: int):
        return SimpleNamespace(is_running=False)

    def command_location_move(self, gripper_id: int, pick_layer: int, place_layer: int) -> bool:
        self.location_moves.append((gripper_id, pick_layer, place_layer))
        return True

    def command_cabinet_forward(self, station_id: int, layer: int) -> bool:
        self.front_refills.append((station_id, layer))
        self.front_refill_started = True
        return True

    def is_cabinet_timeout(self, station_id: int, layer: int) -> bool:
        return False

    def is_photo_triggered(self, station_id: int, layer: int, side: str) -> bool:
        return side == "front" and self.front_refill_started


def _blocked_back_goods_case() -> tuple[CabinetStore, OutboundTask]:
    store = CabinetStore.create(station_prefixes=["A", "B", "C"])
    store.put_goods_to_slot("A11", ["SKU1"])
    store.put_goods_to_slot("A12", ["SKU2"])
    store.put_goods_to_slot("A13", ["SKU3"])
    store.put_goods_to_slot("A14", ["SKU4"])

    task = OutboundTask(
        task_id="T-front-refill",
        task_types="outbound",
        timestamp="",
        station_id="A",
        packages_count=1,
        packages=[
            Package(
                package_id="P1",
                box_type="BOX",
                packaging_line="HS1",
                count=2,
                goods=["SKU3", "SKU4"],
            )
        ],
    )
    return store, task


def test_strategy_plans_front_refill_after_location_moves():
    store, task = _blocked_back_goods_case()

    plan = strategy(QueueTask(task), store)

    assert len(plan.batches) == 1
    batch = plan.batches[0]
    assert [(move.from_location, move.to_location) for move in batch.before_moves] == [
        ("A11", "A21"),
        ("A12", "A22"),
    ]
    assert [(action.station_code, action.layer, action.moved_goods) for action in batch.before_forwards] == [
        (
            "A",
            1,
            {
                "A13->A11": ["SKU3"],
                "A14->A12": ["SKU4"],
            },
        )
    ]

    pick_locations = [
        action.location_code
        for station_plan in batch.station_plans
        for action in station_plan.actions
        if action.action_type == "pick"
    ]
    assert pick_locations == ["A11", "A12"]


def test_front_refill_pre_actions_update_real_store_before_pick():
    store, task = _blocked_back_goods_case()
    plan = strategy(QueueTask(task), store)
    batch = plan.batches[0]
    plc = _IdlePlc()
    processor = Task_Processing(plc_service=plc, cabinet_store=store)

    processor._execute_batch_before_moves(batch)
    processor._execute_batch_before_forwards(batch)

    assert plc.location_moves == [(1, 1, 2), (2, 1, 2)]
    assert plc.front_refills == [(1, 1)]
    assert store.get_slot("A11").goods == ["SKU3"]
    assert store.get_slot("A12").goods == ["SKU4"]
    assert store.get_slot("A13").goods == []
    assert store.get_slot("A14").goods == []
