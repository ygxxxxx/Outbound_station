from src.utils.logger import logger
from src.communication.rcs_sever_protocol import encode, decode
from src.exception.exception import ProtocolDataError,ProtocolVersionError

import threading
import socket
import time

logger = logger.bind(tag = "RCSSever")

# 命令类型编码定义
class CmdType:
    # 状态接口
    OUTBOUND_TASK_DETAIL_REQ    = 1000    # 查询出库任务执行情况
    OUTBOUND_TASK_DETAIL_RES    = 11000

    OUTBOUND_STORAGE_REQ        = 1001    # 查询出库库位信息
    OUTBOUND_STORAGE_RES        = 11001

    OUTBOUND_STATUS_REQ         = 1002    # 查询出库工作站状态
    OUTBOUND_STATUS_RES         = 11002

    OUTBOUND_SUBDEVICE_REQ      = 1006    # 查询出库子设备状态
    OUTBOUND_SUBDEVICE_RES      = 11006

    OUTBOUND_BATCH_REQ          = 1100    # 批量查询出库全部信息
    OUTBOUND_BATCH_RES          = 11100

    # 任务接口
    OUTBOUND_TASK_DISPATCH_REQ  = 2000    # 下发出库任务
    OUTBOUND_TASK_DISPATCH_RES  = 12000

# RCS通信模块（作为服务端）
class RCS_Sever:
    def __init__(
            self, status_host: str, 
            status_port: int, 
            task_host: str, 
            task_port: int, 
            on_status_request = None, 
            on_task_request = None
            ) -> None:
        self.status_host = status_host
        self.status_port = status_port
        self.status_sock = None
        self.status_connected = False
        self.status_stop_event = threading.Event()

        self.task_host = task_host
        self.task_port = task_port
        self.task_sock = None
        self.task_connected = False
        self.task_stop_event = threading.Event()
    
        self.on_status_request = on_status_request
        self.on_task_request = on_task_request

    # 启动状态接口
    def _status_port_start(self) -> None:
        self.status_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # 创建使用Ipv4 + TCP的socket对象
        self.status_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # 允许端口复用
        self.status_sock.bind((self.status_host, self.status_port))# 绑定到指定ip和端口
        self.status_sock.listen(5)
        self.status_sock.settimeout(1.0)
        logger.info("等待RCS连接...")
        while not self.status_stop_event.is_set():
            try:
                conn, addr = self.status_sock.accept()
                conn.settimeout(1.0)
                self.status_connected = True
            except socket.timeout:
                continue
            logger.info(f"状态端口连接: {addr}")
            # 每个客户端连接启动一个独立的recv线程
            threading.Thread(target= self._status_port_receive_loop, args= (conn, addr), daemon= True).start()
        self.status_sock.close()

    # 启动任务接口
    def _task_port_start(self) -> None:
        self.task_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # 创建使用Ipv4 + TCP的socket对象
        self.task_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # 允许端口复用
        self.task_sock.bind((self.task_host, self.task_port))# 绑定到指定ip和端口
        self.task_sock.listen(5)
        self.task_sock.settimeout(1.0)
        logger.info("等待RCS连接...")
        while not self.task_stop_event.is_set():
            try:
                conn, addr = self.task_sock.accept()
                conn.settimeout(1.0)
                self.task_connected = True
            except socket.timeout:
                continue
            logger.info(f"任务端口连接: {addr}")
            threading.Thread(target= self._task_port_receive_loop, args= (conn, addr), daemon= True).start()
        self.task_sock.close()

    # 启动RCS通信模块
    def start(self) -> None:
        self.status_stop_event.clear()
        self.task_stop_event.clear()
        threading.Thread(target= self._status_port_start, daemon = True).start()
        threading.Thread(target= self._task_port_start, daemon = True).start()

    # 状态接口循环接收函数
    def _status_port_receive_loop(self, conn, addr) -> None:
        recv_buffer = b''
        try:
            while not self.status_stop_event.is_set():
                try:
                    data = conn.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    logger.warning(f"RCS状态接口关闭连接")
                    break
                recv_buffer += data
                while True:
                    try:
                        result, recv_buffer = decode(recv_buffer)
                    except ProtocolVersionError as e:
                        recv_buffer = e.remaining
                        error_resp = encode(e.seq, e.cmd + 10000, {"ret_code": -1, "create_time": (int(time.time() * 1000)), "err_msg": str(e)})
                        conn.sendall(error_resp)
                        break
                    except  ProtocolDataError as e:
                        recv_buffer = e.remaining
                        error_resp = encode(e.seq, e.cmd + 10000, {"ret_code": -1, "create_time": (int(time.time() * 1000)), "err_msg": str(e)})
                        conn.sendall(error_resp)
                        break
                    if result is None:
                        break
                    seq, cmd, body_dict = result
                    logger.info(f"[接收] seq = {seq}, cmd = {cmd}, body_dict = {body_dict}")
                    self._status_handle_message(seq, cmd, body_dict, conn)
        except Exception as e:
            logger.error(f"接收数据时发生错误:{e}")
        finally:
            conn.close()
            logger.info(f"RCS状态接口连接已关闭{addr}")
            
    # 任务接口循环接收函数     
    def _task_port_receive_loop(self, conn, addr) -> None:
        recv_buffer = b''
        try:
            while not self.task_stop_event.is_set():
                try:
                    data = conn.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    logger.warning(f"RCS任务接口关闭连接")
                    break
                recv_buffer += data
                while True:
                    try:
                        result, recv_buffer = decode(recv_buffer)
                    except ProtocolVersionError as e:
                        recv_buffer = e.remaining
                        error_resp = encode(e.seq, e.cmd + 10000, {"ret_code": -1, "create_time": int(time.time() * 1000), "err_msg": str(e)})
                        conn.sendall(error_resp)
                        break
                    except  ProtocolDataError as e:
                        recv_buffer = e.remaining
                        error_resp = encode(e.seq, e.cmd + 10000, {"ret_code": -1, "create_time": int(time.time() * 1000), "err_msg": str(e)})
                        conn.sendall(error_resp)
                        break
                    if result is None:
                        break
                    seq, cmd, body_dict = result
                    logger.info(f"[接收] seq = {seq}, cmd = {cmd}, body_dict = {body_dict}")
                    self._task_handle_message(seq, cmd, body_dict, conn)
        except Exception as e:
            logger.error(f"接收数据时发生错误:{e}")
        finally:
            conn.close()
            logger.info(f"RCS任务接口连接已关闭{addr}")

    def _status_handle_message(self, seq: int, cmd: int, body_dict: dict, conn) -> None:
        if self.on_status_request:
            response_data = self.on_status_request(cmd, body_dict)
            resp = encode(seq, cmd + 10000, response_data)
            conn.sendall(resp)


    def _task_handle_message(self, seq: int, cmd: int, body_dict: dict, conn) -> None:
        if self.on_task_request:
            response_data = self.on_task_request(cmd, body_dict)
            resp = encode(seq, cmd + 10000, response_data)
            conn.sendall(resp)

    def stop(self) -> None:
        self.status_stop_event.set()
        self.task_stop_event.set()




