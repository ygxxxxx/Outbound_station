from src.communication.rcs_sever import RCS_Sever
from src.communication.plc_service import PLC_Service
from src.communication.vision_gate import VisionGateClient
from src.business.request_handle import parse_outbound_task, handle_status_request, handle_task_request
from src.business.state_machine import StateMachine
from src.business.task_manager import TaskManager
from src.business.task_processing import Task_Processing
from src.config.settings import config
from src.utils.logger import logger

from functools import partial

import time


logger = logger.bind(tag="Main")


rcs: RCS_Sever = None
plc: PLC_Service = None
vis: VisionGateClient = None
state: VisionGateClient = None
taskmanger: TaskManager = None
taskprocessing: Task_Processing = None


def start():
    global rcs, plc, vis, state, taskmanger, taskprocessing
    
    state = StateMachine()
    taskmanager = TaskManager()

    on_status = partial(handle_status_request, state)
    on_task = partial(handle_task_request, taskmanager, state)

    rcs = RCS_Sever(
        on_status_request=on_status,
        on_task_request=on_task,)
    plc = PLC_Service()
    vis = VisionGateClient()
    
    taskprocessing = Task_Processing(taskmanger, plc, state)







def main():
    start()


