import threading
import time
from typing import Optional, Dict, Callable, List

from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusServerContext, ModbusDeviceContext, ModbusSequentialDataBlock

from src.communication.plc_registers import GripperAddr, CabinetCtrlAddr, StatusAddr, RegisterRange

from src.utils.logger import logger

logger = logger.bind(tag = "PLCSimulator")

# PLC模拟器
class PLC_Simulator:

    TOTAL_REGISTERS = 200 # 寄存器总数

    GRIPPER_RUN_TIME = 5.0 # 夹爪运行时间5秒
    CABINER_PLACE_TIME = 5.0 # 库位传送带运行5秒
    CABINET_FWD_TIME = 2.0 # 单个库位传送带运行时间
    MONITOR_INTERVAL = 0.2 # 监控线程每0.2秒检查一次寄存器


    def __init__(self, host: str = "127.0.0.1", port: int = 23112) -> None:
        self.host = host
        self.port = port

        hr_block = ModbusSequentialDataBlock(0, [0] * self.TOTAL_REGISTERS) # 创建200个寄存器，初始值为0，地址从0开始
        self._slave_context = ModbusDeviceContext(hr = hr_block) # 把寄存器保存到一共从站设别当中
        self._context = ModbusServerContext(slaves = self._slave_context, single = True) # 服务器上下文，管理所有设备，single = true表示只有一台PLC
        self._stop_event = threading.Event()

        self._monitor_thread: Optional[threading.Thread] = None
        self._server_thread: Optional[threading.Thread] = None

        self._active_simulations: Dict[str, bool] = {}
        self._sim_lock = threading.lock

    # 启动
    def start(self) -> None:
        self._stop_event.clear()
        # 服务端线程
        self._server_thread = threading.Thread(target = self._run_server, name = "plc_sim_server", daemon = True)
        self._server_thread.start()
        # 监控寄存器线程
        self._monitor_thread = threading.Thread(target = self._monitor_loop, name = "plc_sim_monitor", daemon = True)
        self._monitor_thread.start()
        logger.info(f"PLC 模拟器已启动, 监听 {self.host}:{self.port}")


    # 停止
    def stop(self) -> None:
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=3)
        logger.info("PLC模拟器停止运行")

    # 启动服务端
    def _run_server(self) -> None:
        try:
            # 上下文，监听端口
            StartTcpServer(context = self._context, address = (self.host, self.post))
        except Exception as e:
            logger.error(f"Modbus server 异常： {e}")

    # 读单个寄存器
    def _read_rag(self, address: int) -> int:
        return self._slave_context.getValues(3, address, count = 1)[0]

    # 读多个寄存器
    def _read_regs(self, address, count: int) -> List:
        return self._slave_context.getValues(3, address, count=count)
    
    # 写单个寄存器
    def _write_reg(self, address: int, value: int) -> None:
        self._slave_context.setValues(3, address, [value])

    # 写多个寄存器
    def _write_regs(self, address: int, values: list) -> None:
        self._slave_context.setValues(3, address, values)

    # 循环监控寄存器
    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._check_gripper_commands()
                self._check_cabinet_commands()
            except Exception as e:
                logger(f"监控异常{e}")

            self._stop_event.wait(self.MONITOR_INTERVAL)

    # 检测夹爪寄存器
    def _check_gripper_commands(self) -> None:
        for gid in range(1, GripperAddr.GRIPPER_COUNT + 1):
            pos_addr = GripperAddr.pos_addr(gid)
            pos_val = self._read_rag(pos_addr)

            if pos_val > 0:
                sim_key = f"gripper_{gid}"
            
                with self._sim_lock:
                    if self._active_simulations.get(sim_key):
                        continue
                    self._active_simulations[sim_key] = True

                count_val = self._read_reg(GripperAddr.count_addr(gid))
                size_val = self._read_rag(GripperAddr.size_addr(gid))
                logger.info(f"[模拟] 夹爪{gid} 收到抓取指令: "f"层={pos_val}, 数量={count_val}, 尺寸={size_val}")
                t = threading.Thread(target = self._simulate_gripper, args = (gid, pos_val), daemon = True)
                t.start()

    # 检测库位传送带寄存器
    def _check_cabinet_commands(self) -> None:
        for sid in range(1, CabinetCtrlAddr.STATION_COUNT + 1):
            place_addr = CabinetCtrlAddr(sid)
            place_val = self._read_rag(place_addr)

            if place_val > 0:
                sim_key = f"cabinet_place_{sid}"
                
                with self._sim_lock:
                    if self._active_simulations.get(sim_key):
                        continue
                    self._active_simulations[sim_key] = True

                logger.info(f"[模拟] 工作站{sid} 收到收纳柜放货指令")

                t = threading.Thread(target = self._simulate_cabinet_place, args = (sid), daemon = True)
                t.start()
            for layer in range(1, CabinetCtrlAddr.REGISTERS_PER_STATION + 1):
                fwd_addr = CabinetCtrlAddr.forward_addr(sid, layer)
                fwd_val = self._read_rag(fwd_addr)

                if fwd_val > 0:
                    sim_key = f"cabinet_fwd_{sid}_{layer}"
                    with self._sim_lock:
                        if self._active_simulations.get(sim_key):
                            continue
                        self._active_simulations[sim_key] = True

                    logger.info(f"[模拟] 工作站{sid} {layer}层 收到库位前进指令")

                    t = threading.Thread(target = self._simulate_cabinet_forward, args = (sid, layer), daemon = True,)
                    t.start()

    # 模拟夹爪寄存器运行
    def _simulate_gripper(self, gripper_id: int, layer: int) -> None:
        sim_key = f"gripper_{gripper_id}"
        try:
            status_addr = StatusAddr.gripper_status_addr(gripper_id)
            self._write_reg(status_addr, 1)
            logger.info(f"[模拟] 夹爪{gripper_id} 开始运行 (层={layer})")

            time.sleep(self.GRIPPER_RUN_TIME)
            self._write_reg(status_addr, 0)

            logger.info(f"[模拟] 夹爪{gripper_id} 运行完成")

            self._write_reg(GripperAddr.pos_addr(gripper_id), 0)
            self._write_reg(GripperAddr.count_addr(gripper_id), 0)
            self._write_reg(GripperAddr.size_addr(gripper_id), 0)

        finally:
            with self._sim_lock:
                self._active_simulations.pop(sim_key, None)

    # 模拟放货工作站全部库位传送带运行
    def _simulate_cabinet_place(self, station_id: int) -> None:
        sim_key = f"cabinet_place_{station_id}"
        try:
            for layer in range(1, 5):
                addr = StatusAddr.conveyor_status_addr(station_id, layer)
                self._write_reg(addr, 1)
                logger.info(f"[模拟] 工作站{station_id} 所有层输送带开始运行")

            time.sleep(self.CABINET_PLACE_TIME)

            for layer in range(1, 5):
                front_addr = StatusAddr.photo_addr(station_id, layer, "front")
                back_addr = StatusAddr.photo_addr(station_id, layer, "back")
                self._write_reg(front_addr, 1)
                self._write_reg(back_addr, 1)

            for layer in range(1, 5):
                addr = StatusAddr.conveyor_status_addr(station_id, layer)
                self._write_reg(addr, 0)

            time.sleep(10)
            for layer in range(1, 5):
                front_addr = StatusAddr.photo_addr(station_id, layer, "front")
                back_addr = StatusAddr.photo_addr(station_id, layer, "back")
                self._write_reg(front_addr, 0)
                self._write_reg(back_addr, 0)

 
            place_addr = CabinetCtrlAddr.place_addr(station_id)
            self._write_reg(place_addr, 0)

            logger.debug(f"[模拟] 工作站{station_id} 放货完成")

        finally:
            with self._sim_lock:
                self._active_simulations.pop(sim_key, None)

    # 模拟单个库位传输带寄存器运行
    def _simulate_cabinet_forward(self, station_id: int, layer: int) -> None:
        sim_key = f"cabinet_fwd_{station_id}_{layer}"
        try:
            conv_addr = StatusAddr.conveyor_status_addr(station_id, layer)
            self._write_reg(conv_addr, 1)
            logger.debug(f"[模拟] 工作站{station_id} {layer}层 输送带开始运行")

            time.sleep(self.CABINET_FWD_TIME)

            front_addr = StatusAddr.photo_addr(station_id, layer, "front")
            back_addr = StatusAddr.photo_addr(station_id, layer, "back")
            self._write_reg(front_addr, 1)
            self._write_reg(back_addr, 1)

            self._write_reg(conv_addr, 0)

            time.sleep(10)
            self._write_reg(front_addr, 0)
            self._write_reg(back_addr, 0)

            fwd_addr = CabinetCtrlAddr.forward_addr(station_id, layer)
            self._write_reg(fwd_addr, 0)

            logger.debug(f"[模拟] 工作站{station_id} {layer}层 前进完成")

        finally:
            with self._sim_lock:
                self._active_simulations.pop(sim_key, None)

    # 模拟急停按钮被按下
    def simulate_emergency_stop(self) -> None:
        self._write_reg(StatusAddr.EMERGENCY_STOP, 1)  
        logger.error("[模拟] 急停报警已触发")
    
    # 解除急停
    def clear_emergency_stop(self) -> None:
        self._write_reg(StatusAddr.EMERGENCY_STOP, 0)
        logger.info("[模拟] 急停报警已清除")

    