import time
from typing import Callable, Optional, List, Dict

from src.utils.logger import logger
from src.communication.plc_client import PLC_Client
from src.communication.plc_registers import GripperAddr, CabinetCtrlAddr, StatusAddr, RegisterRange, OutboundAddr
from src.models.plc_data_model import PLCStatusData, GripperState, StationState
from src.exception.exception import ParameterError


logger = logger.bind(tag = 'plc_service')


# PLC服务层 -> PLC寄存器，PLC客户端，PLC数据模型
class PLC_Service:
    def __init__(
        self,
        plc_client: PLC_Client,
        fault_check_callback: Optional[Callable[[], None]] = None,
    ):
        self._plc_client = plc_client
        self._status_data = PLCStatusData()
        self._fault_check_callback = fault_check_callback

    # 返回PLC数据模型
    @property    
    def status(self) -> PLCStatusData:
        return self._status_data

    def set_fault_check_callback(
        self, callback: Optional[Callable[[], None]]
    ) -> None:
        self._fault_check_callback = callback
    
    def start_connects(self) -> None:
        self._plc_client._ensure_connection(max_retries= -1, interval = 3.0, backoff = 1.0)

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
        if self._fault_check_callback:
            self._fault_check_callback()  # 状态已更新，通知状态机检查故障

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
        place_count: int,
        delay_before_pos: float = 0.6,
    ) -> bool:

        if not 1 <= layer <= 4:
            raise ParameterError(message="层号超出范围", expected_value="1~4", actual_value=str(layer))
        if not 1 <= count <= 4:
            raise ParameterError(message="数量超出范围", expected_value="1~4", actual_value=str(count))
        
        count_addr = GripperAddr.count_addr(gripper_id)
        size_addr = GripperAddr.size_addr(gripper_id)
        pos_addr = GripperAddr.pos_addr(gripper_id)
        place_count_addr = GripperAddr.place_count_addr(gripper_id)

        # PLC 每轮会同步处理六个夹爪。即使这里只调试一个夹爪，
        # 也必须明确告诉 PLC 其他夹爪本轮无任务，避免它们按旧参数执行抓取。
        self._write_gripper_no_task_flags({gripper_id})

        # 写入数量和尺寸
        self._plc_client.write_holding_registers(count_addr, [count])
        self._plc_client.write_holding_registers(size_addr, [size])
        self._plc_client.write_holding_registers(place_count_addr, [place_count])
        logger.info(
            f"夹爪{gripper_id}参数寄存器写入: "
            f"D{count_addr}(count)={count}, "
            f"D{size_addr}(size)={size}, "
            f"D{place_count_addr}(place_count)={place_count}"
        )
        logger.info(f"夹爪{gripper_id}: 已写入数量={count}, 尺寸={size},放置货物数量={place_count}")

        if delay_before_pos < 0.5:
            delay_before_pos = 0.5
        time.sleep(delay_before_pos)

        self._plc_client.write_holding_registers(pos_addr, [layer])
        logger.info(
            f"夹爪{gripper_id}触发寄存器写入: D{pos_addr}(position/layer)={layer}"
        )
        logger.info(f"夹爪{gripper_id}: 已写入抓取位置=第{layer}层, 夹爪开始执行")
        return True

    # 下发当前同步波次中六个夹爪的任务状态：有抓取动作写0，无任务写1
    def _write_gripper_no_task_flags(self, active_gripper_ids: set[int]) -> None:
        for gripper_id in range(1, GripperAddr.GRIPPER_COUNT + 1):
            no_task = 0 if gripper_id in active_gripper_ids else 1
            addr = GripperAddr.no_task_addr(gripper_id)
            self._plc_client.write_holding_registers(addr, [no_task])
            logger.info(
                f"夹爪{gripper_id}任务状态寄存器写入: "
                f"D{addr}(no_task)={no_task}"
            )

        idle_gripper_ids = [
            gripper_id
            for gripper_id in range(1, GripperAddr.GRIPPER_COUNT + 1)
            if gripper_id not in active_gripper_ids
        ]
        logger.info(f"当前夹爪同步波次无任务夹爪: {idle_gripper_ids}")

    # 控制多个夹爪
    def command_gripper_batch(self, commands: List[Dict], outbound_count: int = 0, delay_before_pos: float = 0.6) -> bool:
        active_gripper_ids: set[int] = set()

        # 先完成整批参数校验，再向 PLC 写任何寄存器，避免半批命令已经写入后才发现错误。
        for cmd in commands:
            if not 1 <= cmd.get("layer", 0) <= 4:
                raise ParameterError(message="层号超出范围", expected_value="1~4", actual_value=str(cmd.get("layer")))
            if not 1 <= cmd.get("count", 0) <= 4:
                raise ParameterError(message="数量超出范围", expected_value="1~4", actual_value=str(cmd.get("count")))
            if not 0 <= cmd.get("place_count", 0) <= cmd.get("count", 0):
                raise ParameterError(message="放置数量超出范围", expected_value="0~count", actual_value=str(cmd.get("place_count", 0)))

            gid = cmd["gripper_id"]
            GripperAddr._validate_gripper_id(gid)
            if gid in active_gripper_ids:
                raise ParameterError(message="夹爪编号重复", expected_value="同一波次每个夹爪最多一个任务", actual_value=str(gid))
            active_gripper_ids.add(gid)

        # 有动作的夹爪写0，idle 空闲夹爪写1。
        # 这一组标志只在下发新的抓取波次时写；同一次夹取的后续连续放货不会调用本函数。
        self._write_gripper_no_task_flags(active_gripper_ids)

        for cmd in commands:
            gid = cmd["gripper_id"]
            count_addr = GripperAddr.count_addr(gid)
            size_addr = GripperAddr.size_addr(gid)
            place_count_addr = GripperAddr.place_count_addr(gid)
            self._plc_client.write_holding_registers(count_addr, [cmd["count"]])
            self._plc_client.write_holding_registers(size_addr, [cmd["size"]])
            self._plc_client.write_holding_registers(place_count_addr, [cmd["place_count"]])
            logger.info(
                f"夹爪{gid}参数寄存器写入: "
                f"D{count_addr}(count)={cmd['count']}, "
                f"D{size_addr}(size)={cmd['size']}, "
                f"D{place_count_addr}(place_count)={cmd['place_count']}"
            )
        # 本批次出库数量
        if outbound_count > 0:
            self._plc_client.write_holding_registers(OutboundAddr.BATCH_COUNT, [outbound_count])    
            logger.info(
                f"出库批次寄存器写入: D{OutboundAddr.BATCH_COUNT}(outbound_count)={outbound_count}"
            )
        
        if delay_before_pos < 0.5:
            delay_before_pos = 0.5
        time.sleep(delay_before_pos)

        for cmd in commands:
            gid = cmd["gripper_id"]
            pos_addr = GripperAddr.pos_addr(gid)
            self._plc_client.write_holding_registers(pos_addr, [cmd["layer"]])
            logger.info(
                f"夹爪{gid}触发寄存器写入: "
                f"D{pos_addr}(position/layer)={cmd['layer']}"
            )

        logger.info(f"批量下发 {len(commands)} 个夹爪指令")
        return True
    
    # 放货库位传送带全部转动指令
    def command_cabinet_place(self, station_id: int) -> bool:
        addr = CabinetCtrlAddr.place_addr(station_id)
        self._plc_client.write_holding_registers(addr, [1])
        logger.info(f"下发放货库位传送带全部转动指令")
        return True

    # 无货物层跳过传送带运行(写1禁止该层传送带启动，避免触发超时报警)
    def command_cabinet_no_box(self, station_id: int, layer: int) -> bool:
        addr = CabinetCtrlAddr.no_box_addr(station_id, layer)  # 使用新方法
        self._plc_client.write_holding_registers(addr, [1])
        logger.info(f"工作站{station_id} {layer}层: 已下发跳过传送带指令(无货物)")
        return True
    
    # 库位传送带转动指令
    def command_cabinet_forward(self, station_id: int, layer: int) -> bool:
        addr = CabinetCtrlAddr.forward_addr(station_id, layer)
        self._plc_client.write_holding_registers(addr, [1])
        logger.info(f"工作站{station_id} {layer}层: 已下发库位转动指令")
        return True
    
    # 库位传送带后退命令
    def command_cabinet_backward(self, station_id: int, layer: int) -> bool:
        addr = CabinetCtrlAddr.backward_addr(station_id, layer)
        self._plc_client.write_holding_registers(addr, [1])
        logger.info(f"工作站{station_id} {layer}层: 已下库位后退指令")
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

    # 给RCS上报数据
    def get_to_rcs(self) -> dict:
        return self._status_data.to_rcs()
    
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
    
    # 每批次出库鞋盒数量
    def command_outbound_batch_count(self, count: int) -> bool:
        if not 1 <= count <= 6:
            raise ParameterError(message="出库批次数量超出范围", expected_value="1~6", actual_value=str(count))
        self._plc_client.write_holding_registers(OutboundAddr.BATCH_COUNT, [count])
        logger.info(
            f"出库批次寄存器写入: D{OutboundAddr.BATCH_COUNT}(outbound_count)={count}"
        )
        logger.info(f"已下发每批次鞋盒出库数量: {count}")
        return True

    # 阅读出库完成标志
    def read_outbound_complete(self) -> bool:
        result = self._plc_client.read_holding_registers(OutboundAddr.COMPLETE_FLAG, 1)
        return result[0] == 1

    # 清除出库完成标志，每次出库完成后，出库完成标志会置0，在发送下一批出库指令时需要把标志置1
    def clear_outbound_complete(self) -> bool:
        self._plc_client.write_holding_registers(OutboundAddr.COMPLETE_FLAG, [0])
        self._plc_client.write_holding_registers(OutboundAddr.PHOTO_COUNT, [0])
        logger.info("已清除鞋盒出库完成标志，已重置流水线光电计数")
        return True

    # 读取出库流水线计数光电
    def read_outbound_photo_count(self) -> int:
        result = self._plc_client.read_holding_registers(OutboundAddr.PHOTO_COUNT, 1)
        return result[0]
    

if __name__ == "__main__":
    plc = PLC_Client(host = '192.168.1.88', port = 502, slave_id= 1, timeout= 5)
    plc_service = PLC_Service(plc)
    plc_service.start_connects()
    plc_service.start_status_polling(interval=0.3)
    time.sleep(1)

    commands = [
        {"gripper_id": 1, "layer": 1, "count": 2, "size": 1},
        {"gripper_id": 2, "layer": 2, "count": 1, "size": 2},
        {"gripper_id": 3, "layer": 3, "count": 3, "size": 1},
        {"gripper_id": 4, "layer": 1, "count": 4, "size": 2},
        {"gripper_id": 5, "layer": 4, "count": 1, "size": 1},
        {"gripper_id": 6, "layer": 2, "count": 2, "size": 2},
    ]
    plc_service.command_gripper_batch(commands, delay_before_pos= 0.6)

    plc_service.command_cabinet_place(3)
    try:
        while True:
            time.sleep(1)
            print(plc_service.get_full_status())
    except KeyboardInterrupt:
        plc_service.stop_status_polling()
        plc_service.close()
        logger.info("程序已停止")

    
    
