import time
import sys

from src.communication.plc_client import PLC_Client
from src.communication.plc_service import PLC_Service
from src.exception.exception import ParameterError


PLC_HOST = "192.168.1.88"
PLC_PORT = 502
PLC_SLAVE_ID = 1
PLC_TIMEOUT = 5
STATION_ID = 1

TEST_FUNCTIONS = {
    "1":  ("读取寄存器",             "test_read_registers"),
    "2":  ("写入并回读验证",          "test_write_read_back"),
    "3":  ("启动状态轮询",           "test_start_polling"),
    "4":  ("查询所有状态",           "test_query_all_status"),
    "5":  ("单夹爪指令",             "test_single_gripper"),
    "6":  ("批量夹爪指令",           "test_batch_gripper"),
    "7":  ("参数校验",              "test_param_validation"),
    "8":  ("库位传送带集体转动",       "test_cabinet_place"),
    "9":  ("各层库位转动指令",        "test_cabinet_forward"),
    "10": ("无货物跳过指令",          "test_cabinet_no_box"),
    "11": ("清除单层超时标志",        "test_clear_timeout"),
    "12": ("清除全部层超时标志",      "test_clear_all_timeouts"),
    "13": ("边界值查询",             "test_boundary_queries"),
}


def input_int(prompt, default=None):
    raw = input(prompt).strip()
    if not raw and default is not None:
        return default
    return int(raw)


def input_gripper_params():
    print("  --- 输入夹爪参数 (直接回车使用默认值) ---")
    gripper_id = input_int("  gripper_id [1~6] (默认1): ", 1)
    layer = input_int("  layer [1~4] (默认1): ", 1)
    count = input_int("  count [1~4] (默认1): ", 1)
    size = input_int("  size (默认1): ", 1)
    place_count = input_int("  place_count (默认1): ", 1)
    return gripper_id, layer, count, size, place_count


def show_menu():
    print("\n" + "=" * 60)
    print("  PLC Service 测试菜单")
    print("=" * 60)
    for key, (desc, _) in TEST_FUNCTIONS.items():
        print(f"  [{key:>2}] {desc}")
    print("-" * 60)
    print("  [ a] 全部测试")
    print("  [ q] 退出")
    print("=" * 60)


def run_test(service, func_name):
    func = globals()[func_name]
    func(service)


def run_all(service):
    for key in sorted(TEST_FUNCTIONS.keys(), key=int):
        desc, func_name = TEST_FUNCTIONS[key]
        print(f"\n>>> 运行测试 [{key}] {desc}")
        try:
            run_test(service, func_name)
        except Exception as e:
            print(f"  FAIL: {e}")


def main():
    client = PLC_Client(host=PLC_HOST, port=PLC_PORT, slave_id=PLC_SLAVE_ID, timeout=PLC_TIMEOUT)
    service = PLC_Service(client)

    print("正在连接PLC...")
    service.start_connects()
    print("连接成功")

    if len(sys.argv) > 1:
        service.start_status_polling(interval=0.3)
        time.sleep(1)
        try:
            arg = sys.argv[1]
            if arg == "a":
                run_all(service)
            elif arg in TEST_FUNCTIONS:
                desc, func_name = TEST_FUNCTIONS[arg]
                print(f"\n>>> 运行测试 [{arg}] {desc}")
                run_test(service, func_name)
            else:
                print(f"无效参数: {arg}")
        except Exception as e:
            print(f"  FAIL: {e}")
        finally:
            service.stop_status_polling()
            service.close()
            print("PLC连接已关闭")
        return

    while True:
        show_menu()
        choice = input("请选择测试项: ").strip().lower()

        if choice == "q":
            break

        if choice == "a":
            service.start_status_polling(interval=0.3)
            time.sleep(1)
            try:
                run_all(service)
            finally:
                service.stop_status_polling()
            continue

        if choice in TEST_FUNCTIONS:
            desc, func_name = TEST_FUNCTIONS[choice]
            service.start_status_polling(interval=0.3)
            time.sleep(1)
            print(f"\n>>> 运行测试 [{choice}] {desc}")
            try:
                run_test(service, func_name)
            except Exception as e:
                print(f"  FAIL: {e}")
            finally:
                service.stop_status_polling()
            continue

        print("无效选择，请重新输入")

    service.close()
    print("PLC连接已关闭, 退出")


