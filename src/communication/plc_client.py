from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException as ME

from src.utils.logger import logger
from src.exception.exception import PLCCommunicationError

import threading
import time
logger = logger.bind(tag = "PLCClient")

class PLC_Client:

    def __init__(self, host, port, slave_id=1, timeout=5):
        self.host = host
        self.port = port

        self.slave_id = slave_id

        self._lock = threading.Lock()

        self.timeout = timeout

        self._client = ModbusTcpClient(host=self.host, port=self.port, timeout=self.timeout, retries=3)

        self._stop_event = threading.Event()

        # 轮询线程对象
        self._poll_thread = None
        self._poll_interval = 1.0
        self._poll_callback = None
        self._address_map = None

    # 连接PLC
    def connect_to_plc(self) -> None:
        if self._client.connected:
            logger.warning(f"PLC已连接,无需重复连接: {self.host}:{self.port}")
            return
        try:
            self._client.connect()
            if not self._client.connected:
                logger.error(f"PLC连接失败: {self.host}:{self.port}")
                raise PLCCommunicationError(
                    message=f"PLC连接失败: {self.host}:{self.port}",
                    device_name=f"PLC[{self.host}:{self.port}]"
                )
            logger.info(f"连接PLC{self.host}:{self.port}")
        except PLCCommunicationError:
            raise
        except Exception as e:
            logger.error(f"PLC连接失败: {self.host}:{self.port}, 错误: {e}")
            raise PLCCommunicationError(
                message=f"PLC连接失败: {e}",
                device_name=f"PLC[{self.host}:{self.port}]"
            )
    
    # 重试连接
    def _ensure_connection(self, max_retries: int = 3, interval: float = 1.0, backoff: float = 1.0) -> None:
        if self._client.connected:
            return
        retry_count = 0
        current_interval = interval
        while True:
            try:
                self._client.connect()
                if self._client.connected:
                    logger.info(f"PLC已连接: {self.host}:{self.port}" +
                               (f" (重试{retry_count}次)" if retry_count > 0 else ""))
                    return
            except Exception as e:
                logger.debug(f"连接异常: {e}")

            retry_count += 1
            if max_retries > 0 and retry_count >= max_retries:
                raise PLCCommunicationError(
                    message=f"PLC连接失败, 已达最大重试次数{max_retries}: {self.host}:{self.port}",
                    device_name=f"PLC[{self.host}:{self.port}]"
                )

            logger.warning(
                f"PLC未连接, {current_interval:.1f}秒后重试 "
                f"({retry_count}/{max_retries if max_retries > 0 else '∞'}): "
                f"{self.host}:{self.port}"
            )
            time.sleep(current_interval)
            current_interval *= backoff

        
    # 断开PLC连接
    def plc_close(self) -> None:
        if self._client.connected:
            self.stop_polling()
            self._client.close()
            logger.info(f"PLC连接已关闭: {self.host}:{self.port}")

    # 读取多个保持寄存器
    def read_holding_registers(self, address, count, slave=None) -> list:
        _slave = slave if slave is not None else self.slave_id
        with self._lock:
            self._ensure_connection()
            try:
                result = self._client.read_holding_registers(address, count=count, device_id=_slave)
                if result.isError():
                    logger.error(f"读取保持寄存器失败: {result}")
                    raise PLCCommunicationError(
                        message=f"读取保持寄存器失败: {result}",
                        device_name=f"PLC[{self.host}:{self.port}]"
                    )
                return result.registers
            except ME as e:
                logger.error(f"读取保持寄存器异常: {e}")
                raise PLCCommunicationError(
                    message=f"读取保持寄存器异常: {e}",
                    device_name=f"PLC[{self.host}:{self.port}]"
                )
            
    # 写入多个保持寄存器
    def write_holding_registers(self, address, values, slave=None) -> bool:
        _slave = slave if slave is not None else self.slave_id
        with self._lock:
            self._ensure_connection()
            try:
                result = self._client.write_registers(address, values, device_id=_slave)
                if result.isError():
                    logger.error(f"写入保持寄存器失败: {result}")
                    raise PLCCommunicationError(
                        message=f"写入保持寄存器失败: {result}",
                        device_name=f"PLC[{self.host}:{self.port}]"
                    )
                return True
            except ME as e:
                logger.error(f"写入保持寄存器异常: {e}")
                raise PLCCommunicationError(
                    message=f"写入保持寄存器异常: {e}",
                    device_name=f"PLC[{self.host}:{self.port}]"
                )

    # 读取多个输入寄存器
    def read_input_registers(self, address, count, slave=None) -> list:
        _slave = slave if slave is not None else self.slave_id
        with self._lock:
            self._ensure_connection()
            try:
                result = self._client.read_input_registers(address, count=count, device_id=_slave)
                if result.isError():
                    logger.error(f"读取输入寄存器失败: {result}")
                    raise PLCCommunicationError(
                        message=f"读取输入寄存器失败: {result}",
                        device_name=f"PLC[{self.host}:{self.port}]"
                    )
                return result.registers
            except ME as e:
                logger.error(f"读取输入寄存器异常: {e}")
                raise PLCCommunicationError(
                    message=f"读取输入寄存器异常: {e}",
                    device_name=f"PLC[{self.host}:{self.port}]"
                )
    
    # 读取多个线圈状态
    def read_coils(self, address, count, slave=None) -> list:
        _slave = slave if slave is not None else self.slave_id
        with self._lock:
            self._ensure_connection()
            try:
                result = self._client.read_coils(address, count=count, device_id=_slave)
                if result.isError():
                    logger.error(f"读取线圈失败: {result}")
                    raise PLCCommunicationError(
                        message=f"读取线圈失败: {result}",
                        device_name=f"PLC[{self.host}:{self.port}]"
                    )
                return result.bits[:count]
            except ME as e:
                logger.error(f"读取线圈异常: {e}")
                raise PLCCommunicationError(
                    message=f"读取线圈异常: {e}",
                    device_name=f"PLC[{self.host}:{self.port}]"
                )
    
    # 写入单个线圈状态
    def write_coil(self, address, value, slave=None) -> bool:
        _slave = slave if slave is not None else self.slave_id
        with self._lock:
            self._ensure_connection()
            try:
                result = self._client.write_coil(address, value, device_id=_slave)
                if result.isError():
                    logger.error(f"写入线圈失败: {result}")
                    raise PLCCommunicationError(
                        message=f"写入线圈失败: {result}",
                        device_name=f"PLC[{self.host}:{self.port}]"
                    )
                return True
            except ME as e:
                logger.error(f"写入线圈异常: {e}")
                raise PLCCommunicationError(
                    message=f"写入线圈异常: {e}",
                    device_name=f"PLC[{self.host}:{self.port}]"
                )

    # 写入多个线圈状态
    def write_coils(self, address, values, slave=None) -> bool:
        _slave = slave if slave is not None else self.slave_id
        with self._lock:
            self._ensure_connection()
            try:
                result = self._client.write_coils(address, values, device_id=_slave)
                if result.isError():
                    logger.error(f"写入线圈失败: {result}")
                    raise PLCCommunicationError(
                        message=f"写入线圈失败: {result}",
                        device_name=f"PLC[{self.host}:{self.port}]"
                    )
                return True
            except ME as e:
                logger.error(f"写入线圈异常: {e}")
                raise PLCCommunicationError(
                    message=f"写入线圈异常: {e}",
                    device_name=f"PLC[{self.host}:{self.port}]"
                )
    
    # 读取多个离散输入状态
    def read_discrete_inputs(self, address, count, slave=None) -> list:
        _slave = slave if slave is not None else self.slave_id
        with self._lock:
            self._ensure_connection()
            try:
                result = self._client.read_discrete_inputs(address, count=count, device_id=_slave)
                if result.isError():
                    logger.error(f"读取离散输入失败: {result}")
                    raise PLCCommunicationError(
                        message=f"读取离散输入失败: {result}",
                        device_name=f"PLC[{self.host}:{self.port}]"
                    )
                return result.bits[:count]
            except ME as e:
                logger.error(f"读取离散输入异常: {e}")
                raise PLCCommunicationError(
                    message=f"读取离散输入异常: {e}",
                    device_name=f"PLC[{self.host}:{self.port}]"
                )
            
    # 启动轮询线程        
    def start_polling(self, address_map, callback, interval=1.0) -> None:
        
        self._poll_callback = callback
        self._poll_interval = interval
        self._address_map = address_map

        if self._poll_thread and self._poll_thread.is_alive():
            logger.warning("PLC轮询线程已在运行,无需重复启动")
            return
        
        self._stop_event.clear()
        self._poll_thread = threading.Thread(target = self._poll_loop, name = 'poll_loop', daemon=True)
        self._poll_thread.start()
        logger.info(f"PLC轮询线程已启动,间隔: {self._poll_interval}秒")

    # 停止轮询线程
    def stop_polling(self) -> None:
        self._stop_event.set()
        if self._poll_thread:
            self._poll_thread.join(timeout = 5)
            if self._poll_thread.is_alive():
                logger.warning("轮询线程未能在5秒内停止")
            self._poll_thread = None
            logger.info("PLC轮询线程已停止")

    # 轮询线程主循环
    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            data = {}
            try:
                for name, config in self._address_map.items():
                    addr_type = config["type"]
                    address = config["address"]
                    count = config.get("count", 1)

                    if addr_type == "holding":
                        data[name] = self.read_holding_registers(address, count)
                    elif addr_type == "coils":
                        data[name] = self.read_coils(address, count)
                    elif addr_type == "input":
                        data[name] = self.read_input_registers(address, count)
                    elif addr_type == "discrete":
                        data[name] = self.read_discrete_inputs(address, count)
                if data and self._poll_callback:
                    self._poll_callback(data)

            except PLCCommunicationError as e:
                logger.error(f"PLC轮询通信异常: {e}")
            except Exception as e:
                logger.error(f"PLC轮询异常: {e}")

            self._stop_event.wait(self._poll_interval)