
from src.communication.plc_simulator import PLCSimulator
from src.communication.plc_service import PLCService
from src.communication.plc_client import PLC_Client
import time

def test_gripper_control():
    """测试夹爪控制流程"""
    
    # 1. 启动模拟器
    sim = PLCSimulator(host="127.0.0.1", port=5020)
    sim.start()
    time.sleep(1)  # 等待服务器就绪

    # 2. 创建 PLC 客户端和服务层
    client = PLC_Client(host="127.0.0.1", port=5020)
    client.connect_to_plc()
    service = PLCService(client)

    # 3. 启动状态轮询
    service.start_status_polling(interval=0.5)
    time.sleep(1)

    # 4. 下发夹爪指令
    service.command_gripper(gripper_id=1, layer=2, count=3, size=38)

    # 5. 立即检查状态——夹爪应该是运行中
    gripper = service.get_gripper_state(1)
    assert gripper.is_running == True
    print(f"夹爪1状态: 运行中")

    # 6. 等待模拟完成（3秒 + 轮询间隔）
    time.sleep(4)

    # 7. 再次检查——夹爪应该是空闲
    gripper = service.get_gripper_state(1)
    assert gripper.is_running == False
    print(f"夹爪1状态: 空闲")

    # 8. 清理
    service.stop_status_polling()
    client.plc_close()
    sim.stop()
    print("测试通过")


def test_emergency_stop():
    """测试急停功能"""
    
    sim = PLCSimulator(host="127.0.0.1", port=5020)
    sim.start()
    time.sleep(1)

    client = PLC_Client(host="127.0.0.1", port=5020)
    client.connect_to_plc()
    service = PLCService(client)
    service.start_status_polling(interval=0.3)
    time.sleep(1)

    # 模拟触发急停
    sim.simulate_emergency_stop()
    time.sleep(1)

    # 检查急停状态
    assert service.is_emergency_stop() == True
    print("急停检测: 已触发")

    # 清除急停
    sim.clear_emergency_stop()
    time.sleep(1)

    assert service.is_emergency_stop() == False
    print("急停检测: 已清除")

    service.stop_status_polling()
    client.plc_close()
    sim.stop()
    print("急停测试通过")


if __name__ == "__main__":
    test_gripper_control()
    test_emergency_stop()