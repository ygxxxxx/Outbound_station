from enum import Enum, unique
from typing import Callable, Optional
import threading
from datetime import datetime

from src.business.task_manager import TaskManager
from src.communication.plc_service import PLC_Service
from src.utils.logger import logger

logger = logger.bind(tag="StateMachine")

_STATION_ID_TO_PLC = {"A": 1, "B": 2, "C": 3}

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


class StateMachine:

    def __init__(
        self,
        host_id: str,
        station_ids: list[str],
        plc_service: PLC_Service,
        task_manager: TaskManager,
    ):

        self._host_id = host_id
        self._station_ids = station_ids
        self._plc_service = plc_service
        self._task_manager = task_manager

        self._states: dict[str, StationState] = {
            sid: StationState.IDLE for sid in station_ids
        }
        self._contexts: dict[str, dict] = {}

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._stop_event.set()
        self._transition_history: dict[str, list[dict]] = {
            sid: [] for sid in station_ids
        }
        self._max_history_per_station = 50
        logger.info(f"[{host_id}] 状态机初始化完成, 工作站: {station_ids}")

    # 切换工作站状态
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
            
            if context is not None:
                self._contexts[station_id] = context

            self._record_transition(station_id, old, target, reason)

            logger.info(
                f"[{self._host_id}] S{station_id} {old.value} -> {target.value}"
                + (f" ({reason})" if reason else "")
            )

        if old in (StationState.DONE, StationState.DELIVERED) and target == StationState.IDLE:
            with self._lock:
                self._contexts.pop(station_id, None)
        
        return True

    # 获得单个工作站状态  
    def get_state(self, station_id: str) -> StationState:
        with self._lock:
            return self._states[station_id]

    # 获得全部工作站状态
    def get_all_states(self) -> dict[str, StationState]:
        with self._lock:
            return dict(self._states)

    # 获得任务信息
    def get_context(self, station_id: str) -> dict | None:
        with self._lock:
            return self._contexts.get(station_id)

    # 判断能不能切换到目标状态
    def can_transition(self, station_id: str, target: StationState) -> bool:
        with self._lock:
            current = self._states[station_id]
            return target in _TRANSITION_TABLE.get(current, set())

    # 判断工作站是否空闲
    def is_idle(self, station_id: str) -> bool:
        with self._lock:
            return self._states[station_id] == StationState.IDLE

    # 判断工作站是否处于error状态
    def is_error(self, station_id: str) -> bool:
        with self._lock:
            return self._states[station_id] == StationState.ERROR

    # 检查PLC故障并更新状态机
    def check_plc_faults(self) -> None:
        if self._plc_service is None:
            return

        if self._plc_service.is_emergency_stop():
            for sid in self._station_ids:
                if not self.is_error(sid):
                    self.transition(sid, StationState.ERROR, reason="急停信号")

        for sid in self._station_ids:
            plc_id = _STATION_ID_TO_PLC[sid]
            faults = self._plc_service.get_station_faults(plc_id)
            if faults and not self.is_error(sid):
                self.transition(sid, StationState.ERROR, reason=f"设备故障: {faults}")

    # 强制重置状态到IDLE
    def force_reset_to_idle(self, station_id: str, reason: str = "强制重置") -> None:
        with self._lock:
            old = self._states[station_id]
            self._states[station_id] = StationState.IDLE
            self._contexts.pop(station_id, None)
            self._record_transition(station_id, old, StationState.IDLE, reason)
        logger.warning(
            f"[{self._host_id}] S{station_id} 强制: {old.value} -> IDLE ({reason})"
    )
        
    # 获得工作站状态
    def get_outbound_station_status(self) -> dict:
        with self._lock:
            station_status = {
                "stationA": self._states["A"].value,
                "stationB": self._states["B"].value,
                "stationC": self._states["C"].value,
            }
            
            return station_status

    # 返回任务状态
    def get_task_execution_detail(self) -> dict:
        with self._lock:
            task_detail = self._task_manager.get_current_task_detail()
            if task_detail is not None:
                return task_detail
            return {
                "task_id": "",
                "task_types": "",
                "status": "idle",
                "total_packages": 0,
                "finish_time": None,
            }
        
    # 返回工作站最近的状态转换历史记录
    def get_transition_history(self, station_id: str, limit: int = 20) -> list[dict]:
        with self._lock:
            history = self._transition_history.get(station_id, [])
            return list(history[-limit:])

    # 记录状态转换历史，保持每个工作站的历史记录不超过设定的最大值
    def _record_transition(
        self,
        station_id: str,
        old: StationState,
        new: StationState,
        reason: str,
    ) -> None:
        record = {
            "time": datetime.now().isoformat(),
            "from": old.value,
            "to": new.value,
            "reason": reason,
        }
        history = self._transition_history[station_id]
        history.append(record)
        if len(history) > self._max_history_per_station:
            history.pop(0)