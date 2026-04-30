from src.utils.logger import logger
from src.exception.exception import RCSCommunicationError
from src.communication.rcs_protocol import build_message, decode
from src.models.outbound_task_model import OutboundTask, Package, Goods

import threading
import socket

logger = logger.bind(tag = "RCSClient")


class RCSClient:

    def __init__(self, host, port, outbound_station_id, on_dispatch = None):
        self.host = host
        self.port = port
        self.connected = False
        self.sock = None
        self._recv_buffer = b''  # 接收缓冲区
        self.outbound_id = outbound_station_id
        self.on_dispatch = on_dispatch  # 任务下发回调函数

    # 连接RCS
    def connect_to_rcs(self) -> None:
        if self.connected:
            logger.warning(f"RCS已连接,无需重复连接: {self.host}:{self.port}")
            return
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((self.host, self.port))
            self.connected = True
            self.sock = sock
            logger.info(f"连接RCS{self.host}:{self.port}")
            self._recv_buffer = b''
            self._recv_thread = threading.Thread(target=self.receive_loop, daemon=True)
            self._recv_thread.start()
        # 捕获连接异常
        except OSError as e:
            logger.error(f"RCS连接失败: {self.host}:{self.port}, 错误: {e}")
            raise RCSCommunicationError(
                message=f"RCS连接失败: {e}",
                device_name=f"RCS[{self.host}:{self.port}]"
            )

    # 接收RCS数据
    def receive_loop(self) -> None:
        if not self.connected:
            logger.warning(f"未连接RCS: {self.host}:{self.port}")
            self.connected = False
            return
        try:
            while True:
                try:
                    data = self.sock.recv(4096)  # 接收数据
                except socket.timeout:
                    continue
                if not data: 
                    logger.warning(f"RCS关闭连接: {self.host}:{self.port}")
                    self.connected = False
                    break
                self._recv_buffer += data
                logger.debug(f"从RCS接收到数据,长度: {len(data)}")
                while True:
                    msg, self._recv_buffer = decode(self._recv_buffer)
                    if msg is None:
                        break          # 缓冲区里没有完整消息了，等下次 recv
                    self._dispatch(msg)
        # 捕获接收异常
        except OSError as e:
            logger.error(f"RCS连接失败: {self.host}:{self.port}, 错误: {e}")
            self.connected = False
        
    # 分发RCS发送的消息
    def _dispatch(self, msg) -> None:
        msg_type = msg.get("type")
        if msg_type == "TASK_DISPATCH":
            self._handle_task_dispatch(msg)
        elif msg_type == "ACK":
            self._handle_ack(msg)
        elif msg_type == "HEARTBEAT":
            self._handle_heartbeat(msg)
        else:
            logger.warning(f"收到未知类型消息: {msg}")

    # 处理任务下发消息
    def _handle_task_dispatch(self, msg) -> None:
        data = msg["data"]
        task = OutboundTask(
            task_id=data["task_id"],
            packages=[Package(
                package_id=p["package_id"],
                face_sheet=p.get("face_sheet"),
                logistics=p.get("logistics"),
                manual_process_type=p.get("manual_process_type"),
                packaging_line=p.get("packaging_line"),
                goods=[Goods(goods_id=g["goods_id"], count=g["count"]) for g in p.get("goods", [])]
            )for p in data.get("packages", [])]
        )
        resp = build_message("TASK_ACCEPT", self.outbound_id, "RCS", {
            "task_id": task.task_id, "result": 0, "message": "OK"
        })
        self.send_data(resp)
        if self.on_dispatch:
            self.on_dispatch(task)

    # 处理确认消息
    def _handle_ack(self, msg) -> None:
        data = msg.get("data", {})
        if data.get("result") == 0:
            logger.info(f"收到RCS确认")
        elif data.get("result") == 1:
            logger.warning(f"失败-参数错误")
        elif data.get("result") == 2:
            logger.warning(f"失败-系统繁忙")
        elif data.get("result") == 3:
            logger.warning(f"失败-任务不存在")
        elif data.get("result") == 4:
            logger.warning(f"失败-工作站不可用")
        else:
            logger.warning(f"失败-未知错误")

    # 处理心跳消息
    def _handle_heartbeat(self, msg) -> None:
       
        pass

    # 发送数据到RCS
    def send_data(self, data) -> None:
        if not self.connected:
            logger.warning(f"未连接RCS: {self.host}:{self.port}")
            raise RCSCommunicationError(
                message="未连接RCS",
                device_name=f"RCS[{self.host}:{self.port}]"
            )
        try:
            self.sock.sendall(data) # 循环发送全部数据
            logger.debug(f"发送数据到RCS,长度: {len(data)}")
        # 捕获发送异常
        except OSError as e:
            logger.error(f"RCS连接失败: {self.host}:{self.port}, 错误: {e}")
            raise RCSCommunicationError(
                message=f"RCS连接失败: {e}",
                device_name=f"RCS[{self.host}:{self.port}]"
            )

    # 关闭连接
    def close(self) -> None:
        if self.connected:
            self.sock.close()
            self.connected = False
            logger.info(f"关闭RCS连接: {self.host}:{self.port}")


if __name__ == "__main__":
    from datetime import datetime
    import time
    rcs_client = RCSClient(host = "127.0.0.1", port = 9000, outbound_station_id = "01")
    rcs_client.connect_to_rcs()
    msg = {

        "task_id": "T202604301452",
        "task_types":"OUTBOUND",
        "status": "COMPLETED",
        "completed_goods": 12,
        "total_goods": 12,
        "completed_packages": ["PKG001", "PKG002"],
        "finish_time": "2026-04-30 14:55:00"
        
    }
    msg = build_message(msg_type = "TASK_COMPLETE", sender = "HOST_01", receiver = "RCS", data = msg)
    rcs_client.send_data(msg)
    time.sleep(100)
    rcs_client.close()
