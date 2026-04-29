from enum import Enum, unique
from typing import Callable, Optional
import threading
from datetime import datetime

from src.communication.rcs_client import RCSClient
from src.communication.plc_client import PLCClient
from src.communication.rcs_protocol import build_message
from src.utils.logger import logger

logger = logger.bind(tag="StateMachine")


@unique
class StationState(Enum):
    IDLE = "IDLE"
    READY = "READY"
    OUTBOUND = "OUTBOUND"
    DONE = "DONE"
    ERROR = "ERROR"
    WAITING_DELIVERY = "WAITING_DELIVERY"
    DELIVERED = "DELIVERED"


_TRANSITION_TABLE: dict[StationState, set[StationState]] = {
    StationState.IDLE:               {StationState.READY, StationState.ERROR},
    StationState.READY:              {StationState.WAITING_DELIVERY, StationState.OUTBOUND, StationState.ERROR},
    StationState.WAITING_DELIVERY:   {StationState.DELIVERED, StationState.ERROR},
    StationState.DELIVERED:          {StationState.IDLE, StationState.ERROR},
    StationState.OUTBOUND:           {StationState.DONE, StationState.ERROR},
    StationState.DONE:               {StationState.IDLE, StationState.ERROR},
    StationState.ERROR:              {StationState.IDLE},
}

class Trigger:
    TASK_ASSIGNED    = "TASK_ASSIGNED"
    ACTION_START     = "ACTION_START"
    ALL_ACTIONS_DONE = "ALL_ACTIONS_DONE"
    RESET            = "RESET"
    ALARM            = "ALARM"

TransitionCallback = Callable[[int, StationState, StationState], None]


