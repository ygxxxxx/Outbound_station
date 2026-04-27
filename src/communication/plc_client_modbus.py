"""
基于 Modbus TCP 协议的 PLC 通信客户端
=====================================

【协议说明】
Modbus 是一种工业通信协议，广泛应用于 PLC、传感器、执行器等设备之间的数据交换。
Modbus TCP 是 Modbus 协议在 TCP/IP 网络上的实现，使用标准以太网进行通信。

【数据模型】
Modbus 定义了四种数据区域，每种有独立的地址空间：
  1. 线圈 (Coils)              —— 可读写的布尔量（开关量输出），功能码 01/05/15
  2. 离散输入 (Discrete Inputs)  —— 只读的布尔量（开关量输入），功能码 02
  3. 保持寄存器 (Holding Registers)—— 可读写的 16 位字（模拟量输出/设置值），功能码 03/06/16
  4. 输入寄存器 (Input Registers)  —— 只读的 16 位字（模拟量输入），功能码 04

【地址说明】
Modbus 协议中有两种地址表示方式：
  - PLC 地址 (0-based)：从 0 开始编号，本代码使用此方式
  - 协议地址 (1-based)：从 1 开始编号，如 40001 表示第 1 个保持寄存器
  本代码中所有 address 参数均为 0-based PLC 地址。

【依赖】
需要先安装: pip install pymodbus

【架构设计】
本类在 pymodbus 库的基础上封装了以下能力：
  - 连接管理与自动重连机制
  - 线程安全（所有读写操作加互斥锁）
  - 统一的异常处理和错误包装（转为项目自定义的 PLCCommunicationError）
  - 后台轮询线程（周期性地批量读取指定地址的数据，通过回调通知上层）
  - 防止在未连接状态下执行 I/O 操作（自动触发重连）

注意：此文件为 AI 生成的参考代码，不直接使用。
实际业务逻辑请在 plc_client2.py 中基于此参考实现编写。
"""

from pymodbus.client import ModbusTcpClient

# ModbusException —— pymodbus 中所有 Modbus 异常的基类（如网络超时、连接断开等）
from pymodbus.exceptions import ModbusException

# ExceptionResponse —— 表示 PLC 返回的 Modbus 异常响应帧
# （请求被 PLC 理解但无法执行，如非法地址、非法数据值等）
from pymodbus.pdu import ExceptionResponse
from src.utils.logger import logger
from src.exception.exception import PLCCommunicationError
import threading
import time


# 为日志打上标签，方便在日志中按 "PLCClient" 过滤和定位
logger = logger.bind(tag="PLCClient")


