from src.communication.rcs_sever_protocol import decode, encode
from src.utils.logger import logger

import socket
import time
import random

logger = logger.bind(tag='rcs_client_simulator')


class RCS_Simulator:
    def __init__(self, host: str, status_port: int = 23310, task_port: int = 23311):
        self.host = host
        self.status_port = status_port
        self.task_port = task_port

        self.status_sock = None
        self.task_sock = None

        self.stop_event = False

    def connect(self):
        self.status_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.status_sock.connect((self.host, self.status_port))

        self.task_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.task_sock.connect((self.host, self.task_port))

    def send_request(self, sock: socket.socket, cmd: int, body_dict: dict = None) -> tuple[int, int, int]:
        seq = random.randint(0, 65535)
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

    def query_plc_status(self) -> dict:
        _, _, body = self.send_request(self.status_sock, 1003)
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
        self.stop_event = True
        if self.status_sock:
            self.status_sock.close()
        if self.task_sock:
            self.task_sock.close()


def _input(prompt_text: str, default: str = "") -> str:
    if default:
        raw = input(f"{prompt_text} [{default}]: ").strip()
        return raw if raw else default
    return input(f"{prompt_text}: ").strip()


def _input_int(prompt_text: str, default: int) -> int:
    raw = _input(prompt_text, str(default))
    try:
        return int(raw)
    except ValueError:
        return default


def _print_separator():
    print("=" * 60)


def _print_response(label: str, resp: dict):
    _print_separator()
    print(f"  {label}")
    _print_separator()
    _format_response(resp)
    _print_separator()
    print()


def _format_response(resp: dict, indent: int = 0):
    prefix = "  " * indent
    for key, value in resp.items():
        if isinstance(value, list):
            print(f"{prefix}{key}:")
            if not value:
                print(f"{prefix}  (空)")
            elif isinstance(value[0], dict):
                for i, item in enumerate(value):
                    print(f"{prefix}  [{i}]")
                    _format_response(item, indent + 2)
            else:
                for item in value:
                    print(f"{prefix}  - {item}")
        elif isinstance(value, dict):
            print(f"{prefix}{key}:")
            _format_response(value, indent + 1)
        else:
            print(f"{prefix}{key}: {value}")


STATION_IDS = ("A", "B", "C")
LOGISTICS_OPTIONS = ("shunfeng", "yunda", "zhongtong", "yuantong", "jd", "ems")
MANUAL_PROCESS_OPTIONS = ("N", "G", "S")
PACKAGING_LINE_OPTIONS = ("HS1", "HS2", "MP1", "MA1", "MO1")
BOX_TYPE_OPTIONS = ("DW01-A", "DW01-B", "DW02-A", "DW02-B")


def _input_putaway_task() -> dict:
    _print_separator()
    print("  下发放货任务 (putaway)")
    _print_separator()

    task_id = _input("任务ID", f"PUT_{int(time.time())}")
    station_id = _input(f"工作站编号 {STATION_IDS}", "A").upper()
    if station_id not in STATION_IDS:
        print(f"  无效工作站，使用默认 A")
        station_id = "A"

    put_goods = []
    print(f"\n  逐个输入库位货物信息 (输入空行结束)")
    print(f"  示例: 库位=A11, SKU=SKU1,SKU1,SKU1 -> A11 放3件 SKU1")
    while True:
        location = _input(f"\n  库位编号 (如 {station_id}11, 输入空行结束)", "")
        if not location:
            break

        skus = _input(f"  SKU (逗号分隔)", "SKU1")
        good_sku = [s.strip().strip("[]") for s in skus.split(",") if s.strip().strip("[]")]
        abr_count = len(good_sku)

        if abr_count == 0:
            print("  未输入SKU，跳过此库位")
            continue

        put_goods.append({
            "storage_location": location,
            "abr_count": abr_count,
            "good_sku": good_sku,
        })
        print(f"  -> {location}: {abr_count}件 {good_sku}")

    if not put_goods:
        print("  未输入任何库位，取消下发")
        return None

    print(f"\n  汇总:")
    for pg in put_goods:
        print(f"    {pg['storage_location']}: {pg['abr_count']}件 {pg['good_sku']}")

    return {
        "task_id": task_id,
        "task_types": "putaway",
        "timestamp": str(int(time.time() * 1000)),
        "station_id": station_id,
        "put_goods": put_goods,
    }


