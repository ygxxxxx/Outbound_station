from src.business.task_manager import TaskManager, QueueTask
from src.communication.rcs_sever import CmdType, RCS_Sever
from src.communication.plc_client import PLC_Client
from src.models.outbound_task_model import OutboundTask
from src.utils.logger import logger
from src.utils.response import build_common_response
from src.config.settings import load_config


logger = logger.bind(tag = "request_handle")

class Request_Handle:
    def __init__(self) -> None:
        pass


    # 这个函数作为回调传给 rcs_sever
    # 当状态端口收到任何请求时，rcs_sever 会调用这个函数
    def handle_status_request(cmd: int, body_dict: dict) -> dict:
        if cmd == CmdType.OUTBOUND_TASK_DETAIL_REQ:          # 1000
            business_data = state_machine.get_task_execution_detail()
            return build_common_response(business_data)
        
        elif cmd == CmdType.OUTBOUND_STORAGE_REQ:             # 1001
            business_data = state_machine.get_storage_info()
            return build_common_response(business_data)
        
        elif cmd == CmdType.OUTBOUND_STATUS_REQ:              # 1002
            business_data = state_machine.get_outbound_station_status()
            return build_common_response(business_data)
        
        elif cmd == CmdType.OUTBOUND_SUBDEVICE_REQ:           # 1006
            if sorting_manager:
                business_data = sorting_manager.get_subdevice_status()
            else:
                business_data = {"has_error": 0, "status_change": 0}
            return build_common_response(business_data)
        
        elif cmd == CmdType.OUTBOUND_BATCH_REQ:                # 1100
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

    # 这个函数作为回调传给 rcs_sever
    # 当任务端口收到任何请求时，rcs_sever 会调用这个函数
    def handle_task_request(cmd: int, body_dict: dict) -> dict:
        if cmd == CmdType.OUTBOUND_TASK_DISPATCH_REQ:         # 2000
            task = parse_outbound_task(body_dict)
            task_manager.on_task_dispatch(task)
            return build_common_response()                    # 仅返回通用字段
        
        else:
            return build_common_response(ret_code=-1, err_msg=f"不支持的任务类型: {cmd}")
