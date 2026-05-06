from collections import deque
from src.communication.plc_client import PLCClient
from src.communication.rcs_client import RCSClient
from src.models.outbound_task_model import OutboundTask

from src.utils.logger import logger

import threading
import time

logger = logger.bind(tag="TaskManager")

class QueueTask:
    def __init__(self, task: OutboundTask):
        self.task_id = task.task_id
        self.status = "pending"  
        self.task = task
        self.start_time = None
        self.end_time = None


class TaskManager:
    def __init__(
        self,
        plc_client: PLCClient,
        rcs_client: RCSClient,
        maxrunning_tasks: int = 3,
        retention_seconds: int = 3600,
    ):

        # 初始化接收PLC和RCS的客户端
        self.plc_clients = plc_client
        self.rcs_client = rcs_client

        self.rcs_client.on_dispatch = self._on_task_dispatch

        # 最大同时处理任务数,以及任务保留时间（单位：秒）
        self.maxrunning_tasks = maxrunning_tasks
        self._retention_seconds = retention_seconds

        # 初始化三个队列，分别负责待处理、正在处理和已完成的任务
        self._pending: deque[QueueTask] = deque()
        self._running: dict[str, QueueTask] = {}
        self._completed: dict[str, QueueTask] = {}

        self._stop_event = threading.Event()
        self._stop_event.set()
        self.rlock = threading.RLock()

        logger.info("任务管理器初始化完成")

    # 启动任务管理器
    def start(self) -> None:
        if not self._stop_event.is_set():
            logger.warning("任务管理器已在运行中,忽略重复启动")
            return
        self._stop_event.clear()
        self._start_cleanup_timer()
        logger.info("任务管理器已启动")

    # 结束任务管理器
    def stop(self) -> None:
        if self._stop_event.is_set():
            logger.warning("任务管理器未在运行,忽略重复停止")
            return
        self._stop_event.set()
        logger.info("任务管理器已停止")

    # 添加新任务到待处理队列
    def add_to_pending(self, task: QueueTask) -> None:
        with self.rlock:
            self._pending.append(task)
            logger.info(f"新任务加入待处理队列: {task.task_id}")

    # 从待处理队列移除任务
    def _remove_pending(self, task_id: str) -> QueueTask:
        with self.rlock:
            for task in self._pending:
                if task.task_id == task_id:
                    self._pending.remove(task)
                    logger.info(f"任务从待处理队列移除: {task_id}")
                    return task
            logger.warning(f"待处理队列中未找到任务: {task_id}")
            return None

    # 获取当前待处理队列中的所有任务
    def get_pending_tasks(self) -> list[QueueTask]:
        with self.rlock:
            return list(self._pending)

    # 查找待处理队列中的任务
    def _find_in_pending(self, task_id: str) -> QueueTask:
        with self.rlock:
            for task in self._pending:
                if task.task_id == task_id:
                    return task
            logger.warning(f"待处理队列中未找到任务: {task_id}")
            return None

    # 将任务从待处理队列移动到正在处理队列
    def _add_to_running(self, task: QueueTask) -> None:
        with self.rlock:
            self._running[task.task_id] = task
            task.start_time = time.time()
            logger.debug(f"任务移入执行队列taskid = {task.task_id}")

    # 从正在处理队列移除任务
    def _remove_running(self, task_id: str) -> QueueTask:
        with self.rlock:
            return self._running.pop(task_id, None)

    # 获取当前正在处理队列中的所有任务
    def get_running_tasks(self) -> list[QueueTask]:
        with self.rlock:
            return list(self._running.values())

    # 获取当前正在处理队列中的任务数量
    def get_running_count(self) -> int:
        with self.rlock:
            return len(self._running)

    # 移动任务到已完成队列
    def _move_to_completed(self, task: QueueTask) -> None:
        with self.rlock:
            task.status = "completed"
            task.end_time = time.time()
            self._completed[task.task_id] = task
            logger.debug(f"任务完成: taskid = {task.task_id}")

    # 从已完成队列移除任务
    def _remove_completed(self, task_id: str) -> QueueTask:
        with self.rlock:
            return self._completed.pop(task_id, None)

    # 清理过期的已完成任务
    def _cleanup_expired_tasks(self) -> None:
        now = time.time()
        expired_ids = []

        with self.rlock:
            for task_id, task in self._completed.items():
                if now - task.end_time > self._retention_seconds:
                    expired_ids.append(task_id)

        for task_id in expired_ids:
            with self.rlock:
                self._remove_completed(task_id)
            logger.debug(f"过期任务已清理: task_id={task_id}")

    # 启动定时器定期清理过期任务
    def _start_cleanup_timer(self) -> None:
        def loop():
            while not self._stop_event.wait(30):
                self._cleanup_expired_tasks()

        t = threading.Thread(target=loop, daemon=True)
        t.start()
        logger.info("清理定时器已启动")

    # 任务下发回调函数，接收从RCS下发的新任务，并添加到待处理队列
    def _on_task_dispatch(self, task: OutboundTask) -> None:
        self.add_to_pending(QueueTask(task))