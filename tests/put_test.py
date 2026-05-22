from src.communication.plc_client import PLC_Client
from src.communication.plc_registers import StatusAddr, GripperAddr, OutboundAddr, CabinetCtrlAddr
from src.communication.plc_service import PLC_Service

from src.utils.logger import logger

import time

logger = logger.bind(tag="put_test")

PLC_HOST = "192.168.1.88"
PLC_PORT = 502
PLC_SLAVE_ID = 1
PLC_TIMEOUT = 5
STATION_ID = 1


def main():
    plc_client = PLC_Client(PLC_HOST, PLC_PORT, PLC_SLAVE_ID, PLC_TIMEOUT)
    plc = PLC_Service(plc_client)
    plc.start_connects()
    plc.start_status_polling(interval=0.3)
    time.sleep(1)
    count = 0

    try:
        while True:
            time.sleep(0.1)
            if not plc.is_photo_triggered(1, 3, "back"):
                continue

            logger.info("3层后光电触发，下发放货指令")
            plc.command_cabinet_no_box(1, 4)
            plc.command_cabinet_no_box(1, 3)
            plc.command_cabinet_place(1)
            
            count += 1
            logger.info(f"第{count}轮放货测试")
            plc.clear_all_cabinet_timeouts(1)

            while plc.is_photo_triggered(1, 3, "back"):
                time.sleep(0.2)

    except KeyboardInterrupt:
        plc.close()
        logger.info("程序已停止")


main()
