from src.communication.rcs_sever import RCS_Sever
from src.communication.plc_client import PLC_Client
from src.communication.plc_service import PLC_Service
from src.communication.vision_gate import VisionGateClient
from src.business.request_handle import parse_outbound_task, handle_status_request, handle_task_request
from src.business.state_machine import StateMachine
from src.business.task_manager import TaskManager
from src.business.task_processing import Task_Processing
from src.models.containers import CabinetStore
from src.config.settings import config
from src.utils.logger import logger

from functools import partial
import threading

import time

logger = logger.bind(tag="Main")



rcs: RCS_Sever = None
plc: PLC_Service = None
plc_client: PLC_Client = None
vis: VisionGateClient = None
state: StateMachine = None
taskmanager: TaskManager = None
taskprocessing: Task_Processing = None
cabinet_store: CabinetStore = None

def start():
    global rcs, plc, plc_client, state, taskmanager, taskprocessing, cabinet_store, vis
    
    taskmanager = TaskManager()
    cabinet_store = CabinetStore.create(station_prefixes=["A", "B", "C"])

    plc_client = PLC_Client(
        host = "192.168.1.88",
        port = 502,
        slave_id = 1,
        timeout = 5
    )
    plc = PLC_Service(plc_client)
    state = StateMachine(
        host_id = "OUTBOUND_STATION1",
        station_ids = ["A", "B", "C"],
        task_manager = taskmanager,
        plc_service = plc,
    )
    def _plc_connect_and_poll():
        plc.start_connects()
        plc.start_status_polling()

    plc.set_fault_check_callback(state.check_plc_faults)
    threading.Thread(target=_plc_connect_and_poll, daemon=True).start()

    on_status = partial(handle_status_request, state, plc, cabinet_store)
    on_task = partial(handle_task_request, taskmanager, state, plc)

    rcs = RCS_Sever(
        status_host = "127.0.0.1",
        status_port = 23310,
        task_host = "0.0.0.0",
        task_port = 23311,
        on_status_request=on_status,
        on_task_request=on_task,)
    
    vis = VisionGateClient(
        host = "127.0.0.1",
        port = 23320,
    )

    taskprocessing = Task_Processing(taskmanager, plc, state, cabinet_store, vis)

    rcs.start()
    threading.Thread(target=vis.connect_with_retry, daemon=True).start()
    taskprocessing.start()



def stop():
    rcs.stop()
    taskprocessing.stop()
    plc.close()

def main():
    start()
    try:
        while True:
            time.sleep(2)
                     
    except KeyboardInterrupt:
       stop()

main()
