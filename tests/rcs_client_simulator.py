from src.communication.rcs_sever_protocol import decode,encode
from src.utils.logger import logger

import threading
import socket
import time
import random

logger = logger.bind(tag = 'rcs_client_simulator')

class RCS_Simulator:
    def __init__(self, host: str, status_port: int = 23310, task_port: int = 23311):
        self.host = host
        self.status_port = status_port
        self.task_port = task_port

        self.status_sock = None
        self.task_sock = None

        self.stop_event = threading.Event()

    def connect(self):
        # 连接状态端口
        self.status_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.status_sock.connect((self.host, self.status_port))
        self.status_connected = True
    
        # 连接任务端口
        self.task_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.task_sock.connect((self.host, self.task_port))
        self.task_connected = True
        
    def send_request(self, sock: socket.socket, cmd: int, body_dict: dict = None) -> tuple[int, int, int]:
        seq = random.randint(0,65535)
        data = encode(seq, cmd, body_dict)
        sock.sendall(data)

        recv_buffer = b''
        while True:
            data = sock.recv(4096)
            if not data:
                raise ConnectionError("连接断开")
            recv_buffer += data
            result, recv_buffer = decode(recv_buffer)
            if result is not None:
                resp_seq, resp_cmd, resp_body = result
                return resp_seq, resp_cmd, resp_body
            
    def query_outbound_task_detail(self) -> dict:
        _, _, body = self.send_request(self.status_sock, 1000)
        return body
    
    def query_outbound_storage(self) -> dict:
        _, _, body = self.send_request(self.status_sock, 1001)
        return body

    def query_outbound_status(self) -> dict:
        _, _, body = self.send_request(self.status_sock, 1002)
        return body

    def query_inbound_status(self) -> dict:
        _, _, body = self.send_request(self.status_sock, 1005)
        return body

    def query_outbound_subdevice(self) -> dict:
        _, _, body = self.send_request(self.status_sock, 1006)
        return body

    def query_outbound_batch(self) -> dict:
        _, _, body = self.send_request(self.status_sock, 1100)
        return body
    
    def dispatch_outbound_task(self, task_data: dict) -> dict:
        _, _, body = self.send_request(self.task_sock, 2000, task_data)
        return body

    def dispatch_inbound_route(self, route_data: dict) -> dict:
        _, _, body = self.send_request(self.task_sock, 2001, route_data)
        return body
    
    def close(self) -> None:
        self.stop_event.set()
        if self.status_sock:
            self.status_sock.close()
        if self.task_sock:
            self.task_sock.close()

if __name__ == '__main__':

    simulator = RCS_Simulator("127.0.0.1", status_port=23310, task_port=23311)
    simulator.connect()
    logger.info("已连接到上位机")

    

    resp = simulator.query_outbound_status()
    print(f"出库工作站状态: {resp}")

    resp = simulator.query_outbound_storage()
    print(f"出库库位信息: {resp}")

    task_data = {
        "task_id": "TEST_001",
        "task_types": "outbound",
        "timestamp": str(int(time.time() * 1000)),
        "packages": [
            {
                "package_id": "PKG001",
                "box_type": "DW01-A",
                "face_sheet": "SF1234567890",
                "logistics": "顺丰标快",
                "manual_process_type": "N",
                "packaging_line": "HS1",
                "count": 2,
                "goods": [
                    {"storage_location": "A11", "good_sku": "SKU-A001"},
                    {"storage_location": "A12", "good_sku": "SKU-A002"},
                ]
            }
        ]
    }
    resp = simulator.dispatch_outbound_task(task_data)
    print(f"任务下发响应: {resp}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        simulator.close()
        logger.info("程序已停止")