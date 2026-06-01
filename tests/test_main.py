from src.communication.rcs_sever import RCS_Sever
from src.communication.plc_client import PLC_Client
from src.communication.plc_service import PLC_Service
from src.communication.vision_gate import VisionGateClient
from src.business.request_handle import handle_status_request, handle_task_request
from src.business.state_machine import StateMachine
from src.business.task_manager import TaskManager
from src.business.task_processing import Task_Processing
from src.models.containers import CabinetStore
from src.models.outbound_task_model import Put_Goods
from src.config.settings import load_config
from src.utils.logger import logger

from functools import partial
import threading

import time

logger = logger.bind(tag="test_main")



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

    config = load_config()
    
    taskmanager = TaskManager()
    cabinet_store = CabinetStore.create(station_prefixes=["A", "B", "C"])

    plc_client = PLC_Client(
        host = config.plcconfig.plc_address,
        port = config.plcconfig.plc_port,
        slave_id = 1,
        timeout = config.plcconfig.timeout
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
        status_host = config.rcsconfig.rcs_address,
        status_port = config.rcsconfig.rcs_status_port,
        task_host = config.rcsconfig.rcs_address,
        task_port = config.rcsconfig.rcs_task_port,
        on_status_request=on_status,
        on_task_request=on_task,)
    
    vis = VisionGateClient(
        host = config.visiongateconfig.vg_address,
        port = config.visiongateconfig.vg_port,
    )

    taskprocessing = Task_Processing(taskmanager, plc, state, cabinet_store, vis)

    rcs.start()
    threading.Thread(target=vis.connect_with_retry, daemon=True).start()
    taskprocessing.start()



def stop():
    rcs.stop()
    taskprocessing.stop()
    plc.close()