class StateMachine:

    def __init__(
        self,
        host_id: str,
        station_ids: list[int],
        plc_client: PLCClient,
        rcs_client: RCSClient,
        on_transition: Optional[TransitionCallback] = None,
    ):

        self._host_id = host_id
        self._station_ids = station_ids
        self._plc_client = plc_client
        self._rcs_client = rcs_client
        self._on_transition = on_transition

        self._states: dict[int, StationState] = {
            sid: StationState.IDLE for sid in station_ids
        }
        self._contexts: dict[int, dict] = {}
        self._empty_slots: dict[int, list[str]] = {
            sid: [] for sid in station_ids
        }
        self._completed_goods: dict[int, int] = {
            sid: 0 for sid in station_ids
        }
        self._completed_packages: dict[int, list[str]] = {
            sid: [] for sid in station_ids
        }

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._stop_event.set()

        logger.info(f"[{host_id}] 状态机初始化完成, 工作站: {station_ids}")

    # 获得工作站状态
    def get_state(self, station_id: int) -> StationState:
        with self._lock:
            return self._states[station_id]

    # 获得全部工作站状态
    def get_all_states(self) -> dict[int, StationState]:
        with self._lock:
            return dict(self._states)

    # 获得工作站任务
    def get_context(self, station_id: int) -> dict | None:
        with self._lock:
            return self._contexts.get(station_id)

    # 查询当前的状态能否跳转目标状态
    def can_transition(self, station_id: int, target: StationState) -> bool:
        with self._lock:
            current = self._states[station_id]
            return target in _TRANSITION_TABLE.get(current, set())



    def transition(
        self,
        station_id: int,
        target: StationState,
        reason: str = "",
        context: dict = None,
    ) -> bool:

        if station_id not in self._states:
            logger.error(f"[{self._host_id}] 未知工作站: {station_id}")
            return False

        with self._lock:
            current = self._states[station_id]
            allowed = _TRANSITION_TABLE.get(current, set())
            if target not in allowed:
                logger.warning(
                    f"[{self._host_id}] S{station_id} 非法转换: "
                    f"{current.value} -> {target.value}"
                )
                return False

            old = current
            self._states[station_id] = target
            logger.info(
                f"[{self._host_id}] S{station_id} {old.value} -> {target.value}"
                + (f" ({reason})" if reason else "")
            )

            if context is not None:
                self._contexts[station_id] = context

        trigger = self._derive_trigger(reason, old, target)
        self._send_state_change(station_id, old, target, trigger)

        if old == StationState.DONE and target == StationState.IDLE:
            self._send_task_complete(station_id)
            self._send_container(station_id)
            with self._lock:
                self._contexts.pop(station_id, None)
                self._completed_goods[station_id] = 0
                self._completed_packages[station_id] = []

        elif old == StationState.DELIVERED and target == StationState.IDLE:
            self._send_task_complete(station_id)
            with self._lock:
                self._contexts.pop(station_id, None)
                self._completed_goods[station_id] = 0
                self._completed_packages[station_id] = []

        if self._on_transition:
            try:
                self._on_transition(station_id, old, target)
            except Exception as e:
                logger.error(f"[{self._host_id}] S{station_id} 回调异常: {e}")

        return True

    # 返回trigger（可能可以不需要）
    def _derive_trigger(self, reason: str, old: StationState, new: StationState) -> str:

        r = reason.lower()
        if any(k in r for k in ("急停", "故障", "异常", "err")):
            return Trigger.ALARM
        if any(k in r for k in ("人工", "恢复", "重置", "reset")):
            return Trigger.RESET
        if old == StationState.IDLE and new == StationState.READY:
            return Trigger.TASK_ASSIGNED
        if new == StationState.DONE:
            return Trigger.ALL_ACTIONS_DONE
        if new == StationState.IDLE:
            return Trigger.ALL_ACTIONS_DONE
        return Trigger.ACTION_START

    # 强制重置状态到IDLE
    def force_reset_to_idle(self, station_id: int) -> None:
        with self._lock:
            old = self._states[station_id]
            self._states[station_id] = StationState.IDLE
            self._contexts.pop(station_id, None)
            self._empty_slots[station_id] = []
            self._completed_goods[station_id] = 0
            self._completed_packages[station_id] = []
            logger.warning(
                f"[{self._host_id}] S{station_id} 强制: {old.value} -> IDLE"
            )

        self._send_state_change(station_id, old, StationState.IDLE, Trigger.RESET)


    # 启动状态机
    def start(self) -> None:
       
        if not self._stop_event.is_set():
            return
        self._stop_event.clear()

        address_map = self._build_address_map()
        self._plc_client.start_polling(
            address_map=address_map,
            callback=self._on_plc_data,
            interval=1.0,
        )
        logger.info(f"[{self._host_id}] PLC 轮询已启动, 工作站: {self._station_ids}")

    # 停止状态机
    def stop(self) -> None:

        if self._stop_event.is_set():
            return
        self._stop_event.set()
        self._plc_client.stop_polling()
        logger.info(f"[{self._host_id}] PLC 轮询已停止")

    # 构建工作站PLC地址映射表
    def _build_address_map(self) -> dict:
        """
        构建整合所有工作站的 PLC 地址映射表。

        一台 PLC 控制所有工作站的夹爪和传送带，地址映射中包含每个工作站的信号。
        key 命名建议：{station_id}_{signal_name}，与 _on_plc_data 中的解析对应。

        TODO: 根据实际 PLC 寄存器地址配置填写。
        返回示例：
        {
            "1_abr_delivery_done":   {"type": "coils",    "address": 0,  "count": 1},
            "1_gripper_action_done": {"type": "coils",    "address": 1,  "count": 1},
            "2_abr_delivery_done":   {"type": "coils",    "address": 2,  "count": 1},
            "2_gripper_action_done": {"type": "coils",    "address": 3,  "count": 1},
            "emergency_stop":        {"type": "discrete", "address": 10, "count": 1},
            ...
        }
        """
        return {}

    # PLC轮询
    def _on_plc_data(self, data: dict) -> None:
        
        # 全局急停信号，一旦触发所有工作站进入 ERROR
        if data.get("emergency_stop"):
            for sid in self._station_ids:
                with self._lock:
                    state = self._states[sid]
                if state != StationState.ERROR:
                    self.transition(sid, StationState.ERROR, reason="急停信号")

        # 按工作站分别处理
        for sid in self._station_ids:
            self._process_station_plc_data(sid, data)

    # 处理单个工作站的 PLC 信号
    def _process_station_plc_data(self, station_id: int, data: dict) -> None:
        with self._lock:
            state = self._states[station_id]

        # 解析该工作站的信号，key 格式为 "{station_id}_{signal_name}"
        prefix = f"{station_id}_"

        if state == StationState.OUTBOUND:
            if data.get(f"{prefix}gripper_action_done"):
                if self._is_outbound_complete(station_id):
                    self.transition(station_id, StationState.DONE, reason="出库完成")

    # 出库完成判断
    def _is_outbound_complete(self, station_id: int) -> bool:
        return False

    # 设置库位为空位
    def set_empty_slots(self, station_id: int, empty_slots: list[str]) -> None:
        
        with self._lock:
            if station_id in self._empty_slots:
                self._empty_slots[station_id] = empty_slots
                logger.debug(
                    f"[{self._host_id}] S{station_id} 空位更新: {empty_slots}"
                )

    def _sender(self) -> str:
        return self._host_id

    # 上报状态变更
    def _send_state_change(
        self, station_id: int, old: StationState, new: StationState, trigger: str
    ) -> None:
        ctx = self._contexts.get(station_id, {})
        try:
            msg = build_message("STATE_CHANGE", self._sender(), "RCS", {
                "station_id": station_id,
                "task_id": ctx.get("task_id", ""),
                "previous_state": old.value,
                "current_state": new.value,
                "trigger": trigger,
            })
            self._rcs_client.send_data(msg)
            logger.debug(
                f"[{self._host_id}] S{station_id} STATE_CHANGE: {old.value} -> {new.value}"
            )
        except Exception as e:
            logger.error(f"[{self._host_id}] S{station_id} STATE_CHANGE 失败: {e}")

    # 发送任务完成通知
    def _send_task_complete(self, station_id: int) -> None:
        ctx = self._contexts.get(station_id, {})
        try:
            msg = build_message("TASK_COMPLETE", self._sender(), "RCS", {
                "task_id": ctx.get("task_id", ""),
                "task_types": ctx.get("task_type", "OUTBOUND"),
                "status": "COMPLETED",
                "completed_goods": self._get_completed_goods_count(station_id),
                "total_goods": ctx.get("total_goods", 0),
                "completed_packages": self._get_completed_package_ids(station_id),
                "finish_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            self._rcs_client.send_data(msg)
            logger.info(
                f"[{self._host_id}] S{station_id} TASK_COMPLETE task={ctx.get('task_id')}"
            )
        except Exception as e:
            logger.error(f"[{self._host_id}] S{station_id} TASK_COMPLETE 失败: {e}")

    # 发送任务执行进度
    def send_task_progress(self, station_id: int) -> None:
        ctx = self._contexts.get(station_id, {})
        try:
            msg = build_message("TASK_PROGRESS", self._sender(), "RCS", {
                "task_id": ctx.get("task_id", ""),
                "status": "EXECUTING",
                "completed_goods": self._get_completed_goods_count(station_id),
                "total_goods": ctx.get("total_goods", 0),
                "completed_packages": self._get_completed_package_ids(station_id),
            })
            self._rcs_client.send_data(msg)
            logger.debug(f"[{self._host_id}] S{station_id} TASK_PROGRESS")
        except Exception as e:
            logger.error(f"[{self._host_id}] S{station_id} TASK_PROGRESS 失败: {e}")

    # 发送货位数据
    def _send_container(self, station_id: int) -> None:

        try:
            containers = self._get_cabinet_slot_data(station_id)
            occupied = sum(1 for s in containers if s.get("status") == "OCCUPIED")
            empty = len(self._empty_slots.get(station_id, []))
            total = occupied + empty

            msg = build_message("CONTAINER", self._sender(), "RCS", {
                "station_id": station_id,
                "containers": containers,
                "total_slots": total,
                "occupied_slots": occupied,
                "empty_slots": empty,
            })
            self._rcs_client.send_data(msg)
            logger.info(
                f"[{self._host_id}] S{station_id} CONTAINER: 占用{occupied}/空闲{empty}/{total}"
            )
        except Exception as e:
            logger.error(f"[{self._host_id}] S{station_id} CONTAINER 失败: {e}")

    # 上报警告
    def report_error(
        self,
        station_id: int,
        alarm_type: str,
        description: str,
        level: str = "ERROR",
        device: str = "",
    ) -> None:
        
        ctx = self._contexts.get(station_id, {})
        try:
            msg = build_message("ALARM", self._sender(), "RCS", {
                "alarm_id": f"ALM{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "level": level,
                "device": device or f"工作站{station_id}",
                "alarm_type": alarm_type,
                "task_id": ctx.get("task_id", ""),
                "station_id": station_id,
            })
            self._rcs_client.send_data(msg)
            logger.warning(
                f"[{self._host_id}] S{station_id} ALARM: {alarm_type} - {description}"
            )
        except Exception as e:
            logger.error(f"[{self._host_id}] S{station_id} ALARM 失败: {e}")

    # 上报设备状态（不确定需不需要，并且需要获取状态函数还没写）
    def _send_device_status(self) -> None:
        
        stations = []
        for sid in self._station_ids:
            stations.append({
                "station_id": sid,
                "grippers": [
                    {"gripper_id": 1, "status": "IDLE"},
                    {"gripper_id": 2, "status": "IDLE"},
                ],
                "conveyor": "RUNNING",
                "scanner_online": True,
            })
        try:
            msg = build_message("DEVICE_STATUS", self._sender(), "RCS", {
                "stations": stations,
            })
            self._rcs_client.send_data(msg)
            logger.debug(f"[{self._host_id}] DEVICE_STATUS")
        except Exception as e:
            logger.error(f"[{self._host_id}] DEVICE_STATUS 失败: {e}")


    # 定时上报所有工作站状态+收纳柜+设备状态
    def report_all_status(self) -> None:
        for sid in self._station_ids:
            with self._lock:
                current = self._states[sid]
            self._send_state_change(sid, current, current, Trigger.ACTION_START)
            self._send_container(sid)
        self._send_device_status()

    def mark_package_complete(self, station_id: int, package_id: str) -> None:
        with self._lock:
            if package_id not in self._completed_packages[station_id]:
                self._completed_packages[station_id].append(package_id)

    def add_completed_goods(self, station_id: int, count: int) -> None:
        with self._lock:
            self._completed_goods[station_id] += count

    def _get_completed_goods_count(self, station_id: int) -> int:
        with self._lock:
            return self._completed_goods[station_id]

    def _get_completed_package_ids(self, station_id: int) -> list:
        with self._lock:
            return list(self._completed_packages[station_id])

    # def _get_cabinet_slot_data(self, station_id: int) -> list:


 