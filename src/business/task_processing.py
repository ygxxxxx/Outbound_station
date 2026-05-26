from src.communication.plc_service import PLC_Service
from src.business.state_machine import StateMachine, StationState
from src.business.strategy import strategy
from src.business.task_manager import TaskManager, QueueTask
from src.models.containers import CabinetStore
from src.models.outbound_plan_model import OutboundPlan, OutboundBatch, PackageSegment, StationBatchPlan, GripperAction, PlacedItem

from src.utils.logger import logger

import threading
import time

logger = logger.bind(tag="Task_Processing")

MAX_TASK_RETRY = 3

class Task_Processing:
    def __init__(self,
                 taskmanager: TaskManager = None,
                 plc_service: PLC_Service = None,
                 state_machine: StateMachine = None,
                 cabinet_store: CabinetStore = None
                 ):
        self.taskmanager = taskmanager
        self.plc_service = plc_service
        self.state_machine = state_machine
        self.cabinet_store = cabinet_store

        self._stop_event = threading.Event()
        

    def start(self):
        self._stop_event.clear()
        threading.Thread(target=self._check_pending_loop, daemon=True).start()
        logger.info("开始监听任务队列")

    # 循环查询_pending
    def _check_pending_loop(self) -> None:
        while not self._stop_event.is_set():
            with self.taskmanager.rlock:
                if not self.taskmanager._pending:
                    queuetask = None
                else:
                    queuetask = self.taskmanager._pending[0]

            if queuetask is None:
                self._stop_event.wait(timeout=1.0)
                continue

            try:
                logger.info(f"开始解析任务：{queuetask.task_id}")
                # 解析任务类型
                if queuetask.task_types == "putaway":
                    self._putaway_task_processing(queuetask)

                elif queuetask.task_types == "outbound":
                    self._outbound_task_processing(queuetask)  # 如果是出库任务进出库任务处理函数

            except Exception as e:
                with self.taskmanager.rlock:
                    queuetask.retry_count += 1
                if queuetask.retry_count > MAX_TASK_RETRY:
                    logger.error(f"任务重试超过{MAX_TASK_RETRY}次，从队列移除:{queuetask.task_id}")
                    self.taskmanager.remove_pending(queuetask.task_id)
                else:
                    logger.warning(f"任务解析失败，第{queuetask.retry_count}次: ，留在队列中: {queuetask.task_id}, {e}")
                self._stop_event.wait(timeout=5.0)

    @staticmethod
    def _parse_station_id(station_code: str) -> int:
        mapping = {"A": 1, "B": 2, "C": 3}
        if station_code not in mapping:
            raise ValueError(f"非法工作站编号: {station_code}")
        return mapping[station_code]

    @staticmethod
    def _parse_layer_from_location(storage_location: str) -> int:
        if len(storage_location) >= 2 and storage_location[1].isdigit():
            return int(storage_location[1])
        return 0

    @staticmethod
    def _parse_position_from_location(storage_location: str) -> int:
        if len(storage_location) >= 3 and storage_location[2].isdigit():
            return int(storage_location[2])
        return 0

    def _transition_or_raise(self, station_code: str, target: StationState, reason: str) -> None:
        if not self.state_machine.transition(station_code, target, reason=reason):
            raise RuntimeError(f"工作站{station_code}无法切换到状态{target.value}")

    def _fail_running_task(self, queuetask: QueueTask, station_codes: list[str], error: Exception) -> None:
        error_msg = str(error)
        for station_code in station_codes:
            self.state_machine.transition(station_code, StationState.ERROR, reason=error_msg)
        self.taskmanager.fail_task(queuetask.task_id, error_msg)

    def _build_putaway_placements(
        self,
        queuetask: QueueTask,
        layer_goods_info: dict[int, dict[str, bool]],
    ) -> list[tuple[str, list[str], str]]:
        placements: list[tuple[str, list[str], str]] = []
        planned_qty: dict[str, int] = {}
        back_to_front_map = {"3": "1", "4": "2"}

        for goods in queuetask.task.put_goods:
            if goods.abr_count <= 0:
                continue

            layer = self._parse_layer_from_location(goods.storage_location)
            actual_location = goods.storage_location
            if not layer_goods_info[layer]["front"]:
                actual_position = back_to_front_map[goods.storage_location[2]]
                actual_location = f"{queuetask.task.station_id}{layer}{actual_position}"

            slot = self.cabinet_store.get_slot(actual_location)
            if slot is None:
                raise ValueError(f"落位库位不存在: {actual_location}")

            next_qty = planned_qty.get(actual_location, slot.qty) + len(goods.good_sku)
            if next_qty > 4:
                raise ValueError(
                    f"落位库位容量不足: {actual_location}, 当前{slot.qty}, "
                    f"本次计划放入{next_qty - slot.qty}件"
                )
            planned_qty[actual_location] = next_qty
            placements.append((actual_location, goods.good_sku, goods.storage_location))

        return placements

    # 放货处理
    def _putaway_task_processing(self, queuetask: QueueTask) -> None:
        logger.info(f"开始处理放货任务{queuetask.task_id}")

        station_code = queuetask.task.station_id
        plc_station_id = self._parse_station_id(station_code)

        # layer -> {"front": bool, "back": bool} 记录每层前区(1,2位)和后区(3,4位)是否有货
        layer_goods_info: dict[int, dict[str, bool]] = {}
        for pg in queuetask.task.put_goods:
            if pg.abr_count > 0:
                layer = self._parse_layer_from_location(pg.storage_location)
                position = self._parse_position_from_location(
                    pg.storage_location)
                if (
                    not isinstance(pg.storage_location, str)
                    or len(pg.storage_location) != 3
                    or pg.storage_location[0] != station_code
                    or not (1 <= layer <= 4 and 1 <= position <= 4)
                    or pg.abr_count != len(pg.good_sku)
                ):
                    raise ValueError(f"非法放货数据: {pg.storage_location}")
                if layer not in layer_goods_info:
                    layer_goods_info[layer] = {"front": False, "back": False}
                if position in (1, 2):
                    layer_goods_info[layer]["front"] = True
                elif position in (3, 4):
                    layer_goods_info[layer]["back"] = True

        all_layers = set(range(1, 5))
        goods_layers = set(layer_goods_info.keys())
        empty_layers = all_layers - goods_layers

        # 设备动作开始后，任何异常均终止任务，避免重复出货。
        self.taskmanager.remove_pending(queuetask.task_id)
        self.taskmanager.add_to_running(queuetask)

        try:
            placements = self._build_putaway_placements(queuetask, layer_goods_info)
            self._transition_or_raise(station_code, StationState.WAITING_DELIVERY, "放货任务开始")

            # 无货物的层：下发跳过指令，禁止传送带运行
            for layer in sorted(empty_layers):
                self.plc_service.command_cabinet_no_box(plc_station_id, layer)

            # 所有层都没有货物，直接跳过
            if not goods_layers:
                logger.warning(f"工作站{station_code} 所有层均无货物，直接标记放货完成")
                self._transition_or_raise(station_code, StationState.DELIVERED, "无货物直接完成")
                self.taskmanager.complete_task(queuetask.task_id)
                self.state_machine.transition(station_code, StationState.IDLE, reason="放货任务已释放")
                return

            logger.info(
                f"工作站{station_code} 有货物的层: {sorted(goods_layers)}, 详情: {layer_goods_info}")

            self.plc_service.command_cabinet_place(plc_station_id)

            total_timeout = time.time() + 60
            while not self._stop_event.is_set():
                if self.plc_service.is_emergency_stop():
                    raise RuntimeError(f"工作站{station_code}放货过程中急停触发")

                all_triggered = True
                for layer in sorted(goods_layers):
                    info = layer_goods_info[layer]
                    front = self.plc_service.is_photo_triggered(
                        plc_station_id, layer, "front")
                    need_back = info["front"] and info["back"]
                    if need_back:
                        back = self.plc_service.is_photo_triggered(
                            plc_station_id, layer, "back")
                        if not (front and back):
                            all_triggered = False
                    elif not front:
                        all_triggered = False

                for layer in sorted(goods_layers):
                    if self.plc_service.is_cabinet_timeout(plc_station_id, layer):
                        raise RuntimeError(f"工作站{station_code} {layer}层放货超时")

                if all_triggered:
                    logger.info(f"工作站{station_code} 所有货物层光电判定完成，放货完成")
                    break

                if time.time() > total_timeout:
                    raise TimeoutError(f"工作站{station_code}放货超时")

                self._stop_event.wait(timeout=0.2)

            if self._stop_event.is_set():
                raise RuntimeError("任务处理停止，放货任务中断")

            for actual_location, goods_sku, original_location in placements:
                logger.info(
                    f"写入库位: {actual_location} (原始: {original_location}), "
                    f"SKU: {goods_sku}, 数量: {len(goods_sku)}"
                )
                if not self.cabinet_store.put_goods_to_slot(actual_location, goods_sku):
                    raise RuntimeError(
                        f"库位写入失败: {actual_location}，请人工核对现场库存"
                    )

            self._transition_or_raise(station_code, StationState.DELIVERED, "放货完成")
            self.taskmanager.complete_task(queuetask.task_id)
            self.state_machine.transition(station_code, StationState.IDLE, reason="放货任务已释放")
        except Exception as exc:
            logger.error(f"放货任务执行失败: task_id={queuetask.task_id}, error={exc}")
            self._fail_running_task(queuetask, [station_code], exc)

    def _outbound_task_processing(self, queuetask: QueueTask) -> None:

        # 将任务放入出库策略当中进行计算，得出Outboundplan
        outboundplan = strategy(queuetask, self.cabinet_store)
        self._log_outbound_plan_detail(outboundplan)

        # 将任务从准备队列转移至正在执行中
        self.taskmanager.remove_pending(queuetask.task_id)
        self.taskmanager.add_to_running(queuetask)

        try:
            for station_code in ("A", "B", "C"):
                self._transition_or_raise(station_code, StationState.OUTBOUND, "进行出库任务")
            # 按照Outboundplan计划执行任务
            self._execute_plan(outboundplan)
            for station_code in ("A", "B", "C"):
                self._transition_or_raise(station_code, StationState.DONE, "任务完成")
            self.taskmanager.complete_task(queuetask.task_id)
        except Exception as exc:
            logger.error(f"出库任务执行失败: task_id={queuetask.task_id}, error={exc}")
            self._fail_running_task(queuetask, ["A", "B", "C"], exc)

    def stop(self) -> None:
        self._stop_event.set()
        logger.info("任务处理已停止")

    # 打印策略生成的完整出库计划，便于在执行设备动作前核对算法结果
    def _log_outbound_plan_detail(self, outboundplan: OutboundPlan) -> None:
        logger.info("=" * 80)
        logger.info(
            f"出库详细计划开始: task_id={outboundplan.task_id}, "
            f"task_type={outboundplan.task_type}, "
            f"total_packages={outboundplan.total_packages}, "
            f"total_goods={outboundplan.total_goods}, "
            f"total_batches={len(outboundplan.batches)}"
        )

        for segment in outboundplan.package_segments:
            logger.info(
                f"包裹连续段: package_id={segment.package_id}, "
                f"target_line={segment.target_line}, "
                f"total_goods={segment.total_goods}, "
                f"batches={segment.batch_start}-{segment.batch_end}, "
                f"sequence={segment.sequence_start}-{segment.sequence_end}, "
                f"stations={segment.station_codes}, "
                f"exclusive={segment.exclusive}"
            )

        for batch in outboundplan.batches:
            # 包含新取货动作的批次才会写入六个夹爪的任务/无任务寄存器。
            has_new_plc_command = any(
                action.action_type == "pick" and action.send_to_plc
                for station_plan in batch.station_plans
                for action in station_plan.actions
            )
            logger.info(
                f"计划批次 {batch.batch_no}: target_line={batch.target_line}, "
                f"outbound_count={batch.outbound_count}, "
                f"sequence={batch.sequence_start}-{batch.sequence_end}, "
                f"packages={batch.package_ids}, "
                f"exclusive={batch.exclusive}, "
                f"has_new_plc_command={has_new_plc_command}"
            )

            for station_plan in batch.station_plans:
                for action in station_plan.actions:
                    if action.action_type == "idle":
                        idle_command = (
                            "write_no_task=1"
                            if has_new_plc_command
                            else "no_register_write"
                        )
                        logger.info(
                            f"  工作站 {station_plan.station_code}: "
                            f"G{action.global_gripper_id}"
                            f"(local={action.local_gripper_id}), "
                            f"action=idle, {idle_command}"
                        )
                        continue

                    action_mode = (
                        "send_pick_command"
                        if action.send_to_plc
                        else "continue_place"
                    )
                    placed_items = [
                        (
                            f"{item.goods_sku}/pkg={item.package_id}/"
                            f"seq={item.sequence}/batch={item.place_batch_no}"
                        )
                        for item in action.placed_items
                    ]
                    logger.info(
                        f"  工作站 {action.station_code}: "
                        f"G{action.global_gripper_id}"
                        f"(local={action.local_gripper_id}), "
                        f"action=pick, mode={action_mode}, "
                        f"location={action.location_code}, layer={action.layer}, "
                        f"picked_count={action.picked_count}, "
                        f"picked_goods={action.picked_goods}, "
                        f"place_count={action.place_count}, "
                        f"target_line={action.target_line}, "
                        f"placed_items={placed_items}"
                    )

        logger.info(f"出库详细计划结束: task_id={outboundplan.task_id}")
        logger.info("=" * 80)

    # 接受出库计划并解析执行
    def _execute_plan(self, outboundplan: OutboundPlan) -> None:
        logger.info(
            f"开始执行出库计划: task_id={outboundplan.task_id}, "
            f"total_batches={len(outboundplan.batches)}, "
            f"total_goods={outboundplan.total_goods}"
        )
        return_remaining_after_batches = self._return_remaining_boxes_batch_numbers(outboundplan)

        for batch in outboundplan.batches:
            if self._stop_event.is_set():
                raise RuntimeError("任务处理已停止，出库计划中断")

            # strategy 可能在计划中已将后排货物按补位后的前排库位安排出库。
            # 执行到该批次前，必须先让真实设备完成补位，并同步本地库位库存。
            self._execute_required_front_refill_before_batch(batch)
            self._execute_batch(
                batch,
                return_remaining_boxes=batch.batch_no in return_remaining_after_batches,
            )

        logger.info(f"出库计划执行完成: task_id={outboundplan.task_id}")

    def _return_remaining_boxes_batch_numbers(self, outboundplan: OutboundPlan) -> set[int]:
        return_batches: set[int] = set()
        for batch in outboundplan.batches:
            command_actions = [
                action
                for station_plan in batch.station_plans
                for action in station_plan.actions
                if action.action_type == "pick" and action.send_to_plc
            ]
            if not command_actions:
                continue
            if not any(action.picked_count > action.place_count for action in command_actions):
                continue

            # 同一波次必须等待需要落线次数最多的夹爪完成，才能统一触发回柜。
            wave_duration = max(action.place_count for action in command_actions)
            return_batches.add(batch.batch_no + wave_duration - 1)
        return return_batches

    # 解析出库批次并执行
    def _execute_batch(self, batch: OutboundBatch, return_remaining_boxes: bool = False) -> None:
        placed_count = self._count_batch_placed_items(batch)
        if placed_count != batch.outbound_count:
            raise ValueError(
                f"批次 {batch.batch_no} 出库数量不一致: "
                f"outbound_count={batch.outbound_count}, placed_count={placed_count}"
            )

        # 需要重新写入 PLC 夹爪参数的动作，只能是本轮新开始的取货动作。
        commands = self._build_plc_commands_for_batch(batch)
        has_continuing_action = any(
            action.action_type == "pick" and not action.send_to_plc
            for station_plan in batch.station_plans
            for action in station_plan.actions
        )

        # 旧夹爪还在连续放货时，不能给空闲夹爪写新数据。
        if commands and has_continuing_action:
            raise ValueError(f"批次 {batch.batch_no} 继续放货过程中不能下发新的夹爪命令")

        logger.info(
            f"开始执行批次 {batch.batch_no}: "
            f"outbound_count={batch.outbound_count}, "
            f"commands={len(commands)}, "
            f"packages={batch.package_ids}"
        )

        if batch.outbound_count <= 0:
            logger.info(f"批次 {batch.batch_no} 无落线货物，跳过")
            return

        self.plc_service.clear_outbound_complete()

        if commands:
            self.plc_service.command_gripper_batch(
                commands,
                outbound_count=batch.outbound_count,
            )
        elif has_continuing_action:
            # 当前批次是上一轮夹取后的继续放货，只更新出库数量，不能重写夹爪数据
            self.plc_service.command_outbound_batch_count(batch.outbound_count)
        else:
            raise ValueError(f"批次 {batch.batch_no} 有出库数量但没有可执行夹爪动作")

        self._wait_outbound_batch_complete(batch)
        if return_remaining_boxes:
            self.plc_service.command_return_remaining_boxes()
            logger.info(f"批次 {batch.batch_no} 同步波次落线完成，已触发剩余鞋盒放回收纳柜")
        self._update_cabinet_store_after_batch(batch)

        logger.info(f"批次 {batch.batch_no} 执行完成")

    # 构建下发PLC的夹爪命令
    def _build_plc_commands_for_batch(self, batch: OutboundBatch) -> list[dict]:
        commands = []

        for station_plan in batch.station_plans:
            for action in station_plan.actions:
                if action.action_type != "pick":
                    continue
                if not action.send_to_plc:
                    continue

                if action.layer is None:
                    raise ValueError(f"批次 {batch.batch_no} 夹爪动作缺少 layer")
                if action.size is None:
                    raise ValueError(f"批次 {batch.batch_no} 夹爪动作缺少 size")

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

    # 等待出库完成信号
    def _wait_outbound_batch_complete(self, batch: OutboundBatch, timeout: float = 100.0) -> None:
        deadline = time.time() + timeout

        while not self._stop_event.is_set():
            if self.plc_service.is_emergency_stop():
                raise RuntimeError(f"批次 {batch.batch_no} 执行中触发急停")

            if self.plc_service.read_outbound_complete():
                logger.info(f"批次 {batch.batch_no} PLC 确认出库完成")
                #photo_count = self.plc_service.read_outbound_photo_count()
                #if photo_count != batch.outbound_count:
                    #raise RuntimeError(
                        #f"批次 {batch.batch_no} 光电计数不一致: "
                        #f"expected={batch.outbound_count}, actual={photo_count}"
                    #)
                #logger.info(f"批次 {batch.batch_no} PLC 确认出库完成, 光电计数={photo_count}")
                return

            if time.time() > deadline:
                raise TimeoutError(f"批次 {batch.batch_no} 等待 PLC 出库完成超时")

            self._stop_event.wait(timeout=0.2)

        raise RuntimeError(f"任务停止，批次 {batch.batch_no} 等待出库完成中断")

    # 更新库位
    def _update_cabinet_store_after_batch(self, batch: OutboundBatch) -> None:
        for station_plan in batch.station_plans:
            for action in station_plan.actions:
                if action.action_type != "pick":
                    continue
                if action.location_code is None:
                    continue
                if not action.placed_items:
                    continue

                placed_skus = [item.goods_sku for item in action.placed_items]
                removed_count = self.cabinet_store.remove_goods_batch(
                    action.location_code,
                    placed_skus,
                )

                if removed_count != len(placed_skus):
                    raise RuntimeError(
                        f"批次 {batch.batch_no} 更新库存失败: "
                        f"location={action.location_code}, "
                        f"expected={len(placed_skus)}, removed={removed_count}"
                    )

                logger.info(
                    f"批次 {batch.batch_no} 已更新库位: "
                    f"location={action.location_code}, removed={placed_skus}"
                )
    # 统计批次落线数量

    def _count_batch_placed_items(self, batch: OutboundBatch) -> int:
        return sum(
            len(action.placed_items)
            for station_plan in batch.station_plans
            for action in station_plan.actions
        )

    # 在批次开始前检查：计划中的前排取货是否需要先由后排货物补位得到
    def _execute_required_front_refill_before_batch(self, batch: OutboundBatch) -> None:
        refill_layers: set[tuple[str, int]] = set()

        for station_plan in batch.station_plans:
            for action in station_plan.actions:
                # 同一次夹取的后续连续放置不会再次取库位，也不应触发新的补位动作。
                if action.action_type != "pick" or not action.send_to_plc:
                    continue
                if action.location_code is None:
                    continue

                station_code, layer, position = CabinetStore.parse_location(action.location_code)
                if position not in (1, 2):
                    continue

                current_slot = self.cabinet_store.get_slot(action.location_code)
                if current_slot is None:
                    raise RuntimeError(f"计划使用了不存在的库位: {action.location_code}")

                # 当前前排库存已经和计划夹取内容相同，说明该动作不依赖补位。
                if current_slot.goods == action.picked_goods:
                    continue

                back_location = f"{station_code}{layer}{position + 2}"
                back_slot = self.cabinet_store.get_slot(back_location)
                if back_slot is None or back_slot.goods != action.picked_goods:
                    continue

                front_locations = [f"{station_code}{layer}{front_position}" for front_position in (1, 2)]
                if all(self.cabinet_store.get_slot(location).is_empty for location in front_locations):
                    refill_layers.add((station_code, layer))

        for station_code, layer in sorted(refill_layers):
            self._execute_front_refill(station_code, layer, batch.batch_no)

    # 控制某一层后排货物向前补位，并在设备到位后更新 CabinetStore
    def _execute_front_refill(self, station_code: str, layer: int, batch_no: int) -> None:
        station_id = self._parse_station_id(station_code)
        logger.info(f"批次 {batch_no} 执行前进行库位补位: 工作站={station_code}, layer={layer}")

        self.plc_service.command_cabinet_forward(station_id, layer)
        self._wait_front_refill_complete(station_id, layer, batch_no)

        moved_goods = self.cabinet_store.move_back_goods_to_front(station_code, layer)
        if not moved_goods:
            raise RuntimeError(f"批次 {batch_no} 补位完成但未找到可移动货物: {station_code}{layer}层")

        logger.info(f"批次 {batch_no} 库位补位库存同步完成: {moved_goods}")

    # 等待传送带把后排货物送到前排位置
    def _wait_front_refill_complete(
        self,
        station_id: int,
        layer: int,
        batch_no: int,
        timeout: float = 30.0,
    ) -> None:
        deadline = time.time() + timeout

        while not self._stop_event.is_set():
            if self.plc_service.is_emergency_stop():
                raise RuntimeError(f"批次 {batch_no} 补位过程中触发急停")

            if self.plc_service.is_cabinet_timeout(station_id, layer):
                raise RuntimeError(f"批次 {batch_no} 补位失败: 工作站{station_id} {layer}层传送带超时")

            if self.plc_service.is_photo_triggered(station_id, layer, "front"):
                logger.info(f"批次 {batch_no} 补位完成: 工作站{station_id} {layer}层前光电已触发")
                return

            if time.time() > deadline:
                raise TimeoutError(f"批次 {batch_no} 等待工作站{station_id} {layer}层补位完成超时")

            self._stop_event.wait(timeout=0.2)

        raise RuntimeError(f"任务停止，批次 {batch_no} 等待库位补位中断")
