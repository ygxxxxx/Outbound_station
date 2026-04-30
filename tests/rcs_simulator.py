import socket
import json
import threading

from datetime import datetime

from src.utils.logger import logger

logger = logger.bind(tag = "rcs_simulator")

SEPARATOR = b'\n'

class RCS_Simulator:
    def __init__(self, host, port):
        self.host = host
        self.port = port

        self.connected = False
        self.sock = None
        self.conn = None

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
        msg = self._build_goods_message(
                type = "ACK", 
                sender = result.get("receiver", ""), 
                receiver = result.get("sender", ""),
                data = {"result" : 0, "message" : ""}
            )
        self.send_data(msg)

        print(result.get("type", ""))
        print(result.get("sender", ""))
        print(result.get("receiver", ""))
        print(result.get("timestamp", ""))
        print(result.get("data", None))
        

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
    def close(self):
        self.stop_event.set()
        self.connected = False
        if self.conn:
            try:
                self.conn.close()
            except OSError:
                pass
            self.conn = None
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
        logger.info("模拟器已关闭")

    def _build_goods_message(self, type, sender, receiver, data) -> bytes:
        body = {
            "type": type,
            "sender": sender,
            "receiver": receiver,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data": data
        }
        return self._encode(body)
    
    

if __name__ == "__main__":
    import time
    rcs_simulator = RCS_Simulator("127.0.0.1", 9000)
    rcs_simulator.connect_station()
    time.sleep(100)
    rcs_simulator.close()