def test_read_registers(service: PLC_Service):
    print("=" * 60)
    print("读取寄存器")

    regs = service._plc_client.read_holding_registers(0, 18)
    print(f"  控制区 D0~D17: {regs}")

    regs = service._plc_client.read_holding_registers(100, 10)
    print(f"  状态区 D100~D109: {regs}")

    print("  PASS")


def test_write_read_back(service: PLC_Service):
    print("=" * 60)
    print("写入并回读验证")

    test_addr = 9999
    original = service._plc_client.read_holding_registers(test_addr, 1)
    service._plc_client.write_holding_registers(test_addr, [12345])
    result = service._plc_client.read_holding_registers(test_addr, 1)
    assert result[0] == 12345, f"回读值不符: {result[0]}"
    service._plc_client.write_holding_registers(test_addr, original)
    print("  PASS")


def test_start_polling(service: PLC_Service):
    print("=" * 60)
    print("启动状态轮询")

    status = service.get_full_status()
    assert isinstance(status, dict)
    assert "emergency_stop" in status
    assert "grippers" in status
    assert "stations" in status
    print(f"  急停: {status['emergency_stop']}")
    print(f"  夹爪数量: {len(status['grippers'])}")
    print(f"  工作站数量: {len(status['stations'])}")
    print("  PASS")


def test_query_all_status(service: PLC_Service):
    print("=" * 60)
    print("查询所有状态")

    es = service.is_emergency_stop()
    print(f"  急停: {es}")

    for gid in range(1, 7):
        state = service.get_gripper_state(gid)
        print(f"  夹爪{gid} 运行中: {state.is_running if state else 'None'}")

    all_grippers = service.get_all_gripper_states()
    print(f"  全部夹爪: {[g.is_running for g in all_grippers]}")

    st = service.get_station_state(STATION_ID)
    if st:
        for i, layer in enumerate(st.layers, 1):
            print(f"  工作站{STATION_ID} {i}层: 传送带={layer.is_conveyor_running}, "
                  f"前光电={layer.front_photo_triggered}, 后光电={layer.back_photo_triggered}, "
                  f"超时={layer.is_timeout}")

    faults = service.get_station_faults(STATION_ID)
    print(f"  工作站{STATION_ID} 故障: {faults}")

    print(f"  完整状态字典: {service.get_full_status()}")
    print("  PASS")


def test_single_gripper(service: PLC_Service):
    print("=" * 60)
    gripper_id, layer, count, size, place_count = input_gripper_params()
    print(f"  单夹爪指令: gripper_id={gripper_id}, layer={layer}, count={count}, size={size}, place_count={place_count}")
    result = service.command_gripper(
        gripper_id=gripper_id, layer=layer, count=count, size=size,
        place_count=place_count, delay_before_pos=0.6
    )
    assert result is True
    print("  PASS")


def test_batch_gripper(service: PLC_Service):
    print("=" * 60)
    commands = []
    num = input_int("  输入夹爪指令条数 (默认2): ", 2)
    for i in range(num):
        print(f"  --- 第{i + 1}条指令 ---")
        gripper_id, layer, count, size, place_count = input_gripper_params()
        commands.append({
            "gripper_id": gripper_id, "layer": layer,
            "count": count, "size": size, "place_count": place_count,
        })
    print(f"  批量夹爪指令: {commands}")
    result = service.command_gripper_batch(commands, delay_before_pos=0.6)
    assert result is True
    print("  PASS")