def early_batch_shipping():
    put_goods = [Put_Goods(storage_location="A11", abr_count=4, good_sku=["SKU1", "SKU1", "SKU1", "SKU1"]),
                 Put_Goods(storage_location="A12", abr_count=4, good_sku=["SKU2", "SKU2", "SKU2", "SKU2"]),
                 Put_Goods(storage_location="A13", abr_count=4, good_sku=["SKU2", "SKU2", "SKU2", "SKU2"]),
                 Put_Goods(storage_location="A14", abr_count=4, good_sku=["SKU1", "SKU1", "SKU1", "SKU1"]),
                 Put_Goods(storage_location="A21", abr_count=4, good_sku=["SKU3", "SKU3", "SKU3", "SKU3"]),
                 Put_Goods(storage_location="A22", abr_count=4, good_sku=["SKU3", "SKU3", "SKU3", "SKU3"]),
                 Put_Goods(storage_location="A23", abr_count=4, good_sku=["SKU3", "SKU3", "SKU3", "SKU3"]),
                 Put_Goods(storage_location="A24", abr_count=4, good_sku=["SKU4", "SKU4", "SKU4", "SKU4"]),
                 Put_Goods(storage_location="A31", abr_count=4, good_sku=["SKU1", "SKU1", "SKU1", "SKU1"]),
                 Put_Goods(storage_location="A32", abr_count=4, good_sku=["SKU4", "SKU4", "SKU4", "SKU4"]),
                 Put_Goods(storage_location="A33", abr_count=4, good_sku=["SKU2", "SKU2", "SKU2", "SKU2"]),
                 Put_Goods(storage_location="A34", abr_count=4, good_sku=["SKU3", "SKU3", "SKU3", "SKU3"]),
                 Put_Goods(storage_location="A41", abr_count=4, good_sku=["SKU1", "SKU1", "SKU1", "SKU1"]),
                 Put_Goods(storage_location="A42", abr_count=4, good_sku=["SKU3", "SKU3", "SKU3", "SKU3"]),
                 Put_Goods(storage_location="A43", abr_count=4, good_sku=["SKU4", "SKU4", "SKU4", "SKU4"]),
                 Put_Goods(storage_location="A44", abr_count=4, good_sku=["SKU4", "SKU4", "SKU4", "SKU4"]),
                 Put_Goods(storage_location="B11", abr_count=4, good_sku=["SKU2", "SKU2", "SKU2", "SKU2"]),
                 Put_Goods(storage_location="B12", abr_count=4, good_sku=["SKU2", "SKU2", "SKU2", "SKU2"]),
                 Put_Goods(storage_location="B13", abr_count=4, good_sku=["SKU1", "SKU1", "SKU1", "SKU1"]),
                 Put_Goods(storage_location="B14", abr_count=4, good_sku=["SKU3", "SKU3", "SKU3", "SKU3"]),
                 Put_Goods(storage_location="B21", abr_count=4, good_sku=["SKU5", "SKU5", "SKU5", "SKU5"]),
                 Put_Goods(storage_location="B22", abr_count=4, good_sku=["SKU6", "SKU6", "SKU6", "SKU6"]),
                 Put_Goods(storage_location="B23", abr_count=4, good_sku=["SKU1", "SKU1", "SKU1", "SKU1"]),
                 Put_Goods(storage_location="B24", abr_count=4, good_sku=["SKU3", "SKU3", "SKU3", "SKU3"]),
                 Put_Goods(storage_location="B31", abr_count=4, good_sku=["SKU2", "SKU2", "SKU2", "SKU2"]),
                 Put_Goods(storage_location="B32", abr_count=4, good_sku=["SKU1", "SKU1", "SKU1", "SKU1"]),
                 Put_Goods(storage_location="B33", abr_count=4, good_sku=["SKU4", "SKU4", "SKU4", "SKU4"]),
                 Put_Goods(storage_location="B34", abr_count=4, good_sku=["SKU2", "SKU2", "SKU2", "SKU2"]),
                 Put_Goods(storage_location="B41", abr_count=4, good_sku=["SKU5", "SKU5", "SKU5", "SKU5"]),
                 Put_Goods(storage_location="B42", abr_count=4, good_sku=["SKU3", "SKU3", "SKU3", "SKU3"]),
                 Put_Goods(storage_location="B43", abr_count=4, good_sku=["SKU1", "SKU1", "SKU1", "SKU1"]),
                 Put_Goods(storage_location="B44", abr_count=4, good_sku=["SKU4", "SKU4", "SKU4", "SKU4"]),
                 Put_Goods(storage_location="C11", abr_count=4, good_sku=["SKU1", "SKU1", "SKU1", "SKU1"]),
                 Put_Goods(storage_location="C12", abr_count=4, good_sku=["SKU2", "SKU2", "SKU2", "SKU2"]),
                 Put_Goods(storage_location="C13", abr_count=4, good_sku=["SKU6", "SKU6", "SKU6", "SKU6"]),
                 Put_Goods(storage_location="C14", abr_count=4, good_sku=["SKU1", "SKU1", "SKU1", "SKU1"]),
                 Put_Goods(storage_location="C21", abr_count=4, good_sku=["SKU7", "SKU7", "SKU7", "SKU7"]),
                 Put_Goods(storage_location="C22", abr_count=4, good_sku=["SKU5", "SKU5", "SKU5", "SKU5"]),
                 Put_Goods(storage_location="C23", abr_count=4, good_sku=["SKU5", "SKU5", "SKU5", "SKU5"]),
                 Put_Goods(storage_location="C24", abr_count=4, good_sku=["SKU6", "SKU6", "SKU6", "SKU6"]),
                 Put_Goods(storage_location="C31", abr_count=4, good_sku=["SKU5", "SKU5", "SKU5", "SKU5"]),
                 Put_Goods(storage_location="C32", abr_count=4, good_sku=["SKU6", "SKU6", "SKU6", "SKU6"]),
                 Put_Goods(storage_location="C33", abr_count=4, good_sku=["SKU1", "SKU1", "SKU1", "SKU1"]),
                 Put_Goods(storage_location="C34", abr_count=4, good_sku=["SKU7", "SKU7", "SKU7", "SKU7"]),
                 Put_Goods(storage_location="C41", abr_count=4, good_sku=["SKU5", "SKU5", "SKU5", "SKU5"]),
                 Put_Goods(storage_location="C42", abr_count=4, good_sku=["SKU3", "SKU3", "SKU3", "SKU3"]),
                 Put_Goods(storage_location="C43", abr_count=4, good_sku=["SKU7", "SKU7", "SKU7", "SKU7"]),
                 Put_Goods(storage_location="C44", abr_count=4, good_sku=["SKU4", "SKU4", "SKU4", "SKU4"]),
                ]

    cabinet_store.batch_putaway(put_goods)

def main():
    start()
    early_batch_shipping()
    try:
        while True:
            time.sleep(2)
                     
    except KeyboardInterrupt:
       stop()

main()
