import socket
from src.utils.logger import logger
from src.exception.exception import PLCCommunicationError

logger = logger.bind(tag = "PLCClient")

class PLCClient:

    def __init__(self, port, host):
        self.host = host
        self.port = port
        self.connected = False
        self.sock = None

    # 连接PLC
    def connect_to_plc(self):
        if self.connected:
            logger.warning(f"PLC已连接,无需重复连接: {self.host}:{self.port}")
            return
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((self.host, self.port))
            self.connected = True
            self.sock = sock
            logger.info(f"连接PLC{self.host}:{self.port}")
        # 捕获连接异常
        except OSError as e:
            logger.error(f"PLC连接失败: {self.host}:{self.port}, 错误: {e}")
            raise PLCCommunicationError(
                message=f"PLC连接失败: {e}",
                device_name=f"PLC[{self.host}:{self.port}]"
            )

    # 接收PLC数据
    def receive_data(self):
        if not self.connected:
            logger.warning(f"未连接PLC: {self.host}:{self.port}")
            raise PLCCommunicationError(
                message="未连接PLC",
                device_name=f"PLC[{self.host}:{self.port}]"
            )
        try:
            while True:
                data = self.sock.recv(4096)  # 接收数据
                if not data: 
                    logger.warning(f"PLC关闭连接: {self.host}:{self.port}")
                    self.connected = False
                    break
                logger.debug(f"从PLC接收到数据,长度: {len(data)}")
        # 捕获接收异常
        except OSError as e:
            logger.error(f"PLC连接失败: {self.host}:{self.port}, 错误: {e}")
            raise PLCCommunicationError(
                message=f"PLC连接失败: {e}",
                device_name=f"PLC[{self.host}:{self.port}]"
            )

    # 发送数据到PLC
    def send_data(self, data):
        if not self.connected:
            logger.warning(f"未连接PLC: {self.host}:{self.port}")
            raise PLCCommunicationError(
                message="未连接PLC",
                device_name=f"PLC[{self.host}:{self.port}]"
            )
        try:
            self.sock.sendall(data) # 循环发送全部数据
            logger.debug(f"发送数据到PLC,长度: {len(data)}")
        # 捕获发送异常
        except OSError as e:
            logger.error(f"PLC连接失败: {self.host}:{self.port}, 错误: {e}")
            raise PLCCommunicationError(
                message=f"PLC连接失败: {e}",
                device_name=f"PLC[{self.host}:{self.port}]"
            )

    # 关闭连接
    def close(self):
        if self.connected:
            self.sock.close()
            self.connected = False
            logger.info(f"关闭PLC连接: {self.host}:{self.port}")


if __name__ == "__main__":
    plc_client = PLCClient(port = 100, host = "127.0.0.1")
    plc_client.connect_to_plc()
    plc_client.send_data(b"Hello PLC")
    plc_client.close()

                           