import socket
import threading
import json

from datetime import datetime

from src.utils.logger import logger
from src.exception.exception import VisionGateCommunicationError

logger = logger.bind(tag="VisionGate")

SEPARATOR = b'\n'


class VisionGateClient:

    def __init__(self, host: str, port: int, on_ack=None):
        self.host = host
        self.port = port
        self.sock: socket.socket | None = None
        self.connected = False
        self.on_ack = on_ack

        self._recv_buffer = b''
        self._recv_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._stop_event.set()

        self._lock = threading.Lock()

    # 视觉门连接
    def connect(self) -> None:
        if self.connected:
            logger.warning(f"视觉门已连接,无需重复连接: {self.host}:{self.port}")
            return
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((self.host, self.port))
            self.sock = sock
            self.connected = True
            self._recv_buffer = b''
            self._stop_event.clear()
            self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
            self._recv_thread.start()
            logger.info(f"连接视觉门成功: {self.host}:{self.port}")
        except OSError as e:
            self.connected = False
            logger.error(f"视觉门连接失败: {self.host}:{self.port}, 错误: {e}")
            raise VisionGateCommunicationError(
                message=f"视觉门连接失败: {e}",
                device_name=f"视觉门[{self.host}:{self.port}]"
            )

    # 视觉门连接关闭
    def close(self) -> None:
        self._stop_event.set()
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.connected = False
        self.sock = None
        logger.info(f"关闭视觉门连接: {self.host}:{self.port}")

    # 发送消息
    def send_goods_list(self, task_id: str, goods_sequence: list[dict]) -> None:
        msg = self._build_goods_message(task_id, goods_sequence)
        self._send(msg)

    # 处理消息转换成为字节码
    def _build_goods_message(self, task_id: str, goods_sequence: list[dict]) -> bytes:
        body = {
            "task_id": task_id,
            "goods_sequence": goods_sequence,
            "sendtime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        return self._encode(body)

    # 编码函数
    def _encode(self, body_dict: dict) -> bytes:
        body_json = json.dumps(body_dict, ensure_ascii=False).encode('utf-8')
        return body_json + SEPARATOR

    # 解码函数（静态方法）
    @staticmethod
    def _decode(data: bytes) -> tuple[dict | None, bytes]:
        if SEPARATOR not in data:
            return None, data
        line, remain = data.split(SEPARATOR, 1)
        try:
            return json.loads(line.decode('utf-8')), remain
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None, remain

    # 发送函数
    def _send(self, data: bytes) -> None:
        if not self.connected or not self.sock:
            logger.warning(f"视觉门未连接: {self.host}:{self.port}")
            raise VisionGateCommunicationError(
                message="视觉门未连接",
                device_name=f"视觉门[{self.host}:{self.port}]"
            )
        try:
            self.sock.sendall(data)
            logger.debug(f"发送数据到视觉门, 长度: {len(data)}")
        except OSError as e:
            self.connected = False
            logger.error(f"视觉门发送失败: {self.host}:{self.port}, 错误: {e}")
            raise VisionGateCommunicationError(
                message=f"视觉门发送失败: {e}",
                device_name=f"视觉门[{self.host}:{self.port}]"
            )

    # 循环接收
    def _recv_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    data = self.sock.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    logger.warning(f"视觉门关闭连接: {self.host}:{self.port}")
                    self.connected = False
                    break
                with self._lock:
                    self._recv_buffer += data
                while True:
                    msg, self._recv_buffer = self._decode(self._recv_buffer)
                    if msg is None:
                        break
                    self._on_message(msg)
        except OSError as e:
            logger.error(f"视觉门接收异常: {self.host}:{self.port}, 错误: {e}")
            self.connected = False

    # 解析收到信息
    def _on_message(self, msg: dict) -> None:
        task_id = msg.get("task_id", "")
        result = msg.get("result")
        if result is not None:
            if result == 0:
                logger.info(f"视觉门ACK成功: task_id={task_id}")
            else:
                logger.warning(f"视觉门ACK失败: task_id={task_id}, result={result}")
            if self.on_ack:
                try:
                    self.on_ack(task_id, result)
                except Exception as e:
                    logger.error(f"视觉门ACK回调异常: {e}")
        else:
            logger.debug(f"视觉门收到未知消息: {msg}")


if __name__ == "__main__":
    visiongateclient = VisionGateClient(host = "127.0.0.1", port = 9000)
    visiongateclient.connect()
    task_id = "T123456789"
    goos_sequence = [  
        {
            "sequence" : 1,
            "goods_id" : "SKU-A001",
            "package_id" : "PKG001",
            "target_line" : "高速线1"
        },
        {
            "sequence" : 2,
            "goods_id" : "SKU-A002",
            "package_id" : "PKG001",
            "target_line" : "高速线1"
        },
        {
            "sequence" : 3,
            "goods_id" : "SKU-A003",
            "package_id" : "PKG002",
            "target_line" : "高速线2"
        }
    ]
    visiongateclient.send_goods_list(task_id = task_id, goods_sequence = goos_sequence)
    input("按回车退出")