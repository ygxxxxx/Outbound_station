import time
import sys

from src.communication.plc_client import PLC_Client
from src.communication.plc_service import PLC_Service
from src.utils.logger import logger

logger = logger.bind(tag="location_move_test")

PLC_HOST = "192.168.1.88"
PLC_PORT = 502
PLC_SLAVE_ID = 1
PLC_TIMEOUT = 5

STATION_MAP = {"A": 1, "B": 2, "C": 3}
POSITION_TO_LOCAL_GRIPPER = {1: 1, 2: 2}


def global_gripper_id(station_id: int, local_gripper_id: int) -> int:
    return (station_id - 1) * 2 + local_gripper_id


def parse_location(code: str):
    return code[0], int(code[1]), int(code[2])


def wait_gripper_idle(plc: PLC_Service, gripper_id: int, timeout: float = 60.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = plc.get_gripper_state(gripper_id)
        if state is not None and not state.is_running:
            return True
        if plc.is_emergency_stop():
            print(f"  [ERROR] 急停已触发")
            return False
        time.sleep(0.2)
    print(f"  [ERROR] 等待夹爪{gripper_id}空闲超时")
    return False


def show_gripper_states(plc: PLC_Service):
    print("\n--- 夹爪状态 ---")
    for gid in range(1, 7):
        state = plc.get_gripper_state(gid)
        if state is None:
            print(f"  夹爪{gid}: 状态未知")
        else:
            running = "运行中" if state.is_running else "空闲"
            print(f"  夹爪{gid}: {running}")
    print()


def show_photo_states(plc: PLC_Service):
    print("\n--- 光电状态 ---")
    for station_code, station_id in STATION_MAP.items():
        for layer in range(1, 5):
            front = plc.is_photo_triggered(station_id, layer, "front")
            back = plc.is_photo_triggered(station_id, layer, "back")
            print(f"  {station_code}{layer}层: 前光电={'ON' if front else 'OFF'}, 后光电={'ON' if back else 'OFF'}")
    print()


def do_location_move(plc: PLC_Service):
    print("\n--- 库位移动 ---")
    print("格式: 源库位编码 -> 目标库位编码 (同工作站、同列)")
    print("示例: A11 -> A21 (把A工作站1层1位货物移到2层1位)")
    print("      A12 -> A32 (把A工作站1层2位货物移到3层2位)")
    print()

    from_str = input("输入源库位 (如 A11): ").strip().upper()
    to_str = input("输入目标库位 (如 A21): ").strip().upper()

    try:
        from_station, from_layer, from_pos = parse_location(from_str)
        to_station, to_layer, to_pos = parse_location(to_str)
    except (IndexError, ValueError):
        print(f"  [ERROR] 库位编码格式错误，需要3位编码如 A11")
        return

    if from_station != to_station:
        print(f"  [ERROR] 库位移动不能跨工作站: {from_str} -> {to_str}")
        return

    if from_pos != to_pos:
        print(f"  [ERROR] 库位移动不能跨列(位置不同): {from_str} -> {to_str}")
        return

    if from_layer == to_layer:
        print(f"  [ERROR] 源层和目标层相同，无需移动")
        return

    if from_pos not in POSITION_TO_LOCAL_GRIPPER:
        print(f"  [ERROR] 位置{from_pos}不可由夹爪直接抓取，只能移动位置1或2的货物")
        return

    station_id = STATION_MAP[from_station]
    local_gripper = POSITION_TO_LOCAL_GRIPPER[from_pos]
    gripper_id = global_gripper_id(station_id, local_gripper)

    print(f"\n  移动计划: {from_str}(层{from_layer}) -> {to_str}(层{to_layer})")
    print(f"  工作站: {from_station}(id={station_id}), 夹爪: 全局{gripper_id}(本地{local_gripper})")
    confirm = input("  确认执行? (y/n): ").strip().lower()
    if confirm != "y":
        print("  已取消")
        return

    if not wait_gripper_idle(plc, gripper_id):
        print(f"  [ERROR] 夹爪{gripper_id}未就绪，无法执行移动")
        return

    print(f"  正在下发库位移动指令: 夹爪{gripper_id}, 取货层={from_layer}, 放置层={to_layer}")
    plc.command_location_move(
        gripper_id=gripper_id,
        pick_layer=from_layer,
        place_layer=to_layer,
    )

    print(f"  等待夹爪{gripper_id}完成移动...")
    if wait_gripper_idle(plc, gripper_id, timeout=60.0):
        print(f"  库位移动完成: {from_str} -> {to_str}")
    else:
        print(f"  [ERROR] 库位移动超时或失败")


def do_location_move_batch(plc: PLC_Service):
    print("\n--- 批量库位移动 ---")
    print("输入多组移动，每组格式: 源库位->目标库位")
    print("每组必须同工作站、同列，且不能有重复夹爪")
    print("输入空行结束")
    print()

    moves = []
    used_grippers = set()

    while True:
        line = input(f"  移动#{len(moves)+1} (如 A11->A21): ").strip().upper()
        if not line:
            break

        parts = line.replace(" ", "").split("->")
        if len(parts) != 2:
            print("    [ERROR] 格式错误，请用 源库位->目标库位")
            continue

        from_str, to_str = parts
        try:
            from_station, from_layer, from_pos = parse_location(from_str)
            to_station, to_layer, to_pos = parse_location(to_str)
        except (IndexError, ValueError):
            print("    [ERROR] 库位编码格式错误")
            continue

        if from_station != to_station:
            print(f"    [ERROR] 不能跨工作站")
            continue
        if from_pos != to_pos:
            print(f"    [ERROR] 不能跨列")
            continue
        if from_layer == to_layer:
            print(f"    [ERROR] 源层和目标层相同")
            continue
        if from_pos not in POSITION_TO_LOCAL_GRIPPER:
            print(f"    [ERROR] 位置{from_pos}不可抓取")
            continue

        station_id = STATION_MAP[from_station]
        local_gripper = POSITION_TO_LOCAL_GRIPPER[from_pos]
        gripper_id = global_gripper_id(station_id, local_gripper)

        if gripper_id in used_grippers:
            print(f"    [ERROR] 夹爪{gripper_id}已在本批中使用")
            continue

        used_grippers.add(gripper_id)
        moves.append({
            "from": from_str,
            "to": to_str,
            "gripper_id": gripper_id,
            "from_layer": from_layer,
            "to_layer": to_layer,
        })
        print(f"    已添加: {from_str}->", to_str, f"(夹爪{gripper_id})")

    if not moves:
        print("  未输入任何移动")
        return

    print(f"\n  移动计划 ({len(moves)}组):")
    for m in moves:
        print(f"    {m['from']}(层{m['from_layer']}) -> {m['to']}(层{m['to_layer']}), 夹爪{m['gripper_id']}")

    confirm = input("  确认执行? (y/n): ").strip().lower()
    if confirm != "y":
        print("  已取消")
        return

    for gid in used_grippers:
        if not wait_gripper_idle(plc, gid):
            print(f"  [ERROR] 夹爪{gid}未就绪，中止批量移动")
            return

    for m in moves:
        print(f"  下发: 夹爪{m['gripper_id']}, 取{m['from_layer']}层->放{m['to_layer']}层")
        plc.command_location_move(
            gripper_id=m["gripper_id"],
            pick_layer=m["from_layer"],
            place_layer=m["to_layer"],
        )

    print("  等待所有夹爪完成...")
    for gid in sorted(used_grippers):
        if wait_gripper_idle(plc, gid, timeout=60.0):
            print(f"  夹爪{gid}移动完成")
        else:
            print(f"  [ERROR] 夹爪{gid}移动超时")

    print("  批量库位移动结束")


def do_cabinet_forward(plc: PLC_Service):
    print("\n--- 库位前进 (后排->前排) ---")
    station_str = input("输入工作站 (A/B/C): ").strip().upper()
    layer_str = input("输入层号 (1-4): ").strip()

    if station_str not in STATION_MAP:
        print("  [ERROR] 工作站只能是 A/B/C")
        return
    try:
        layer = int(layer_str)
        if not 1 <= layer <= 4:
            raise ValueError
    except ValueError:
        print("  [ERROR] 层号必须是1~4")
        return

    station_id = STATION_MAP[station_str]
    confirm = input(f"  确认: {station_str}{layer}层 前进? (y/n): ").strip().lower()
    if confirm != "y":
        print("  已取消")
        return

    plc.command_cabinet_forward(station_id, layer)
    print(f"  已下发 {station_str}{layer}层 前进指令")


def do_cabinet_backward(plc: PLC_Service):
    print("\n--- 库位后退 (前排->后排) ---")
    station_str = input("输入工作站 (A/B/C): ").strip().upper()
    layer_str = input("输入层号 (1-4): ").strip()

    if station_str not in STATION_MAP:
        print("  [ERROR] 工作站只能是 A/B/C")
        return
    try:
        layer = int(layer_str)
        if not 1 <= layer <= 4:
            raise ValueError
    except ValueError:
        print("  [ERROR] 层号必须是1~4")
        return

    station_id = STATION_MAP[station_str]
    confirm = input(f"  确认: {station_str}{layer}层 后退? (y/n): ").strip().lower()
    if confirm != "y":
        print("  已取消")
        return

    plc.command_cabinet_backward(station_id, layer)
    print(f"  已下发 {station_str}{layer}层 后退指令")


def do_clear_timeouts(plc: PLC_Service):
    print("\n--- 清除所有超时警报 ---")
    for station_id in range(1, 4):
        plc.clear_all_cabinet_timeouts(station_id)
    print("  已清除所有工作站超时警报")


def print_menu():
    print("=" * 40)
    print("  库位移动测试工具")
    print("=" * 40)
    print("  1. 库位移动 (单次)")
    print("  2. 库位移动 (批量)")
    print("  3. 库位前进 (后排->前排)")
    print("  4. 库位后退 (前排->后排)")
    print("  5. 查看夹爪状态")
    print("  6. 查看光电状态")
    print("  7. 清除所有超时警报")
    print("  0. 退出")
    print("-" * 40)


def main():
    plc_client = PLC_Client(PLC_HOST, PLC_PORT, PLC_SLAVE_ID, PLC_TIMEOUT)
    plc = PLC_Service(plc_client)

    print("正在连接PLC...")
    plc.start_connects()
    plc.start_status_polling(interval=0.3)
    time.sleep(1)
    print("PLC连接成功\n")

    handlers = {
        "1": do_location_move,
        "2": do_location_move_batch,
        "3": do_cabinet_forward,
        "4": do_cabinet_backward,
        "5": show_gripper_states,
        "6": show_photo_states,
        "7": do_clear_timeouts,
    }

    try:
        while True:
            print_menu()
            choice = input("请选择: ").strip()
            if choice == "0":
                break
            handler = handlers.get(choice)
            if handler:
                handler(plc)
            else:
                print("  无效选择")
            print()
    except KeyboardInterrupt:
        pass
    finally:
        plc.close()
        print("程序已退出")


if __name__ == "__main__":
    main()