def test_param_validation(service: PLC_Service):
    print("=" * 60)
    print("参数校验")

    try:
        service.command_gripper(gripper_id=1, layer=0, count=1, size=1, place_count=1)
        assert False, "layer=0 应抛异常"
    except ParameterError:
        print("  layer=0 -> ParameterError OK")

    try:
        service.command_gripper(gripper_id=1, layer=5, count=1, size=1, place_count=1)
        assert False, "layer=5 应抛异常"
    except ParameterError:
        print("  layer=5 -> ParameterError OK")

    try:
        service.command_gripper(gripper_id=1, layer=1, count=0, size=1, place_count=1)
        assert False, "count=0 应抛异常"
    except ParameterError:
        print("  count=0 -> ParameterError OK")

    try:
        service.command_gripper(gripper_id=1, layer=1, count=5, size=1, place_count=1)
        assert False, "count=5 应抛异常"
    except ParameterError:
        print("  count=5 -> ParameterError OK")

    try:
        service.command_gripper_batch([
            {"gripper_id": 1, "layer": 5, "count": 1, "size": 1, "place_count": 1}
        ])
        assert False, "批量layer=5 应抛异常"
    except ParameterError:
        print("  batch layer=5 -> ParameterError OK")

    try:
        service.command_gripper_batch([
            {"gripper_id": 1, "layer": 1, "count": 0, "size": 1, "place_count": 1}
        ])
        assert False, "批量count=0 应抛异常"
    except ParameterError:
        print("  batch count=0 -> ParameterError OK")

    print("  PASS")


def test_cabinet_place(service: PLC_Service):
    print("=" * 60)
    print(f"工作站{STATION_ID} 库位传送带集体转动")
    result = service.command_cabinet_place(station_id=STATION_ID)
    assert result is True
    print("  PASS")


def test_cabinet_forward(service: PLC_Service):
    print("=" * 60)
    layer = input_int(f"  输入层号 [1~4] (默认1): ", 1)
    print(f"  工作站{STATION_ID} {layer}层库位转动指令")
    result = service.command_cabinet_forward(station_id=STATION_ID, layer=layer)
    assert result is True
    print(f"  {layer}层: OK")
    print("  PASS")


def test_cabinet_no_box(service: PLC_Service):
    print("=" * 60)
    layer = input_int(f"  输入层号 [1~4] (默认1): ", 1)
    print(f"  工作站{STATION_ID} {layer}层无货物跳过指令")
    result = service.command_cabinet_no_box(station_id=STATION_ID, layer=layer)
    assert result is True
    print(f"  {layer}层: OK")
    print("  PASS")


def test_clear_timeout(service: PLC_Service):
    print("=" * 60)
    layer = input_int(f"  输入层号 [1~4] (默认1): ", 1)
    print(f"  工作站{STATION_ID} {layer}层超时标志清除")
    result = service.clear_cabinet_timeout(station_id=STATION_ID, layer=layer)
    assert result is True
    time.sleep(0.5)
    timeout = service.is_cabinet_timeout(STATION_ID, layer)
    assert timeout is False
    print(f"  {layer}层: 超时={timeout}")
    print("  PASS")


def test_clear_all_timeouts(service: PLC_Service):
    print("=" * 60)
    print(f"工作站{STATION_ID} 全部层超时标志清除")
    result = service.clear_all_cabinet_timeouts(station_id=STATION_ID)
    assert result is True
    time.sleep(0.5)
    for layer in range(1, 5):
        timeout = service.is_cabinet_timeout(STATION_ID, layer)
        assert timeout is False
        print(f"  {layer}层: 超时={timeout}")
    print("  PASS")


def test_boundary_queries(service: PLC_Service):
    print("=" * 60)
    print("边界值查询")

    assert service.get_gripper_state(0) is None
    assert service.get_gripper_state(7) is None
    print("  非法夹爪ID -> None OK")

    assert service.get_station_state(0) is None
    assert service.get_station_state(4) is None
    print("  非法工作站ID -> None OK")

    assert service.is_conveyor_running(1, 0) is False
    assert service.is_conveyor_running(1, 5) is False
    assert service.is_photo_triggered(1, 0, "front") is False
    assert service.is_cabinet_timeout(1, 0) is False
    print("  非法层号 -> False OK")

    print("  PASS")


if __name__ == "__main__":
    main()
