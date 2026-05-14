from collections import deque
from src.communication.plc_client import PLC_Client
from src.models.outbound_task_model import OutboundTask

from src.utils.logger import logger

import threading
import time

logger = logger.bind(tag="TaskManager")

class QueueTask:
    def __init__(self, task: OutboundTask):
        self.task_id = task.task_id
        self.tesk_types = task.task_types
        self.status = "pending"  
        self.total_packages = task.packages_count
        self.task = task
        self.start_time = None
        self.end_time = None


class TaskManager:
    def __init__(self, plc_client: PLC_Client):

        # 初始化接收PLC客户端
        self.plc_clients = plc_client

        # 初始化一个任务队列（用于保存刚接收到的任务），一个任务字典（用于保存正在执行的任务和已经完成的任务）
        self._pending: deque[QueueTask] = deque()
        self._task: dict[str, QueueTask] = {}

        self.rlock = threading.RLock()

        logger.info("任务管理器初始化完成")

    # 添加新任务到待处理队列
    def add_to_pending(self, task: QueueTask) -> None:
        with self.rlock:
            self._pending.append(task)
            logger.info(f"新任务加入待处理队列: {task.task_id}")

    # 从待处理队列移除任务
    def remove_pending(self, task_id: str) -> QueueTask:
        with self.rlock:
            for task in self._pending:
                if task.task_id == task_id:
                    self._pending.remove(task)
                    logger.info(f"任务从待处理队列移除: {task_id}")
                    return task
            logger.warning(f"待处理队列中未找到任务: {task_id}")
            return None

    # 将任务从待处理队列移动到任务字典中
    def add_to_running(self, task: QueueTask) -> None:
        with self.rlock:
            task.status = "executing"
            task.start_time = str(int(time.time() * 1000))
            self._task[task.task_id] = task
            logger.debug(f"任务开始执行 taskid = {task.task_id}")

    # 任务完成状态切换，将已经完成的任务切换状态
    def complete_task(self) -> None:
        with self.rlock:
            completed_keys = [key for key, t in self._task.items() if t.status == "completed"]
            for key in completed_keys:
                del self._task[key]
            for key, t in self._task.items():
                if t.status == "executing":
                    t.status = "completed"
                    t.end_time = str(int(time.time() * 1000))

    # 查询任务执行状态
    def get_current_task_detail(self) -> dict:
        with self.rlock:
            for key, t in self._task.items():
                if t.status == "executing":
                    return {
                        "task_id": t.task_id,
                        "status": t.status,
                        "total_packages": t.total_packages,
                    }