def _input_outbound_task() -> dict:
    _print_separator()
    print("  下发出库任务 (outbound)")
    _print_separator()

    task_id = _input("任务ID", f"OUT_{int(time.time())}")

    packages = []
    print("\n  输入包裹信息 (直接回车跳过包裹ID结束输入)")
    while True:
        raw = input(f"\n  包裹ID (直接回车结束): ").strip()
        if not raw:
            break
        package_id = raw

        box_type = _input(f"  纸箱类型 {'/'.join(BOX_TYPE_OPTIONS)}", "DW01-A")
        face_sheet = _input("  面单信息", "FS1")
        logistics = _input(f"  物流 {'/'.join(LOGISTICS_OPTIONS)}", "shunfeng")
        manual_type = _input(f"  人工处理类型 {'/'.join(MANUAL_PROCESS_OPTIONS)}", "N").upper()
        packaging_line = _input(f"  打包线 {'/'.join(PACKAGING_LINE_OPTIONS)}", "HS1")

        goods_str = _input("  货物SKU (逗号分隔, 如 SKU1,SKU2)", "SKU1,SKU2")
        goods = [s.strip().strip("[]") for s in goods_str.split(",") if s.strip().strip("[]")]
        count = len(goods)

        packages.append({
            "package_id": package_id,
            "box_type": box_type,
            "face_sheet": face_sheet,
            "logistics": logistics,
            "manual_process_type": manual_type,
            "packaging_line": packaging_line,
            "count": count,
            "goods": goods,
        })
        print(f"  已添加包裹: {package_id}, {count}件货物 {goods}")

    if not packages:
        print("  未输入任何包裹，取消下发")
        return None

    return {
        "task_id": task_id,
        "task_types": "outbound",
        "timestamp": str(int(time.time() * 1000)),
        "package_count": len(packages),
        "packages": packages,
    }


def show_menu():
    _print_separator()
    print("  RCS 客户端模拟器")
    _print_separator()
    print("  --- 状态查询 ---")
    print("  1. 查询出库任务执行情况")
    print("  2. 查询出库库位信息")
    print("  3. 查询出库工作站状态")
    print("  4. 查询PLC状态")
    print("  5. 批量查询全部信息")
    print()
    print("  --- 任务下发 ---")
    print("  6. 下发放货任务 (putaway)")
    print("  7. 下发出库任务 (outbound)")
    print("  8. 解除传送带超时报警")
    print()
    print("  0. 退出")
    _print_separator()


def main():
    simulator = RCS_Simulator("127.0.0.1", status_port=23310, task_port=23311)

    print("正在连接上位机...")
    try:
        simulator.connect()
    except ConnectionError as e:
        print(f"连接失败: {e}")
        return

    logger.info("已连接到上位机")
    print("已连接到上位机 (状态端口: 23310, 任务端口: 23311)\n")

    while True:
        try:
            show_menu()
            choice = input("请输入选项: ").strip()

            if choice == "0":
                print("正在断开连接...")
                simulator.close()
                print("已退出")
                break

            elif choice == "1":
                resp = simulator.query_outbound_task_detail()
                _print_response("出库任务执行情况", resp)

            elif choice == "2":
                resp = simulator.query_outbound_storage()
                _print_response("出库库位信息", resp)

            elif choice == "3":
                resp = simulator.query_outbound_status()
                _print_response("出库工作站状态", resp)

            elif choice == "4":
                resp = simulator.query_plc_status()
                _print_response("PLC状态", resp)

            elif choice == "5":
                resp = simulator.query_outbound_batch()
                _print_response("批量查询全部信息", resp)

            elif choice == "6":
                task_data = _input_putaway_task()
                if task_data:
                    resp = simulator.dispatch_outbound_task(task_data)
                    _print_response("放货任务下发响应", resp)

            elif choice == "7":
                task_data = _input_outbound_task()
                if task_data:
                    resp = simulator.dispatch_outbound_task(task_data)
                    _print_response("出库任务下发响应", resp)

            elif choice == "8":
                station_id = _input("工作站编号 (A/B/C)", "A").upper()
                layer_str = _input("层号 (1-4, 回车清除全部层)", "")
                if layer_str:
                    layer = int(layer_str) if layer_str.isdigit() else 1
                    route_data = {"station_id": station_id, "layer": layer}
                else:
                    route_data = {"station_id": station_id}
                resp = simulator.dispatch_inbound_route(route_data)
                _print_response("解除超时响应", resp)

            else:
                print("无效选项，请重新输入\n")

        except ConnectionError as e:
            print(f"\n连接断开: {e}")
            break
        except KeyboardInterrupt:
            print("\n正在断开连接...")
            simulator.close()
            print("已退出")
            break
        except Exception as e:
            print(f"\n操作失败: {e}\n")
            continue


if __name__ == '__main__':
    main()
