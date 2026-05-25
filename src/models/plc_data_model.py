from src.communication.plc_registers import StatusAddr
from src.utils.logger import logger

from dataclasses import dataclass, field
from typing import List, Optional, Dict
from threading import RLock

logger = logger.bind(tag = "plc_data_model")

# 单个夹爪状态
@dataclass
class GripperState:

    is_running: bool = False # True=夹爪运行中, False=夹爪空闲

# 单层库位状态
@dataclass
class CabinetLayerState:

    is_conveyor_running: bool = False # 输送带是否运行中
    front_photo_triggered: bool = False # 前光电是否触发
    back_photo_triggered: bool = False # 后光电是否触发
    is_timeout: bool = False # 库位传送带运行是否超时


# 单台工作站的轴故障异常
@dataclass
class StationFaultState:

    left_stretch_fault: int = 0 # 左伸缩故障码（0=无故障）
    left_lift_fault: int = 0 # 左升降故障码
    right_stretch_fault: int = 0 # 右伸缩故障码
    right_lift_fault: int = 0 # 右升降故障码
 
    # 是否存在轴故障
    @property
    def has_fault(self) -> bool:
        return (
            self.left_stretch_fault > 0
            or self.left_lift_fault > 0
            or self.right_stretch_fault > 0
            or self.right_lift_fault > 0
        )

    # 获取所有故障描述列表
    def get_fault_list(self) -> List[str]:
        
        faults = []
        if self.left_stretch_fault > 0:
            faults.append(f"左伸缩故障(码={self.left_stretch_fault})")
        if self.left_lift_fault > 0:
            faults.append(f"左升降故障(码={self.left_lift_fault})")
        if self.right_stretch_fault > 0:
            faults.append(f"右伸缩故障(码={self.right_stretch_fault})")
        if self.right_lift_fault > 0:
            faults.append(f"右升降故障(码={self.right_lift_fault})")
        return faults

# 单台工作站的完整状态,包含该工作站下所有设备（收纳柜各层、轴）的状态信息
@dataclass
class StationState:

    station_id: int = 0
    layers: List[CabinetLayerState] = field(default_factory=lambda: [CabinetLayerState() for _ in range(4)])
    fault: StationFaultState = field(default_factory = StationFaultState)


