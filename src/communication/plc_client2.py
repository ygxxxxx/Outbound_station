from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException as ME

from src.utils.logger import logger
from src.exception.exception import PLCCommunicationError

import threading
import time

logger = logger.bind(tag = "PLCClient")

class PLCClient:

    def __init__(self, port, host, timeout = 5):
        self.host = host
        self.port = port
        self._lock = threading.Lock()
        self.timeout = timeout
        self._client = ModbusTcpClient(host = self.host, port = self.port, timeout = self.timeout, retries = 3)

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
    
    def _ensure_connection(self) -> None:
        if not self._client.connected:
            logger.warning(f"PLC未连接,正在尝试重新连接: {self.host}:{self.port}")
            self.connect_to_plc()
        if not self._client.connected:
            logger.error(f"PLC连接失败: {self.host}:{self.port}")
            raise PLCCommunicationError(
                message=f"PLC连接失败,无法执行操作: {self.host}:{self.port}",
                device_name=f"PLC[{self.host}:{self.port}]"
            )

    # 断开PLC连接
    def plc_close(self) -> None:
        if self._client.connected:
            self._client.close()
            logger.info(f"PLC连接已关闭: {self.host}:{self.port}")

    # 读取多个保持寄存器
    def read_holding_registers(self, address, count, slave = 1) -> list:
        with self._lock:
            self._ensure_connection()
            try:
                result = self._client.read_holding_registers(address, count, slave)
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
    def write_holding_registers(self, address, values, slave = 1) -> bool:
        with self._lock:
            self._ensure_connection()
            try:
                result = self._client.write_registers(address, values, slave)
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
    def read_input_registers(self, address, count, slave = 1) -> list:
        with self._lock:
            self._ensure_connection()
            try:
                result = self._client.read_input_registers(address, count, slave)
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
    def read_coils(self, address, count, slave = 1) -> list:
        with self._lock:
            self._ensure_connection()
            try:
                result = self._client.read_coils(address, count, slave)
                if result.isError():
                    logger.error(f"读取线圈失败: {result}")
                    raise PLCCommunicationError(
                        message=f"读取线圈失败: {result}",
                        device_name=f"PLC[{self.host}:{self.port}]"
                    )
                return result.bits
            except ME as e:
                logger.error(f"读取线圈异常: {e}")
                raise PLCCommunicationError(
                    message=f"读取线圈异常: {e}",
                    device_name=f"PLC[{self.host}:{self.port}]"
                )
    
    # 写入单个线圈状态
    def write_coil(self, address, value, slave = 1) -> bool:
        with self._lock:
            self._ensure_connection()
            try:
                result = self._client.write_coil(address, value, slave)
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
    def write_coils(self, address, values, slave = 1) -> bool:
        with self._lock:
            self._ensure_connection()
            try:
                result = self._client.write_coils(address, values, slave)
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
    def read_discrete_inputs(self, address, count, slave = 1) -> list:
        with self._lock:
            self._ensure_connection()
            try:
                result = self._client.read_discrete_inputs(address, count, slave)
                if result.isError():
                    logger.error(f"读取离散输入失败: {result}")
                    raise PLCCommunicationError(
                        message=f"读取离散输入失败: {result}",
                        device_name=f"PLC[{self.host}:{self.port}]"
                    )
                return result.bits
            except ME as e:
                logger.error(f"读取离散输入异常: {e}")
                raise PLCCommunicationError(
                    message=f"读取离散输入异常: {e}",
                    device_name=f"PLC[{self.host}:{self.port}]"
                )