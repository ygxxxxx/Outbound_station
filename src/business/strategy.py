from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.business.task_manager import QueueTask
    from src.models.containers import CabinetStore
    from models.outbound_plan_model import OutboundPlan

from src.utils.logger import logger

logger = logger.bind(tag = "strategy")

class Strategy:
    pass


def strategy(queuetask: QueueTask, cabinet_store: CabinetStore) -> OutboundPlan:
    pass