import socket
import json
import threading

from datetime import datetime


from src.utils.logger import logger

logger = logger.bind(tag = "visual_gate_simulator")

SEPARATOR = b'\n'

class visual_gate_simulator:
    def __init__(self, host, port):
        self.host = host
        self.port = port

        self.stop_event = threading.Event()
        
    def connect_station(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.listen(5)
        logger.info("等待上位机连接")
        self.conn, self.addr = self.sock.accept()
        self.connected = True
        self.stop_event.clear()
        logger.info(f"已连接到上位机: {self.addr}")

        threading.Thread(target = self.receive_loop, daemon = True).start()

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

    # 循环接收
    def receive_loop(self):
        buffer = b""
        while not self.stop_event.is_set() and self.connected:
            try:
                data = self.conn.recv(4096)
                if not data:
                    logger.info("连接已关闭")
                    self.connected = False
                    break
                buffer += data
                while True:
                    result, buffer = self._decode(buffer)
                    if result is None:
                        break
                    self.handle_message(result)
            except Exception as e:
                logger.error(f"接收数据时发生错误: {e}")
                break

    # 处理收到信息
    def handle_message(self, result):
        msg = self._build_goods_message(task_id = result.get("task_id", ""), result = 0)
        self.send_data(msg)

        print(result.get("task_id", ""))
        print(result.get("goods_sequence", None))
        print(result.get("sendtime", ""))

    # 发送数据
    def send_data(self, data) -> None:
        if not self.connected:
            logger.warning(f"未连接R上位机: {self.host}:{self.port}")
            return
        try:
            self.conn.sendall(data)
            logger.debug(f"发送数据到上位机,长度: {len(data)}")
        # 捕获发送异常
        except OSError as e:
            logger.error(f"上位机连接失败: {self.host}:{self.port}, 错误: {e}")

    # 编码函数
    def _encode(self, body_dict: dict) -> bytes:
        body_json = json.dumps(body_dict, ensure_ascii=False).encode('utf-8')
        return body_json + SEPARATOR
    
    # 处理消息转换成为字节码
    def _build_goods_message(self, task_id: str, result: int) -> bytes:
        body = {
            "task_id": task_id,
            "result": result,
            "sendtime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        return self._encode(body)
        




if __name__ == "__main__":
    simulator = visual_gate_simulator(host = "127.0.0.1", port = 9000)
    simulator.connect_station()