if __name__ == '__main__':
    def build_common_response(business_data: dict = None, ret_code: int = 0, err_msg: str = "") -> dict:
        response = {
            "ret_code": ret_code,
            "create_time": (int(time.time() * 1000)),
            "err_msg": err_msg,
        }
        if business_data:
            response.update(business_data)
        return response

    def handle_status_request(cmd: int, body_dict: dict) -> dict:
        if cmd == CmdType.OUTBOUND_TASK_DETAIL_REQ:
            return build_common_response({
                "task_id": "TEST001",
                "task_types": "outbound",
                "status": "IDLE",
                "total_goods": 0,
                "completed_goods": [],
            })
        elif cmd == CmdType.OUTBOUND_STORAGE_REQ:
            return build_common_response({"container": []})
        elif cmd == CmdType.OUTBOUND_STATUS_REQ:
            return build_common_response({
                "station1": "IDLE",
                "station2": "IDLE",
                "station3": "IDLE",
                "overall_status": "IDLE",
            })
        else:
            return build_common_response(ret_code=-1, err_msg=f"不支持: {cmd}")

    def handle_task_request(cmd: int, body_dict: dict) -> dict:
        if cmd == CmdType.OUTBOUND_TASK_DISPATCH_REQ:
            logger.info(f"收到任务下发: {body_dict}")
            return build_common_response()
        else:
            return build_common_response(ret_code=-1, err_msg=f"不支持: {cmd}")

    rcs = RCS_Sever(
        status_host="127.0.0.1",
        status_port=23310,
        task_host="127.0.0.1",
        task_port=23311,
        on_status_request=handle_status_request,
        on_task_request=handle_task_request,
    )

    rcs.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        rcs.stop()
        logger.info("程序已停止")