import time
from typing import Optional, List, Dict

from src.utils.logger import logger
from src.communication.plc_client import PLC_Client
from src.communication.plc_registers import GripperAddr, CabinetCtrlAddr, StatusAddr, RegisterRange
from src.models.plc_data_model import PLCStatusData, GripperState, StationState
from src.exception.exception import ParameterError


logger = logger.bind(tag = 'plc_service')


# PLC服务层 -> PLC寄存器，PLC客户端，PLC数据模型
class PLC_Service:
    def __init__(self, plc_client: PLC_Client):
        self._plc_client = plc_client
        self._status_data = PLCStatusData()

    # 返回PLC数据模型
    @property    
    def status(self) -> PLCStatusData:
        return self._status_data
    
    def start_connects(self) -> None:
        self._plc_client.connect_to_plc()

    def close(self) -> None:
        self.stop_status_polling()
        self._plc_client.plc_close()

    # 开始状态轮询
    def start_status_polling(self, interval: float = 0.5) -> None:
        address_map = {
            "status_all": {
                "type": "holding",
                "address": RegisterRange.STATUS_START,
                "count": RegisterRange.STATUS_COUNT,
            }
        }
        self._plc_client.start_polling(address_map = address_map, callback = self._on_poll_data, interval = interval)
        logger.info(f"PLC 状态轮询已启动, 间隔 {interval}s, 地址范围 D100~D166")

    # 轮询回调
    def _on_poll_data(self, data: dict) -> None:
        registers = data.get("status_all")
        if registers is not None:
            self._status_data.update_from_registers(registers, RegisterRange.STATUS_START)  # 更新PLC数据模型

    # 停止状态轮询
    def stop_status_polling(self) -> None:
        self._plc_client.stop_polling()
        logger.info("PLC 状态轮询已停止")

    # 控制单个夹爪
    def command_gripper(
        self,
        gripper_id: int,
        layer: int,
        count: int,
        size: int,
        delay_before_pos: float = 0.6,
    ) -> bool:

        if not 1 <= layer <= 4:
            raise ParameterError(message="层号超出范围", expected_value="1~4", actual_value=str(layer))
        if not 1 <= count <= 4:
            raise ParameterError(message="数量超出范围", expected_value="1~4", actual_value=str(count))
        
        count_addr = GripperAddr.count_addr(gripper_id)
        size_addr = GripperAddr.size_addr(gripper_id)
        pos_addr = GripperAddr.pos_addr(gripper_id)

        # 写入数量和尺寸
        self._plc_client.write_holding_registers(count_addr, [count])
        self._plc_client.write_holding_registers(size_addr, [size])
        logger.info(f"夹爪{gripper_id}: 已写入数量={count}, 尺寸={size}")

        if delay_before_pos < 0.5:
            delay_before_pos = 0.5
        time.sleep(delay_before_pos)

        self._plc_client.write_holding_registers(pos_addr, [layer])
        logger.info(f"夹爪{gripper_id}: 已写入抓取位置=第{layer}层, 夹爪开始执行")
        return True

    # 控制多个夹爪
    def command_gripper_batch(self, commands: List[Dict], delay_before_pos: float = 0.6) -> bool:
        for cmd in commands:
            if not 1 <= cmd.get("layer", 0) <= 4:
                raise ParameterError(message="层号超出范围", expected_value="1~4", actual_value=str(cmd.get("layer")))
            if not 1 <= cmd.get("count", 0) <= 4:
                raise ParameterError(message="数量超出范围", expected_value="1~4", actual_value=str(cmd.get("count")))

            gid = cmd["gripper_id"]
            count_addr = GripperAddr.count_addr(gid)
            size_addr = GripperAddr.size_addr(gid)
            self._plc_client.write_holding_registers(count_addr, [cmd["count"]])
            self._plc_client.write_holding_registers(size_addr, [cmd["size"]])
            
        if delay_before_pos < 0.5:
            delay_before_pos = 0.5
        time.sleep(delay_before_pos)

        for cmd in commands:
            gid = cmd["gripper_id"]
            pos_addr = GripperAddr.pos_addr(gid)
            self._plc_client.write_holding_registers(pos_addr, [cmd["layer"]])

        logger.info(f"批量下发 {len(commands)} 个夹爪指令")
        return True
    
    # 放货库位传送带全部转动指令
    def command_cabinet_place(self, station_id: int) -> bool:
        addr = CabinetCtrlAddr.place_addr(station_id)
        self._plc_client.write_holding_registers(addr, [1])
        logger.info(f"下发放货库位传送带全部转动指令")
        return True
    
    # 库位传送带转动指令
    def command_cabinet_forward(self, station_id: int, layer: int) -> bool:
       
        addr = CabinetCtrlAddr.forward_addr(station_id, layer)
        self._plc_client.write_holding_registers(addr, [1])
        logger.info(f"工作站{station_id} {layer}层: 已下发库位转动指令")
        return True
    
    # 获取指定夹爪的当前状态
    def get_gripper_state(self, gripper_id: int) -> Optional[GripperState]: 
        return self._status_data.get_gripper_state(gripper_id)

    # 获取所有夹爪的当前状态
    def get_all_gripper_states(self) -> List[GripperState]:  
        return self._status_data.get_all_gripper_states()

    # 判断指定夹爪是否在运行中
    def is_gripper_running(self, gripper_id: int) -> bool:  
        return self._status_data.is_gripper_running(gripper_id)

    # 获取指定工作站的完整状态
    def get_station_state(self, station_id: int) -> Optional[StationState]:
        return self._status_data.get_station_state(station_id)

    def get_all_station_state(self) -> Dict[int, StationState]:
        return self._status_data.get_all_station_states()
    
    # 检查急停是否激活
    def is_emergency_stop(self) -> bool:
        return self._status_data.is_emergency_stop()

    # 检查指定层输送带是否运行中
    def is_conveyor_running(self, station_id: int, layer: int) -> bool:
        st = self._status_data.get_station_state(station_id)
        if st and 1 <= layer <= 4:
            return st.layers[layer - 1].is_conveyor_running
        return False

    # 检查指定光电传感器是否触发
    def is_photo_triggered(self, station_id: int, layer: int, position: str) -> bool:
        st = self._status_data.get_station_state(station_id)
        if st and 1 <= layer <= 4:
            if position == "front":
                return st.layers[layer - 1].front_photo_triggered
            else:
                return st.layers[layer - 1].back_photo_triggered
        return False

    # 检查指定层收纳柜是否运行超时
    def is_cabinet_timeout(self, station_id: int, layer: int) -> bool:
        st = self._status_data.get_station_state(station_id)
        if st and 1 <= layer <= 4:
            return st.layers[layer - 1].is_timeout
        return False

    # 获取指定工作站的故障描述列表
    def get_station_faults(self, station_id: int) -> Optional[List[str]]:
        fault = self._status_data.get_station_fault(station_id)
        if fault:
            return fault.get_fault_list()
        return None

    # 获取完整状态字典，用于 RCS 状态上报
    def get_full_status(self) -> dict:
        return self._status_data.to_dict()
    
    # 清除收纳柜运行超时标志
    def clear_cabinet_timeout(self, station_id: int, layer: int) -> bool:
        addr = StatusAddr.timeout_addr(station_id, layer)
        self._plc_client.write_holding_registers(addr, [0])
        logger.info(f"工作站{station_id} {layer}层: 已清除收纳柜超时标志")
        return True

    # 清除指定工作站所有层的超时标志
    def clear_all_cabinet_timeouts(self, station_id: int) -> bool: 
        for layer in range(1, 5):
            self.clear_cabinet_timeout(station_id, layer)
        return True