# PLC 完整状态数据模型
class PLCStatusData:

    def __init__(self):
        self._lock = RLock()

        self._grippers: List[GripperState] = [GripperState() for _ in range(6)]

        self._stations: Dict[int, StationState] = {
            i: StationState(station_id=i) for i in range(1, 4)
        }

        self._emergency_stop: bool = False

    # 更新单个夹爪的运行状态
    def update_gripper_status(self, gripper_id: int, is_running: bool) -> None:
        
        with self._lock:
            if 1 <= gripper_id <= 6:
                self._grippers[gripper_id - 1].is_running = is_running

    # 更新收纳柜输送带状态
    def update_conveyor_status(self, station_id: int, layer: int, is_running: bool) -> None:
        
        with self._lock:
            if 1 <= station_id <= 3 and 1 <= layer <= 4:
                self._stations[station_id].layers[layer - 1].is_conveyor_running = is_running

    # 更新光电传感器状态
    def update_photo_status(self, station_id: int, layer: int, position: str, triggered: bool) -> None:
        
        with self._lock:
            if 1 <= station_id <= 3 and 1 <= layer <= 4:
                layer_state = self._stations[station_id].layers[layer - 1]
                if position == "front":
                    layer_state.front_photo_triggered = triggered
                else:
                    layer_state.back_photo_triggered = triggered

    # 更新轴故障码
    def update_fault(self, station_id: int, axle: str, fault_code: int) -> None:
        
        with self._lock:
            if 1 <= station_id <= 3:
                fault = self._stations[station_id].fault
                if axle == "left_stretch":
                    fault.left_stretch_fault = fault_code
                elif axle == "left_lift":
                    fault.left_lift_fault = fault_code
                elif axle == "right_stretch":
                    fault.right_stretch_fault = fault_code
                elif axle == "right_lift":
                    fault.right_lift_fault = fault_code

    # 更新急停状态
    def update_emergency_stop(self, active: bool) -> None:
        
        with self._lock:
            self._emergency_stop = active

    # 更新收纳柜超时状态
    def update_timeout_status(self, station_id: int, layer: int, is_timeout: bool) -> None:
        
        with self._lock:
            if 1 <= station_id <= 3 and 1 <= layer <= 4:
                self._stations[station_id].layers[layer - 1].is_timeout = is_timeout

    # 从批量读取的寄存器数据中更新全部状态
    def update_from_registers(self, registers: List[int], start_address: int) -> None:
        
        with self._lock:
            self._parse_gripper_status(registers, start_address)
            self._parse_conveyor_status(registers, start_address)
            self._parse_photo_status(registers, start_address)
            self._parse_fault_status(registers, start_address)
            self._parse_emergency_stop(registers, start_address)
            self._parse_timeout_status(registers, start_address)

    # 解析夹爪状态
    def _parse_gripper_status(self, registers: List[int], start_address: int) -> None:
        base = StatusAddr.GRIPPER_STATUS_START - start_address
        if base < 0 or base + StatusAddr.GRIPPER_STATUS_COUNT > len(registers):
            return
        for i in range(6):
            self._grippers[i].is_running = (registers[base + i] == 1)

    # 解析库位传送带状态
    def _parse_conveyor_status(self, registers: List[int], start_address: int) -> None:
        base = StatusAddr.CONVEYOR_STATUS_START - start_address
        if base < 0 or base + StatusAddr.CONVEYOR_STATUS_COUNT > len(registers):
            return
        for sid in range(1, 4):
            for layer in range(1, 5):
                idx = base + (sid - 1) * 4 + (layer - 1)
                self._stations[sid].layers[layer - 1].is_conveyor_running = (registers[idx] == 1)

    # 解析光电传感器状态
    def _parse_photo_status(self, registers: List[int], start_address: int) -> None:
        base = StatusAddr.PHOTO_START - start_address
        if base < 0 or base + StatusAddr.PHOTO_COUNT > len(registers):
            return
        for sid in range(1, 4):
            for layer in range(1, 5):
                front_idx = base + (sid - 1) * 8 + (layer - 1) * 2
                back_idx = front_idx + 1
                self._stations[sid].layers[layer - 1].front_photo_triggered = (registers[front_idx] == 1)
                self._stations[sid].layers[layer - 1].back_photo_triggered = (registers[back_idx] == 1)

    # 解析轴异常
    def _parse_fault_status(self, registers: List[int], start_address: int) -> None:
        base = StatusAddr.FAULT_START - start_address
        if base < 0 or base + StatusAddr.FAULT_COUNT > len(registers):
            return
        for sid in range(1, 4):
            idx0 = base + (sid - 1) * 4 + 0
            self._stations[sid].fault.left_stretch_fault = registers[idx0]

            idx1 = base + (sid - 1) * 4 + 1
            self._stations[sid].fault.left_lift_fault = registers[idx1]
            
            idx2 = base + (sid - 1) * 4 + 2
            self._stations[sid].fault.right_stretch_fault = registers[idx2]
            
            idx3= base + (sid - 1) * 4 + 3
            self._stations[sid].fault.right_lift_fault = registers[idx3]

    # 解析是否触发急停
    def _parse_emergency_stop(self, registers: List[int], start_address: int) -> None:
        idx = StatusAddr.EMERGENCY_STOP - start_address
        if 0 <= idx < len(registers):
            self._emergency_stop = (registers[idx] == 1)

    # 解析库位传送带是否超时运行
    def _parse_timeout_status(self, registers: List[int], start_address: int) -> None:
        base = StatusAddr.TIMEOUT_START - start_address
        if base < 0 or base + StatusAddr.TIMEOUT_COUNT > len(registers):
            return
        for sid in range(1, 4):
            for layer in range(1, 5):
                idx = base + (sid - 1) * 4 + (layer - 1)
                self._stations[sid].layers[layer - 1].is_timeout = (registers[idx] == 1)


    # 获得夹爪状态
    def get_gripper_state(self, gripper_id: int) -> Optional[GripperState]:
        with self._lock:
            if 1 <= gripper_id <= 6:
                g = self._grippers[gripper_id - 1]
                return GripperState(is_running=g.is_running)
            return None

    # 获得全部夹爪状态
    def get_all_gripper_states(self) -> List[GripperState]:
        with self._lock:
            return [
                GripperState(is_running=g.is_running)
                for g in self._grippers
            ]

    # 获得单个工作站状态
    def get_station_state(self, station_id: int) -> Optional[StationState]:
        with self._lock:
            st = self._stations.get(station_id)
            if st is None:
                return None
            return StationState(
                station_id=st.station_id,
                layers=[
                    CabinetLayerState(
                        is_conveyor_running=l.is_conveyor_running,
                        front_photo_triggered=l.front_photo_triggered,
                        back_photo_triggered=l.back_photo_triggered,
                        is_timeout=l.is_timeout,
                    )
                    for l in st.layers
                ],
                fault=StationFaultState(
                    left_stretch_fault=st.fault.left_stretch_fault,
                    left_lift_fault=st.fault.left_lift_fault,
                    right_stretch_fault=st.fault.right_stretch_fault,
                    right_lift_fault=st.fault.right_lift_fault,
                ),
            )
        
    # 获得全部工作站状态
    def get_all_station_states(self) -> Dict[int, StationState]:
        with self._lock:
            result = {}
            for sid, st in self._stations.items():
                result[sid] = StationState(
                    station_id=st.station_id,
                    layers=[
                        CabinetLayerState(
                            is_conveyor_running=l.is_conveyor_running,
                            front_photo_triggered=l.front_photo_triggered,
                            back_photo_triggered=l.back_photo_triggered,
                            is_timeout=l.is_timeout,
                        )
                        for l in st.layers
                    ],
                    fault=StationFaultState(
                        left_stretch_fault=st.fault.left_stretch_fault,
                        left_lift_fault=st.fault.left_lift_fault,
                        right_stretch_fault=st.fault.right_stretch_fault,
                        right_lift_fault=st.fault.right_lift_fault,
                    ),
                )
            return result

    # 获得急停触发状态
    def is_emergency_stop(self) -> bool:
        with self._lock:
            return self._emergency_stop

    # 获得夹爪是否在运行中
    def is_gripper_running(self, gripper_id: int) -> bool:
        with self._lock:
            if 1 <= gripper_id <= 6:
                return self._grippers[gripper_id - 1].is_running
            return False

    # 获得工作站错误信息
    def get_station_fault(self, station_id: int) -> Optional[StationFaultState]:
        with self._lock:
            st = self._stations.get(station_id)
            if st is None:
                return None
            f = st.fault
            return StationFaultState(
                left_stretch_fault=f.left_stretch_fault,
                left_lift_fault=f.left_lift_fault,
                right_stretch_fault=f.right_stretch_fault,
                right_lift_fault=f.right_lift_fault,
            )

    # 将完整状态导出为字典，用于状态上报
    def to_dict(self) -> dict:
        with self._lock:
            result = {
                "emergency_stop": self._emergency_stop,
                "grippers": [],
                "stations": {},
            }
            for i, g in enumerate(self._grippers, 1):
                result["grippers"].append({
                    "id": i,
                    "running": g.is_running,
                })
            for sid, st in self._stations.items():
                layers_info = []
                for li, layer in enumerate(st.layers, 1):
                    layers_info.append({
                        "layer": li,
                        "conveyor_running": layer.is_conveyor_running,
                        "front_photo": layer.front_photo_triggered,
                        "back_photo": layer.back_photo_triggered,
                        "timeout": layer.is_timeout,
                    })
                result["stations"][str(sid)] = {
                    "layers": layers_info,
                    "faults": st.fault.get_fault_list(),
                }
            return result

    def to_rcs(self) -> dict:
        with self._lock:
            station_letters = {1: "A", 2: "B", 3: "C"}
            station_status_list = []

            for sid in range(1, 4):
                st = self._stations[sid]
                left_gripper_idx = (sid - 1) * 2
                right_gripper_idx = (sid - 1) * 2 + 1
                station_status_list.append({
                    "station_id": station_letters[sid],
                    "left_gripper": self._grippers[left_gripper_idx].is_running,
                    "right_gripper": self._grippers[right_gripper_idx].is_running,
                    "level_1_conveyor_running": st.layers[0].is_conveyor_running,
                    "level_2_conveyor_running": st.layers[1].is_conveyor_running,
                    "level_3_conveyor_running": st.layers[2].is_conveyor_running,
                    "level_4_conveyor_running": st.layers[3].is_conveyor_running,
                    "level_1_conveyor_timeout_warning": st.layers[0].is_timeout,
                    "level_2_conveyor_timeout_warning": st.layers[1].is_timeout,
                    "level_3_conveyor_timeout_warning": st.layers[2].is_timeout,
                    "level_4_conveyor_timeout_warning": st.layers[3].is_timeout,
                    "left_gripper_retract_error": st.fault.left_stretch_fault,
                    "left_gripper_lift_error": st.fault.left_lift_fault,
                    "right_gripper_retract_error": st.fault.right_stretch_fault,
                    "right_gripper_lift_error": st.fault.right_lift_fault,
                })

            return {
                "emergency_stop": self._emergency_stop,
                "stations_status":station_status_list,
            }
