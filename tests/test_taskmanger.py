import src.business.state_machine as _sm
import src.communication.plc_service as _ps
from src.communication.rcs_sever import RCS_Sever
from src.communication.plc_service import PLC_Service
from src.business.task_manager import TaskManager
from src.business.request_handle import handle_task_request, handle_status_request
from src.business.task_processing import Task_Processing
from src.models.containers import CabinetStore

from functools import partial

import time

rcs: RCS_Sever = None
state = None
taskmanager: TaskManager = None
taskprocessing: Task_Processing = None
cabinet_store: CabinetStore = None


class _DummyStateMachine:
    def __init__(self, *args, **kwargs):
        pass
    def transition(self, *args, **kwargs):
        pass
    def get_task_execution_detail(self):
        return {}
    def get_storage_info(self):
        return {}
    def get_outbound_station_status(self):
        return {}
    def get_workstation_plc_status(self):
        return {}
    def clear_cabinet_timeout(self):
        pass


class _DummyPLCService:
    def __init__(self, *args, **kwargs):
        pass
    def command_cabinet_skip(self, *args, **kwargs):
        pass
    def command_cabinet_place(self, *args, **kwargs):
        pass
    def is_emergency_stop(self):
        return False
    def is_photo_triggered(self, *args, **kwargs):
        return True
    def is_cabinet_timeout(self, *args, **kwargs):
        return False


_sm.StateMachine = _DummyStateMachine
_ps.PLC_Service = _DummyPLCService


def start():
    global rcs, plc, state, taskmanger, taskprocessing, cabinet_store

    state = _DummyStateMachine()
    taskmanager = TaskManager()
    cabinet_store = CabinetStore.create(station_prefixes=["A", "B", "C"])

    on_status = partial(handle_status_request, state, cabinet_store)
    on_task = partial(handle_task_request, taskmanager, state)

    rcs = RCS_Sever(
        status_host = "0.0.0.0",
        status_port = 23310,
        task_host = "0.0.0.0",
        task_port = 23311,
        on_status_request=on_status,
        on_task_request=on_task,)
    
    plc = _DummyPLCService()
    taskprocessing = Task_Processing(taskmanager, plc, state, cabinet_store)

    rcs.start()
    taskprocessing.start()


def stop():
    rcs.stop()
    taskprocessing.stop()

def main():
    start()
    try:
        while True:
            time.sleep(2)
                     
    except KeyboardInterrupt:
       stop()


main()
    