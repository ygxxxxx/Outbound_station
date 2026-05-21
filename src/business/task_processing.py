from src.communication.plc_service import PLC_Service
from src.business.state_machine import StateMachine, StationState
from src.business.strategy import strategy
from src.business.task_manager import TaskManager, QueueTask
from src.models.containers import CabinetStore

from src.utils.logger import logger

import threading
import time

logger = logger.bind(tag="Task_Processing")

class Task_Processing:
    def __init__(self, 
            taskmanger: TaskManager = None, 
            plc_service: PLC_Service = None, 
            state_machine: StateMachine = None, 
            cabinet_store: CabinetStore = None
        ):
        self.taskmanger = taskmanger
        self.plc_service = plc_service
        self.state_machine = state_machine
        self.cabinet_store = cabinet_store

        self._stop_event = threading.Event() 


    def start(self):
        self._stop_event.clear()
        threading.Thread(target= self._check_pending_loop, daemon= True).start()
        logger.info("开始监听任务队列")

    # 循环查询_pending
    def _check_pending_loop(self) -> None:
        while not self._stop_event.is_set():
            with self.taskmanger.rlock:
                if not self.taskmanger._pending:
                    queuetask = None
                else:
                    queuetask = self.taskmanger._pending[0]  

            if queuetask is None:
                self._stop_event.wait(timeout=1.0)
                continue

            try:
                logger.info(f"开始解析任务：{queuetask.task_id}")
                self.state_machine.transition(queuetask.task.station_id, StationState.READY, reason="解析任务")
                # 解析任务类型
                if queuetask.task_types == "putaway":
                    self._putway_task_processing(queuetask) # 如果是放货任务进放货任务处理函数
                    
                elif queuetask.task_types == "outbound":
                    self._outbound_task_processing(queuetask) # 如果是出库任务进出库任务处理函数
                
            except Exception as e:
                logger.error(f"任务解析失败，留在队列中: {queuetask.task_id}, {e}")
                self._stop_event.wait(timeout=5.0)  # 失败后等一会再重试
        

    @staticmethod
    def _parse_station_id(station_id_str: str) -> int:
        mapping = {"A": 1, "B": 2, "C": 3}
        return mapping.get(station_id_str, 1)

    @staticmethod
    def _parse_layer_from_location(storage_location: str) -> int:
        if len(storage_location) >= 2 and storage_location[1].isdigit():
            return int(storage_location[1])
        return 0

    @staticmethod
    def _parse_position_from_location(storage_location: str) -> int:
        if len(storage_location) >= 3 and storage_location[2].isdigit():
            return int(storage_location[2])
        return 0

    def _putway_task_processing(self, queuetask: QueueTask) -> None:
        logger.info(f"开始处理放货任务{queuetask.task_id}")

        station_id = self._parse_station_id(queuetask.task.station_id)

        # layer -> {"front": bool, "back": bool} 记录每层前区(1,2位)和后区(3,4位)是否有货
        layer_goods_info: dict[int, dict[str, bool]] = {}
        for pg in queuetask.task.put_goods:
            if pg.abr_count > 0:
                layer = self._parse_layer_from_location(pg.storage_location)
                position = self._parse_position_from_location(pg.storage_location)
                if not (1 <= layer <= 4 and 1 <= position <= 4):
                    continue
                if layer not in layer_goods_info:
                    layer_goods_info[layer] = {"front": False, "back": False}
                if position in (1, 2):
                    layer_goods_info[layer]["front"] = True
                elif position in (3, 4):
                    layer_goods_info[layer]["back"] = True

        all_layers = set(range(1, 5))
        goods_layers = set(layer_goods_info.keys())
        empty_layers = all_layers - goods_layers

        # 无货物的层：下发跳过指令，禁止传送带运行
        for layer in sorted(empty_layers):
            self.plc_service.command_cabinet_no_box(station_id, layer)

        # 所有层都没有货物，直接跳过
        if not goods_layers:
            self.taskmanger.remove_pending(queuetask.task_id)
            self.taskmanger.add_to_running(queuetask)
            logger.warning(f"工作站{station_id} 所有层均无货物，直接标记放货完成")
            self.state_machine.transition(station_id, StationState.WAITING_DELIVERY, reason="放货任务开始(无货物)")
            self.state_machine.transition(station_id, StationState.DELIVERED, reason="无货物直接完成")
            return

        logger.info(f"工作站{station_id} 有货物的层: {sorted(goods_layers)}, 详情: {layer_goods_info}")
        
        # 将任务从待执行任务转移至运行中
        self.taskmanger.remove_pending(queuetask.task_id)
        self.taskmanger.add_to_running(queuetask)

        # 开始执行任务
        self.plc_service.command_cabinet_place(station_id)
        self.state_machine.transition(station_id, StationState.WAITING_DELIVERY, reason="放货任务开始")

        # 超时时间戳
        total_timeout = time.time() + 60
        while not self._stop_event.is_set():
            # 触发急停，停止放货
            if self.plc_service.is_emergency_stop():
                logger.error(f"工作站{station_id} 放货过程中急停触发")
                self.state_machine.transition(station_id, StationState.ERROR, reason="急停")
                return
            
            # 如果没有都到位则标志位会变成False，光电都触发则保持True
            all_triggered = True
            for layer in sorted(goods_layers):
                info = layer_goods_info[layer]
                front = self.plc_service.is_photo_triggered(station_id, layer, "front") # 读取前光电状态
                need_back = info["front"] and info["back"] # 前后层如果都需要判断返回True
                if need_back:
                    back = self.plc_service.is_photo_triggered(station_id, layer, "back") # 读取后光电状态
                    if not (front and back):
                        logger.debug(f"工作站{station_id} {layer}层需前后光电 front={front} back={back}")
                        all_triggered = False
                else:
                    if not front:
                        logger.debug(f"工作站{station_id} {layer}层需前光电 front={front}")
                        all_triggered = False

            # 如果这一层ABR是有货的，但是触发库位传送带超时报警说明出现了意外，货物一直没到位没法触发光电
            for layer in sorted(goods_layers):
                if self.plc_service.is_cabinet_timeout(station_id, layer):
                    logger.error(f"工作站{station_id} {layer}层传送带超时，光电未检测到货物")
                    self.state_machine.transition(station_id, StationState.ERROR, reason=f"{layer}层放货超时")
                    return

            # 如果标志位是True，说明光电都按照货物位置正常触发了
            if all_triggered:
                logger.info(f"工作站{station_id} 所有货物层光电判定完成，放货完成")
                break

            if time.time() > total_timeout:
                logger.error(f"工作站{station_id} 放货超时")
                self.state_machine.transition(station_id, StationState.ERROR, reason="放货超时")
                return

            self._stop_event.wait(timeout=0.2)

        # 货物写入库位管理 
        # 按层分组 put_goods
        layer_put_goods: dict[int, list] = {}
        for pg in queuetask.task.put_goods:
            if pg.abr_count > 0:
                layer = self._parse_layer_from_location(pg.storage_location)
                if layer not in layer_put_goods:
                    layer_put_goods[layer] = []
                layer_put_goods[layer].append(pg)

        station_prefix = queuetask.task.station_id
        back_to_front_map = {"3": "1", "4": "2"}

        for layer in sorted(layer_put_goods.keys()):
            info = layer_goods_info[layer]

            if info["front"]:
                # 该层有前区货物，传送带提前停止，所有货物在原位
                for pg in layer_put_goods[layer]:
                    actual_location = pg.storage_location
                    logger.info(
                        f"写入库位: {actual_location}, "
                        f"SKU: {pg.good_sku}, 数量: {pg.abr_count}"
                    )
                    self.cabinet_store.put_goods_to_slot(actual_location, pg.good_sku)
            else:
                # 该层只有后区货物，传送带将货物送到前区，映射 3→1, 4→2
                for pg in layer_put_goods[layer]:
                    original = pg.storage_location
                    original_pos = original[2]
                    actual_pos = back_to_front_map.get(original_pos, original_pos)
                    actual_location = f"{station_prefix}{layer}{actual_pos}"
                    logger.info(
                        f"写入库位: {actual_location} (原始: {original}), "
                        f"SKU: {pg.good_sku}, 数量: {pg.abr_count}"
                    )
                    self.cabinet_store.put_goods_to_slot(actual_location, pg.good_sku)

        # 任务执行完毕，修改任务机状态，将任务在任务管理器中的状态调整至完成
        self.state_machine.transition(station_id, StationState.DELIVERED, reason="放货完成")
        self.taskmanger.complete_task()

    def _outbound_task_processing(self, queuetask: QueueTask) -> None:
        
        # 将任务放入出库策略当中进行计算，得出Outboundplan


        self.strategy
        
        
        # 将任务从准备队列转移至正在执行中
        self.taskmanger.remove_pending(queuetask.task_id)
        self.taskmanger.add_to_running(queuetask)
        

        # 按照Outboundplan计划执行任务
        self._execute_plan(Outboundplan)



        self.taskmanger.complete_task()

    def stop(self) -> None:
        self._stop_event.set()
        logger.info("任务处理已停止")