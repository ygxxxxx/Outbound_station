from src.business.task_manager import TaskManager, QueueTask
from src.communication.rcs_sever import CmdType, RCS_Sever
from src.communication.plc_client import PLC_Client
from src.business.state_machine import StateMachine
from src.models.outbound_task_model import OutboundTask, Package, Put_Goods
from src.utils.logger import logger
from src.utils.response import build_common_response
from src.config.settings import config

import time

logger = logger.bind(tag="RequestHandle")


# 将接收到的信息进行实例化存入数据模型
def parse_outbound_task(body_dict: dict) -> OutboundTask:
    packages = []
    for p in body_dict.get("packages", []):
        packages.append(Package(
            package_id=p.get("package_id"),
            box_type=p.get("box_type"),
            face_sheet=p.get("face_sheet"),
            logistics=p.get("logistics"),
            manual_process_type=p.get("manual_process_type"),
            packaging_line=p.get("packaging_line"),
            count=p.get("count"),
            goods=p.get("goods", []),
        ))

    put_goods = []
    for g in body_dict.get("put_goods", []):
        put_goods.append(Put_Goods(
            storage_location=g["storage_location"],
            abr_count=g["abr_count"],
            good_sku=g.get("good_sku", []),
        ))

    return OutboundTask(
        task_id=body_dict["task_id"],
        task_types=body_dict["task_types"],
        timestamp=body_dict.get("timestamp", str(int(time.time() * 1000))),
        packages=packages,
        put_goods=put_goods,
    )

# 处理状态端口接收到的请求
def handle_status_request(cmd: int, body_dict: dict) -> dict:
    if cmd == CmdType.OUTBOUND_TASK_DETAIL_REQ:
        business_data = state_machine.get_task_execution_detail()
        return build_common_response(business_data)

    elif cmd == CmdType.OUTBOUND_STORAGE_REQ:
        business_data = state_machine.get_storage_info()
        return build_common_response(business_data)

    elif cmd == CmdType.OUTBOUND_STATUS_REQ:
        business_data = state_machine.get_outbound_station_status()
        return build_common_response(business_data)

    elif cmd == CmdType.OUTBOUND_SUBDEVICE_REQ:
        if sorting_manager:
            business_data = sorting_manager.get_subdevice_status()
        else:
            business_data = {"has_error": 0, "status_change": 0}
        return build_common_response(business_data)

    elif cmd == CmdType.OUTBOUND_BATCH_REQ:
        business_data = {}
        business_data.update(state_machine.get_task_execution_detail())
        business_data.update(state_machine.get_storage_info())
        business_data.update(state_machine.get_outbound_station_status())
        if sorting_manager:
            business_data.update(sorting_manager.get_subdevice_status())
        else:
            business_data.update({"has_error": 0, "status_change": 0})
        return build_common_response(business_data)

    else:
        return build_common_response(ret_code=-1, err_msg=f"不支持的状态查询类型: {cmd}")


# 处理任务端口接收到的请求
def handle_task_request(cmd: int, body_dict: dict) -> dict:
    if cmd == CmdType.OUTBOUND_TASK_DISPATCH_REQ:
        task = parse_outbound_task(body_dict)
        queue_task = QueueTask(task)
        task_manager.add_to_pending(queue_task)
        logger.info(f"收到出库任务: {task.task_id}")
        return build_common_response()

    else:
        return build_common_response(ret_code=-1, err_msg=f"不支持的任务类型: {cmd}")

# 工作站状态变更
def _on_state_transition(station_id: int, old_state, new_state) -> None:
    logger.info(f"S{station_id} 状态变更: {old_state.value} -> {new_state.value}")



plc_client: PLC_Client = None
task_manager: TaskManager = None
state_machine: StateMachine = None
sorting_manager = None
rcs_sever: RCS_Sever = None


def start() -> None:
    global plc_client, task_manager, state_machine, sorting_manager, rcs_sever

    plc_client = PLC_Client(
        host=config.plcconfig.plc_address,
        port=config.plcconfig.plc_port,
        timeout=config.plcconfig.timeout / 1000,
    )

    task_manager = TaskManager(plc_client=plc_client)

    state_machine = StateMachine(
        host_id="outbound_station",
        station_ids=list(range(1, config.workstationconfig.count + 1)),
        plc_client=plc_client,
        on_transition=_on_state_transition,
    )
    sorting_manager = None

    rcs_sever = RCS_Sever(
        status_host=config.rcsconfig.rcs_address,
        status_port=config.rcsconfig.rcs_port,
        task_host=config.rcsconfig.rcs_address,
        task_port=config.rcsconfig.rcs_port + 1,
        on_status_request=handle_status_request,
        on_task_request=handle_task_request,
    )

    plc_client.connect_to_plc()
    state_machine.start()
    rcs_sever.start()
    logger.info("系统启动完成")


def stop() -> None:
    rcs_sever.stop()
    state_machine.stop()
    plc_client.plc_close()
    logger.info("系统已停止")


    
