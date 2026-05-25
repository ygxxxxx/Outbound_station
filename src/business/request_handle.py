from src.business.task_manager import TaskManager, QueueTask
from src.communication.rcs_sever import CmdType
from src.communication.plc_service import PLC_Service
from src.business.state_machine import StateMachine, StationState
from src.models.outbound_task_model import OutboundTask, Package, Put_Goods
from src.models.containers import CabinetStore
from src.utils.logger import logger
from src.utils.response import build_common_response


import time

logger = logger.bind(tag="Request_Handle")


# 将接收到的信息进行实例化存入数据模型
def parse_outbound_task(body_dict: dict) -> OutboundTask:
    packages = []
    for p in body_dict.get("packages", []):
        packages.append(Package(
            package_id = p.get("package_id"),
            box_type = p.get("box_type"),
            face_sheet = p.get("face_sheet"),
            logistics = p.get("logistics"),
            manual_process_type = p.get("manual_process_type"),
            packaging_line = p.get("packaging_line"),
            count = p.get("count"),
            goods = p.get("goods", []),
        ))

    put_goods = []
    for g in body_dict.get("put_goods", []):
        put_goods.append(Put_Goods(
            storage_location = g.get("storage_location"),
            abr_count = g.get("abr_count", 0),
            good_sku = g.get("good_sku", []),
        ))

    return OutboundTask(
        task_id = body_dict["task_id"],
        task_types = body_dict["task_types"],
        timestamp = body_dict.get("timestamp", (int(time.time() * 1000))),
        station_id = body_dict.get("station_id", "A"),
        packages_count = body_dict.get("package_count", 0),
        packages = packages,
        put_goods = put_goods,
    )


# 处理状态端口接收到的请求
def handle_status_request(state_machine: StateMachine, plc_service: PLC_Service, cabinet_store: CabinetStore, cmd: int, body_dict: dict) -> dict:
    try:
        if cmd == CmdType.OUTBOUND_TASK_DETAIL_REQ:                 # 查询出库任务执行情况
            business_data = state_machine.get_task_execution_detail()
            return build_common_response(business_data)

        elif cmd == CmdType.OUTBOUND_STORAGE_REQ:                   # 查询出库工作站库位信息
            business_data = {"container": cabinet_store.to_rcs_container()}
            return build_common_response(business_data)

        elif cmd == CmdType.OUTBOUND_STATUS_REQ:                    # 查询出库工作站状态
            business_data = state_machine.get_outbound_station_status()     
            return build_common_response(business_data)

        elif cmd == CmdType.OUTBOUND_WORKSTATION_PLC_STATUS_REQ:    # 查询工作站PLC状态
            business_data = plc_service.get_to_rcs()
            return build_common_response(business_data)
        
        elif cmd == CmdType.OUTBOUND_BATCH_REQ:                     # 批量查询出库全部信息
            business_data = {}
            try:
                business_data["container"] = cabinet_store.to_rcs_container()
            except Exception as e:
                logger.error(f"批量查询 container 失败: {e}")
                business_data["container_error"] = str(e)
            for name, method in [
                ("task_detail", state_machine.get_task_execution_detail),
                ("status", state_machine.get_outbound_station_status),
            ]:
                try:
                    business_data.update(method())
                except Exception as e:
                    logger.error(f"批量查询 {name} 失败: {e}")
                    business_data[f"{name}_error"] = str(e)
            try:
                business_data.update(plc_service.get_to_rcs())
            except Exception as e:
                logger.error(f"批量查询 plc_status 失败: {e}")

            return build_common_response(business_data)
        
        else:
            return build_common_response(ret_code=-1, err_msg=f"不支持的状态查询类型: {cmd}")
    except Exception as e:
        logger.error(f"状态查询处理异常: cmd={cmd}, error={e}")
        return build_common_response(ret_code=-1, err_msg=f"内部错误: {e}")


# 处理任务端口接收到的请求
def handle_task_request(task_manager: TaskManager, state_machine: StateMachine, plc_service: PLC_Service, cmd: int, body_dict: dict) -> dict:
    try:
        if cmd == CmdType.OUTBOUND_TASK_DISPATCH_REQ:               # 收到RCS下发的出库任务
            try:
                task = parse_outbound_task(body_dict)  # 将任务导入数据模型
                queue_task = QueueTask(task)

            except (KeyError, ValueError, TypeError) as e:
                logger.error(f"任务解析失败{e}")
                return build_common_response(ret_code=-1, err_msg=f"任务数据格式错误: {e}")
            
            state_machine.transition(body_dict.get("station_id", "A"), StationState.READY, reason="收到任务")
            task_manager.add_to_pending(queue_task)
            logger.info(f"收到任务: {task.task_id}")
            return build_common_response()

        elif cmd == CmdType.CLEAR_CONVEYOR_TIMEOUT_REQ:             # 收到RCS要求解除库位传送带运行超时指令
            
            plc_service.clear_all_cabinet_timeouts(1)
            plc_service.clear_all_cabinet_timeouts(2)
            plc_service.clear_all_cabinet_timeouts(3)
            
            return build_common_response()

        else:
            return build_common_response(ret_code=-1, err_msg=f"不支持的任务类型: {cmd}")
    except Exception as e:
        logger.error(f"任务接收处理异常: cmd={cmd}, error={e}")
        return build_common_response(ret_code=-1, err_msg=f"内部错误: {e}")






    
