import socket
import threading
import struct
import json
import time

from src.utils.logger import logger
from src.exception.exception import VisionGateCommunicationError

logger = logger.bind(tag="VisionGate")

SYNC_BYTE = 0xAC
PROTO_VERSION = 1
HEADER_SIZE = 10
MSG_TYPE_OUTBOUND_REQ = 1000
MSG_TYPE_OUTBOUND_RES = 11000
HEADER_FORMAT = '!BBHHI'  

class VisionGateClient:

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.sock: socket.socket | None = None
        self.connected = False

        self._recv_buffer = b''
        self._recv_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._stop_event.set()

        self._lock = threading.Lock()
        self._seq = 0                        
        self._pending_seq = None             
        self._response_event = threading.Event()  
        self._last_response = None
        self._reconnect_interval = 3.0
        self._closed = False

    def _cleanup(self) -> None:
        self._stop_event.set()
        self._response_event.set()
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None
        self.connected = False

    # 视觉门连接
    def connect(self) -> None:
        if self.connected:
            logger.warning(f"视觉门已连接,无需重复连接: {self.host}:{self.port}")
            return
        self._cleanup()
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

    # 重复连接
    def connect_with_retry(self, max_retries: int = 0, interval: float = 2.0, backoff: float = 1.0) -> None:
        retry_count = 0
        current_interval = interval
        while True:
            try:
                self.connect()
                return
            except VisionGateCommunicationError:
                pass

            retry_count += 1
            if 0 < max_retries <= retry_count:
                logger.error(f"视觉门连接失败, 已达最大重试次数{max_retries}: {self.host}:{self.port}")
                raise VisionGateCommunicationError(
                    message=f"视觉门连接失败, 已达最大重试次数{max_retries}: {self.host}:{self.port}",
                    device_name=f"视觉门[{self.host}:{self.port}]"
                )

            logger.warning(
                f"视觉门未连接, {current_interval:.1f}秒后重试 "
                f"({retry_count}/{max_retries if max_retries > 0 else '∞'}): "
                f"{self.host}:{self.port}"
            )
            time.sleep(current_interval)
            current_interval *= backoff

    # 视觉门连接关闭
    def close(self) -> None:
        self._closed = True
        self._cleanup()
        logger.info(f"关闭视觉门连接: {self.host}:{self.port}")

    # 构建请求
    def _build_packet(self, msg_type: int, seq: int, body: dict) -> bytes:

        json_bytes = json.dumps(body, ensure_ascii=False).encode('utf-8')

        header = struct.pack(
            HEADER_FORMAT,
            SYNC_BYTE,
            PROTO_VERSION,
            seq,
            msg_type,
            len(json_bytes)
        )

        return header + json_bytes
    
    # 解析报文
    @staticmethod
    def _parse_header(data: bytes) -> tuple[dict | None, bytes]:
  
        if len(data) < HEADER_SIZE:
            return None, data

        sync, version, seq, msg_type, data_len = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
        if sync != SYNC_BYTE:
            return None, data[1:]  
    
        if version != PROTO_VERSION:
            raise VisionGateCommunicationError(
                message=f"协议版本不匹配: {version}",
                device_name="视觉门"
            )
        total_len = HEADER_SIZE + data_len
        if len(data) < total_len:
            return None, data
        body_bytes = data[HEADER_SIZE:total_len]
        remain = data[total_len:]

        if data_len > 0:
            try:
                body = json.loads(body_bytes.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return None, remain 
        else:
            body = {}
        result = {
            'seq': seq,
            'msg_type': msg_type,
            'body': body,
        }
        return result, remain
    
    # 序号生成
    def _next_seq(self) -> int:
        seq = self._seq
        self._seq = (self._seq + 1) % 65536 
        return seq
    
    # 发送货物列表
    def send_goods_list(self, goods: list[dict], timeout: float = 5.0) -> dict:
        seq = self._next_seq()
        packet = self._build_outbound_packet(seq, goods)
        self._pending_seq = seq
        self._response_event.clear()
        self._send(packet)

        received = self._response_event.wait(timeout)
        if not received:
            raise VisionGateCommunicationError(
                message=f"等待视觉门响应超时: {timeout}秒",
                device_name="视觉门"
            )
        
        self._pending_seq = None
        response = self._last_response
        self._last_response = None
        return response
    
    # 构建出库包裹数据
    def _build_outbound_packet(self, seq: int, goods: list[dict]) -> bytes:
        body = {
            "timestamp": int(time.time() * 1000),   # 13位毫秒时间戳
            "good_count": len(goods),                # 货物数量
            "goods": goods,                          # 货物列表
        }
        
        return self._build_packet(
            msg_type=MSG_TYPE_OUTBOUND_REQ,   # 1000
            seq=seq,
            body=body
        )
    
    # 发送数据
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
                    result, self._recv_buffer = self._parse_header(self._recv_buffer)
                    if result is None:
                        break
                    self._on_message(result)
        except OSError as e:
            logger.error(f"视觉门接收异常: {self.host}:{self.port}, 错误: {e}")
            self.connected = False
        finally:
            if not self._closed:
                threading.Thread(target=self._auto_reconnect, daemon=True).start()

    def _auto_reconnect(self) -> None:
        while not self._closed and not self.connected:
            logger.warning(f"视觉门断开, {self._reconnect_interval:.1f}秒后尝试重连: {self.host}:{self.port}")
            time.sleep(self._reconnect_interval)
            try:
                self.connect()
                logger.info(f"视觉门重连成功: {self.host}:{self.port}")
                return
            except VisionGateCommunicationError:
                logger.warning(f"视觉门重连失败, 将继续重试: {self.host}:{self.port}")

    # 处理接收消息
    def _on_message(self, result: dict) -> None:
        seq = result.get('seq')
        msg_type = result.get('msg_type')
        body = result.get('body', {})

        if msg_type != MSG_TYPE_OUTBOUND_RES:   # 11000
            logger.warning(f"收到非预期报文类型: {msg_type}, 忽略")
            return

        if seq != self._pending_seq:
            logger.warning(f"收到不匹配的响应序号: {seq}, 期望: {self._pending_seq}")
            return

        ret_code = body.get('ret_code', 0)      # 0或缺省=成功
        create_time = body.get('create_time')
        err_msg = body.get('err_msg', '')

        if ret_code == 0:
            logger.info(f"视觉门响应成功: seq={seq}")
        else:
            logger.warning(f"视觉门响应错误: seq={seq}, ret_code={ret_code}, err_msg={err_msg}")
            
        self._last_response = {
            'ret_code': ret_code,
            'create_time': create_time,
            'err_msg': err_msg,
        }
        self._response_event.set()