class PLCClient:
    """
    Modbus TCP PLC 通信客户端

    功能概述：
      - 连接到指定 IP:Port 的 Modbus TCP 服务器（PLC）
      - 读写保持寄存器 (holding registers) —— 功能码 03/16
      - 读写线圈 (coils) —— 功能码 01/05
      - 读取离散输入 (discrete inputs) —— 功能码 02
      - 读取输入寄存器 (input registers) —— 功能码 04
      - 启动后台轮询线程，周期性采集数据并通过回调函数上报

    线程安全：
      所有公有的读写操作均通过 threading.Lock 加锁保护，
      确保在多线程环境下不会出现并发访问冲突。

    使用示例:
        plc = PLCClient(host="192.168.1.100", port=502)
        plc.connect_to_plc()
        values = plc.read_holding_registers(address=0, count=10)
        plc.write_registers(address=0, values=[100, 200])
        plc.close()
    """

    def __init__(self, host, port=502, timeout=5, retries=3, slave_id=1):
        """
        初始化 PLC 客户端

        参数:
            host (str):   PLC 设备的 IP 地址，如 "192.168.1.100"
            port (int):   Modbus TCP 端口号，标准端口为 502，默认为 502
            timeout (float): 单次请求的超时时间（秒），默认 5 秒
            retries (int):   请求失败后的重试次数，默认 3 次
            slave_id (int):  Modbus 从站地址（站号），默认 1
                            注：TCP 网络中通常忽略从站地址，但某些 PLC/网关仍然使用
        """
        self.host = host
        self.port = port
        # 从站地址 —— Modbus TCP 中通常填 1 即可，串行链路上的 Modbus RTU 才需区分站号
        self.slave_id = slave_id
        # 连接状态标志，用于快速判断是否已连接（避免频繁调用底层的 is_connected）
        self.connected = False

        # 创建 pymodbus 同步 TCP 客户端实例
        # pymodbus 内部会自动管理 Socket 连接和重连逻辑
        self._client = ModbusTcpClient(
            host=host,
            port=port,
            timeout=timeout,  # 单次请求超时
            retries=retries,  # 失败后自动重试次数
        )

        # ===== 轮询线程相关 =====
        # 停止事件 —— 用于优雅地通知轮询线程退出
        # threading.Event 是一个简单的线程间通信原语，类似一个可跨线程共享的布尔标志
        self._stop_event = threading.Event()
        # 轮询线程对象
        self._poll_thread = None
        # 轮询间隔（秒），默认 1 秒读取一次
        self._poll_interval = 1.0
        # 轮询数据回调函数，签名: callback(dict) -> None
        self._poll_callback = None
        # 轮询要读取的地址映射表，在 start_polling() 时设置
        self._address_map = None

        # 线程锁 —— 保证所有 Modbus I/O 操作的互斥执行
        # 为什么需要锁？
        #   1. 底层 ModbusTcpClient 的 Socket 不是线程安全的
        #   2. 防止读/写操作交叉执行导致数据混乱
        #   3. 防止轮询线程与用户操作同时访问 PLC 产生冲突
        self._lock = threading.Lock()

    # ============================================================
    #  连接管理
    # ============================================================

    def connect_to_plc(self):
        """
        建立与 PLC 的 Modbus TCP 连接

        行为:
          - 如果已经连接，记录警告日志并直接返回（幂等操作，可安全重复调用）
          - 否则调用 pymodbus 底层 connect() 建立 TCP 连接
          - 连接失败时抛出 PLCCommunicationError

        注意:
          connect() 仅建立 TCP Socket 连接，不发送任何 Modbus 报文。
          实际数据通信发生在后续的读写操作中。
        """
        # 检查底层 TCP 连接是否已存在
        if self._client.connected:
            logger.warning(f"PLC已连接,无需重复连接: {self.host}:{self.port}")
            self.connected = True
            return

        try:
            # 调用 pymodbus 底层建立 TCP 连接
            # 返回 True 表示连接成功，返回 False/None 表示失败
            result = self._client.connect()
            if not result:
                raise PLCCommunicationError(
                    message="PLC连接失败",
                    device_name=f"PLC[{self.host}:{self.port}]",
                )
            self.connected = True
            logger.info(f"连接PLC成功: {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"PLC连接失败: {self.host}:{self.port}, 错误: {e}")
            raise PLCCommunicationError(
                message=f"PLC连接失败: {e}",
                device_name=f"PLC[{self.host}:{self.port}]",
            )

    def _ensure_connected(self):
        """
        确保已连接到 PLC，如果未连接则自动重连

        这是内部保护方法，在所有读写操作前调用，用于处理以下场景：
          - 初始化后从未调用 connect_to_plc()
          - 网络中断导致底层 Socket 断开
          - PLC 重启导致连接丢失

        如果重连失败，抛出 PLCCommunicationError 终止当前操作。
        """
        if not self._client.connected:
            logger.warning(f"未连接PLC,尝试重连: {self.host}:{self.port}")
            # 尝试重新建立 TCP 连接
            self._client.connect()
            if not self._client.connected:
                raise PLCCommunicationError(
                    message="未连接PLC",
                    device_name=f"PLC[{self.host}:{self.port}]",
                )
            self.connected = True

    def _handle_result(self, result, operation):
        """
        处理 Modbus 请求的响应结果，统一进行错误检查和异常抛出

        pymodbus 中请求可能有三种返回结果：
          1. 正常响应 —— 包含请求的数据
          2. ExceptionResponse —— PLC 返回异常码（如非法地址 0x02、非法数据值 0x03）
          3. 其他错误 —— 网络超时、连接断开等

        参数:
            result:    Modbus 请求的返回值（可能是正常响应或异常响应对象）
            operation: 操作描述字符串，用于错误日志，如 "读取保持寄存器[0:10]"

        异常:
            当 result 为 ExceptionResponse 或 isError() 为 True 时，
            抛出 PLCCommunicationError
        """
        # 检查是否为 Modbus 协议级异常响应
        # 例如：读取了不存在的地址、写入了超出范围的值
        if isinstance(result, ExceptionResponse):
            raise PLCCommunicationError(
                message=f"PLC异常响应: {operation}, 异常码: {result.exception_code}",
                device_name=f"PLC[{self.host}:{self.port}]",
            )
        # 检查是否为其他类型错误（网络错误、超时等）
        if result.isError():
            raise PLCCommunicationError(
                message=f"Modbus操作失败: {operation}, 错误: {result}",
                device_name=f"PLC[{self.host}:{self.port}]",
            )

    # ============================================================
    #  读/写保持寄存器 (Holding Registers) —— 功能码 03 / 16
    #  保持寄存器是 Modbus 中最常用的数据区域，16 位无符号整数，
    #  可读可写，通常用于存储工艺参数、设定值、控制命令等。
    # ============================================================

    def read_holding_registers(self, address, count):
        """
        读取保持寄存器（功能码 03 —— Read Holding Registers）

        参数:
            address (int): 起始地址（0-based PLC 地址）
            count (int):   连续读取的寄存器数量（每个寄存器 2 字节/16 位）

        返回:
            list[int]: 读取到的寄存器值列表，每个值范围 0~65535，如 [100, 200, 300]

        示例:
            # 从地址 0 开始读取 3 个保持寄存器
            values = plc.read_holding_registers(address=0, count=3)
            # values 可能是 [1000, 2000, 3000]
        """
        # 使用锁保护整个操作，确保线程安全
        with self._lock:
            # 先确保已连接，未连接则自动重连
            self._ensure_connected()
            try:
                # 调用 pymodbus 底层读取，slave 参数指定从站地址
                result = self._client.read_holding_registers(
                    address=address, count=count, slave=self.slave_id
                )
                # 统一处理响应结果（检查异常）
                self._handle_result(result, f"读取保持寄存器[{address}:{count}]")
                # result.registers 是 list[int]，每个元素 0~65535
                logger.debug(f"读取保持寄存器[{address}:{count}] = {result.registers}")
                return result.registers
            except PLCCommunicationError:
                # 已包装的异常直接向上抛出，不做二次包装
                raise
            except Exception as e:
                # 其他意外异常（如 Socket 断开）—— 标记连接断开，包装后抛出
                self.connected = False
                logger.error(f"读取保持寄存器异常: {e}")
                raise PLCCommunicationError(
                    message=f"读取保持寄存器异常: {e}",
                    device_name=f"PLC[{self.host}:{self.port}]",
                )

    def write_registers(self, address, values):
        """
        写入多个保持寄存器（功能码 16 —— Write Multiple Registers）

        参数:
            address (int):  起始地址（0-based PLC 地址）
            values (list[int]): 要写入的值列表，每个值范围 0~65535

        返回:
            bool: 写入成功返回 True

        示例:
            # 从地址 100 开始写入 3 个寄存器
            plc.write_registers(address=100, values=[500, 600, 700])

        注意:
            pymodbus 的 write_registers 内部会根据 values 长度自动选择：
              - 单个值：使用功能码 06（写单个寄存器）
              - 多个值：使用功能码 16（写多个寄存器）
        """
        with self._lock:
            self._ensure_connected()
            try:
                result = self._client.write_registers(
                    address=address, values=values, slave=self.slave_id
                )
                self._handle_result(result, f"写入寄存器[{address}:{len(values)}]")
                logger.debug(f"写入寄存器[{address}] = {values}")
                return True
            except PLCCommunicationError:
                raise
            except Exception as e:
                self.connected = False
                logger.error(f"写入寄存器异常: {e}")
                raise PLCCommunicationError(
                    message=f"写入寄存器异常: {e}",
                    device_name=f"PLC[{self.host}:{self.port}]",
                )

    # ============================================================
    #  读/写线圈 (Coils) —— 功能码 01 / 05
    #  线圈是布尔量（位操作），可读可写。
    #  通常用于控制继电器、指示灯、启停信号等开关量输出。
    # ============================================================

    def read_coils(self, address, count):
        """
        读取线圈状态（功能码 01 —— Read Coils）

        线圈是 Modbus 中的可读写开关量（布尔值），通常代表 PLC 的数字输出点。

        参数:
            address (int): 起始地址（0-based PLC 地址）
            count (int):   连续读取的线圈数量

        返回:
            list[bool]: 线圈状态列表，True=ON，False=OFF

        示例:
            # 读取地址 0 开始的 8 个线圈状态
            coil_states = plc.read_coils(address=0, count=8)
            # 结果如 [True, False, True, True, False, False, True, False]
        """
        with self._lock:
            self._ensure_connected()
            try:
                result = self._client.read_coils(
                    address=address, count=count, slave=self.slave_id
                )
                self._handle_result(result, f"读取线圈[{address}:{count}]")
                # result.bits 是包含所有返回位的列表
                # 截取到 count 长度，防止返回数据超出预期
                logger.debug(f"读取线圈[{address}:{count}] = {result.bits[:count]}")
                return result.bits[:count]
            except PLCCommunicationError:
                raise
            except Exception as e:
                self.connected = False
                logger.error(f"读取线圈异常: {e}")
                raise PLCCommunicationError(
                    message=f"读取线圈异常: {e}",
                    device_name=f"PLC[{self.host}:{self.port}]",
                )

    def write_coil(self, address, value):
        """
        写入单个线圈（功能码 05 —— Write Single Coil）

        参数:
            address (int): 线圈地址（0-based PLC 地址）
            value (bool):   要写入的值，True=ON，False=OFF

        返回:
            bool: 写入成功返回 True

        示例:
            # 将地址 0 的线圈置为 ON（启动信号）
            plc.write_coil(address=0, value=True)

        注意:
            这是写单个线圈。如果需要同时写多个线圈，
            可以使用 pymodbus 的 write_coils（功能码 15），
            当前类暂未封装该方法。
        """
        with self._lock:
            self._ensure_connected()
            try:
                result = self._client.write_coil(
                    address=address, value=value, slave=self.slave_id
                )
                self._handle_result(result, f"写入线圈[{address}]")
                logger.debug(f"写入线圈[{address}] = {value}")
                return True
            except PLCCommunicationError:
                raise
            except Exception as e:
                self.connected = False
                logger.error(f"写入线圈异常: {e}")
                raise PLCCommunicationError(
                    message=f"写入线圈异常: {e}",
                    device_name=f"PLC[{self.host}:{self.port}]",
                )

    # ============================================================
    #  读取离散输入 (Discrete Inputs) —— 功能码 02
    #  离散输入是只读的布尔量，通常代表传感器信号、限位开关、
    #  光电开关等外部数字输入信号。
    # ============================================================

    def read_discrete_inputs(self, address, count):
        """
        读取离散输入（功能码 02 —— Read Discrete Inputs）

        离散输入是只读的开关量，通常对应 PLC 的数字输入点 X0、X1 等，
        用于读取传感器、按钮、限位开关等外部输入信号的状态。

        参数:
            address (int): 起始地址（0-based PLC 地址）
            count (int):   连续读取的离散输入数量

        返回:
            list[bool]: 离散输入状态列表

        示例:
            # 读取 X0~X7 共 8 个输入点的状态
            inputs = plc.read_discrete_inputs(address=0, count=8)
        """
        with self._lock:
            self._ensure_connected()
            try:
                result = self._client.read_discrete_inputs(
                    address=address, count=count, slave=self.slave_id
                )
                self._handle_result(result, f"读取离散输入[{address}:{count}]")
                logger.debug(f"读取离散输入[{address}:{count}] = {result.bits[:count]}")
                return result.bits[:count]
            except PLCCommunicationError:
                raise
            except Exception as e:
                self.connected = False
                logger.error(f"读取离散输入异常: {e}")
                raise PLCCommunicationError(
                    message=f"读取离散输入异常: {e}",
                    device_name=f"PLC[{self.host}:{self.port}]",
                )

    # ============================================================
    #  读取输入寄存器 (Input Registers) —— 功能码 04
    #  输入寄存器是只读的 16 位值，通常对应 PLC 的模拟量输入通道
    #  （如温度传感器、压力变送器的 ADC 采样值）。
    # ============================================================

    def read_input_registers(self, address, count):
        """
        读取输入寄存器（功能码 04 —— Read Input Registers）

        输入寄存器是只读的 16 位整数，通常用于读取模拟量输入值
        （温度、压力、流量等传感器数据），对应 PLC 的 AD 输入通道。

        参数:
            address (int): 起始地址（0-based PLC 地址）
            count (int):   连续读取的寄存器数量

        返回:
            list[int]: 寄存器值列表，每个值范围 0~65535

        示例:
            # 读取地址 0 开始的 4 个输入寄存器（可能是 4 路模拟量输入）
            analog_values = plc.read_input_registers(address=0, count=4)
        """
        with self._lock:
            self._ensure_connected()
            try:
                result = self._client.read_input_registers(
                    address=address, count=count, slave=self.slave_id
                )
                self._handle_result(result, f"读取输入寄存器[{address}:{count}]")
                logger.debug(f"读取输入寄存器[{address}:{count}] = {result.registers}")
                return result.registers
            except PLCCommunicationError:
                raise
            except Exception as e:
                self.connected = False
                logger.error(f"读取输入寄存器异常: {e}")
                raise PLCCommunicationError(
                    message=f"读取输入寄存器异常: {e}",
                    device_name=f"PLC[{self.host}:{self.port}]",
                )

    # ============================================================
    #  轮询机制 —— 后台周期性数据采集
    #  通过独立的守护线程，按照 address_map 中配置的地址映射表，
    #  周期性批量读取 PLC 数据，并通过回调函数通知上层业务逻辑。
    #
    #  使用场景：
    #    - 实时监控：持续读取 PLC 状态寄存器，更新 UI 界面
    #    - 数据记录：定时采集传感器数据并存入数据库
    #    - 报警检测：监控关键线圈/寄存器，发现异常立即触发告警
    # ============================================================

    def start_polling(self, address_map, callback, interval=1.0):
        """
        启动轮询线程，周期性读取指定地址的数据

        参数:
            address_map (dict): 地址映射表，定义要读取的地址范围。
                格式示例:
                {
                    "设备状态": {"type": "holding",  "address": 100, "count": 10},
                    "IO状态":   {"type": "coils",   "address": 0,   "count": 16},
                    "传感器":   {"type": "input",   "address": 0,   "count": 4},
                    "开关量":   {"type": "discrete", "address": 0,   "count": 8},
                }
                其中 type 字段支持的取值:
                  - "holding"  : 保持寄存器 (功能码 03)
                  - "coils"    : 线圈 (功能码 01)
                  - "input"    : 输入寄存器 (功能码 04)
                  - "discrete" : 离散输入 (功能码 02)

            callback (callable): 数据回调函数，签名: callback(data_dict) -> None
                data_dict 的 key 与 address_map 的 key 一一对应，
                value 为读取到的数据列表。
                示例: {"设备状态": [100, 200, ...], "IO状态": [True, False, ...]}

            interval (float): 轮询间隔（秒），默认 1.0 秒。
                建议根据 PLC 的响应速度和业务需求设置：
                  - 实时控制: 0.1~0.5 秒
                  - 状态监控: 1~5 秒
                  - 数据记录: 10+ 秒

        注意:
            - 轮询线程是守护线程（daemon=True），主程序退出时会自动终止
            - 如果已有轮询线程在运行，不会重复启动（记录警告日志）
            - 不要在回调函数中执行耗时操作，否则会阻塞下一轮轮询
        """
        # 保存用户配置
        self._poll_callback = callback
        self._poll_interval = interval
        self._address_map = address_map

        # 防止重复启动轮询线程
        if self._poll_thread and self._poll_thread.is_alive():
            logger.warning("轮询线程已在运行")
            return

        # 清除停止信号（之前可能调用过 stop_polling() 设置了该事件）
        self._stop_event.clear()
        # 创建并启动守护线程（daemon=True 确保主程序退出时自动结束，不会阻止进程退出）
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        logger.info(f"PLC轮询线程已启动,间隔: {interval}s")

    def stop_polling(self):
        """
        停止轮询线程

        调用流程:
          1. 设置停止事件 (_stop_event.set())，通知 _poll_loop 退出循环
          2. 等待轮询线程结束（最多等 5 秒），防止资源泄漏
          3. 清理线程引用

        注意:
            该方法也会在 close() 中被自动调用，
            确保关闭客户端时轮询线程也被正确清理。
        """
        # 通过 Event 通知轮询线程退出
        self._stop_event.set()
        if self._poll_thread:
            # join(timeout) 等待线程结束，超时后放弃等待（避免死锁）
            self._poll_thread.join(timeout=5)
            self._poll_thread = None
        logger.info("PLC轮询线程已停止")

    def _poll_loop(self):
        """
        轮询主循环

        这是运行在后台守护线程中的核心循环逻辑：
          1. 检查停止事件 (_stop_event)，若被 set() 则退出循环
          2. 遍历 address_map 中的每一项配置，逐个读取 PLC 数据
          3. 根据 type 字段选择对应的 Modbus 读取函数
          4. 将成功读取的数据收集到 data 字典中
          5. 调用用户回调函数传递采集到的数据
          6. 等待 interval 秒后进入下一轮

        异常处理：
          - 轮询过程中的任何异常都被捕获并记录日志
          - 异常不会导致轮询线程退出，只会标记断连状态
          - 下一轮循环时 _ensure_connected 会触发自动重连

        关于使用 _stop_event.wait() 而非 time.sleep()：
          _stop_event.wait(timeout) 的行为：
            - 如果在 timeout 秒内 _stop_event 被 set()，立即返回 True
            - 如果 timeout 秒内未被 set()，返回 False
          这意味着 stop_polling() 调用 _stop_event.set() 时，
          此处可以立即响应并退出循环，而不必等待整个 interval 周期。
        """
        while not self._stop_event.is_set():
            data = {}
            try:
                # 每轮循环开始时确保连接正常（未连接则自动重连）
                self._ensure_connected()

                # 遍历地址映射表，逐个读取
                for name, config in self._address_map.items():
                    addr_type = config[
                        "type"
                    ]  # 寄存器类型: holding/coils/input/discrete
                    address = config["address"]  # 起始地址
                    count = config["count"]  # 数量

                    # 根据类型选择对应的读取函数
                    # 注意：轮询中直接调用底层 _client 方法而非封装方法，
                    # 这是因为封装的方法（如 read_holding_registers）内部持有 _lock 锁，
                    # 如果在轮询线程中也获取 _lock，会导致轮询线程与用户读写操作互相阻塞。
                    # 如果业务场景需要在轮询中也加锁保护，请自行调整实现。
                    if addr_type == "holding":
                        result = self._client.read_holding_registers(
                            address=address, count=count, slave=self.slave_id
                        )
                        if not result.isError():
                            data[name] = result.registers
                    elif addr_type == "coils":
                        result = self._client.read_coils(
                            address=address, count=count, slave=self.slave_id
                        )
                        if not result.isError():
                            data[name] = result.bits[:count]
                    elif addr_type == "input":
                        result = self._client.read_input_registers(
                            address=address, count=count, slave=self.slave_id
                        )
                        if not result.isError():
                            data[name] = result.registers
                    elif addr_type == "discrete":
                        result = self._client.read_discrete_inputs(
                            address=address, count=count, slave=self.slave_id
                        )
                        if not result.isError():
                            data[name] = result.bits[:count]

                # 如果本轮采集到了数据且用户设置了回调函数，则调用回调
                if data and self._poll_callback:
                    self._poll_callback(data)

            except Exception as e:
                logger.error(f"轮询异常: {e}")
                # 标记断连，下一轮循环会在 _ensure_connected 中自动重连
                self.connected = False

            # 等待 interval 秒或直到停止事件被触发
            # 与 time.sleep 的区别：可被 _stop_event.set() 立即中断
            self._stop_event.wait(self._poll_interval)

    # ============================================================
    #  资源释放
    # ============================================================

    def close(self):
        """
        关闭与 PLC 的连接并释放资源

        执行步骤:
          1. 停止轮询线程（如果有）
          2. 关闭底层 Modbus TCP Socket 连接
          3. 更新连接状态标志

        注意：
            使用完 PLCClient 后务必调用 close() 方法，
            否则可能导致 Socket 资源泄漏和轮询线程残留（守护线程会在进程退出时终结，
            但优雅关闭是最佳实践）。
            推荐使用 try-finally 确保资源一定会被释放。

        示例:
            try:
                plc.connect_to_plc()
                # ... 业务操作 ...
            finally:
                plc.close()
        """
        # 先停止轮询，再关闭连接（顺序重要：轮询依赖底层连接）
        self.stop_polling()
        self._client.close()
        self.connected = False
        logger.info(f"关闭PLC连接: {self.host}:{self.port}")


# ============================================================
#  测试代码 —— 仅在直接运行本文件时执行（python -m 方式不会触发此段）
# ============================================================
if __name__ == "__main__":
    # 创建一个连接到 192.168.1.100:502 的 PLC 客户端实例
    # 【实际使用时请修改为你的 PLC 的真实 IP 地址】
    plc = PLCClient(host="192.168.1.100", port=502, slave_id=1)

    try:
        # 1. 建立连接
        plc.connect_to_plc()

        # 2. 写入测试：从地址 0 开始写入 3 个保持寄存器
        #    （寄存器地址和值的含义取决于 PLC 程序，实际使用时参考 PLC 的变量表）
        plc.write_registers(address=0, values=[100, 200, 300])
        print("写入成功")

        # 3. 读回验证：从同一起始地址读取相同数量的寄存器，确认写入了正确的值
        values = plc.read_holding_registers(address=0, count=3)
        print(f"读回: {values}")

        # 4. 读取线圈：读取前 8 个线圈的状态
        coils = plc.read_coils(address=0, count=8)
        print(f"线圈状态: {coils}")

        # 5. 写入线圈：将地址 0 的线圈置为 ON（如启动信号、急停复位等）
        plc.write_coil(address=0, value=True)
        print("启动信号已发送")

        # 6. 轮询测试：每 0.5 秒读取一次数据并通过回调函数打印
        def on_poll_data(data):
            """轮询回调函数 —— 收到新数据时被 _poll_loop 调用"""
            print(f"[轮询] 收到数据: {data}")

        plc.start_polling(
            address_map={
                "status": {"type": "holding", "address": 100, "count": 10},
                "io": {"type": "coils", "address": 0, "count": 16},
            },
            callback=on_poll_data,
            interval=0.5,  # 每 0.5 秒轮询一次
        )

        # 主线程等待 10 秒，期间轮询线程在后台持续采集数据
        time.sleep(10)

    except PLCCommunicationError as e:
        # 处理 PLC 通信相关的业务异常（如断连、超时、非法地址等）
        print(f"PLC通信异常: {e}")
    finally:
        # 无论如何都要确保资源被释放（关闭连接、停止轮询线程）
        plc.close()
