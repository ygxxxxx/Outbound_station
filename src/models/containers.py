from dataclasses import dataclass, field

from src.utils.logger import logger
from src.models.outbound_task_model import Put_Goods

logger = logger.bind(tag = "containers")


# 单个库位信息
@dataclass
class SlotInfo:
    location_code: str    
    goods: list[str] = field(default_factory=list)

    # 判空
    @property
    def is_empty(self) -> bool:
        return len(self.goods) == 0

    # 库位上货物数量
    @property
    def qty(self) -> int:
        return len(self.goods)

    # 判断某个sku是否在该库位上
    def has_goods(self, good_sku: str) -> bool:
        return good_sku in self.goods
    
    # 将货物追加到库位的货物列表中
    def add_good(self, good_sku: str) -> None:
        self.goods.append(good_sku)

    # 将货物移除库位货物列表
    def remove_goods(self, good_sku: str) -> bool:
        if good_sku in self.goods:
            self.goods.remove(good_sku)
            return True
        return False

    # 清除库位货物列表
    def clear(self) -> None:
        self.goods = []


# 库存管理器
class CabinetStore:

    def __init__(self):
        self._slots: dict[str, SlotInfo] = {} # 用字典来表示库位

    # 建立库位
    def init_slot(self, station_prefixes: list[str] = None, layers: int = 4, positions: int = 4) -> None:
        if station_prefixes is None:
            station_prefixes = ["A", "B", "C"]
        for sp in station_prefixes:
            for layer in range(1, layers + 1):
                for position in range(1, positions + 1):
                    code = f"{sp}{layer}{position}"
                    self._slots[code] = SlotInfo(location_code = code)

    # 创建一个store实例
    @classmethod
    def create(cls, station_prefixes: list[str] = None, layers: int = 4, positions: int = 4) -> "CabinetStore":
        store = cls()
        store.init_slot(station_prefixes, layers, positions)
        return store

    # 根据库位编码获取单个库位信息
    def get_slot(self, location_code: str) -> SlotInfo | None:
        slot = self._slots.get(location_code, None)
        return slot
    
    # 获取所有库位信息
    def get_all_slots(self) -> list[SlotInfo]:
        return list(self._slots.values())
        
    # 获取指定工作站的全部库位信息
    def get_station_slot(self, station_prefix: str) -> list[SlotInfo]:
        return [slot for code, slot in self._slots.items() if code[0] == station_prefix]

    # 获得指定工作站的指定层的所有库位信息
    def get_slots_by_layer(self, station_prefix: str, layer: int) -> list[SlotInfo]:
        return [
        slot for code, slot in self._slots.items()
        if code[0] == station_prefix and code[1] == str(layer)
    ]

    # 查找指定SKU货物所在的全部库位
    def find_goods(self, goods_sku: str) -> list[SlotInfo]:
        return [slot for slot in self._slots.values() if slot.has_goods(goods_sku)]

    # 获得工作站货物总数
    def get_station_goods_count(self, station_prefix: str) -> int:
        total = 0
        for code, slot in self._slots.items():
            if code[0] == station_prefix:
                total += slot.qty
        return total
    
    # 获取所有工作站的货物总数
    def get_total_goods_count(self) -> int:
        return sum(slot.qty for slot in self._slots.values())

    # 向指定库位写入一批货物
    def put_goods_to_slot(self, location_code: str, goods_sku_list: list[str]) -> bool:
        slot = self.get_slot(location_code)
        if not slot:
            return False
        for good_sku in goods_sku_list:
            if slot.qty < 4:
                slot.add_good(good_sku)
            else:
                logger.error(f"{location_code}库位已满,{good_sku}货物无法加入")
                return False
        return True

    # 批量向库位放入货物
    def batch_putaway(self, put_goods_list: list[Put_Goods]) -> None:
        for pg in put_goods_list:
            if pg.abr_count > 0:
                self.put_goods_to_slot(pg.storage_location, pg.good_sku)
                logger.info(f"放货进入库位 {pg.storage_location}: {pg.good_sku}, 数量: {pg.abr_count}")

    # 从指定库位移除一个货物
    def remove_goods_from_slot(self, location_code: str, good_sku: str) -> bool:
        slot = self._slots.get(location_code)
        if not slot:
            return False
        return slot.remove_goods(good_sku)
    
    # 从指定库位批量移除多个货物
    def remove_goods_batch(self, location_code: str, goods_sku_list: list[str]) -> int:
        slot = self._slots.get(location_code)
        if not slot:
            return 0
        count = 0 # 移除的货物数量
        for sku in goods_sku_list:
            if slot.remove_goods(sku):
                count += 1
        return count

    # 当前层前排库位已清空后，将后排货物同步移动到机械臂能够取到的前排库位
    def move_back_goods_to_front(self, station_prefix: str, layer: int) -> dict[str, list[str]]:
        if station_prefix not in ("A", "B", "C"):
            raise ValueError(f"未知工作站编号: {station_prefix}")
        if not 1 <= layer <= 4:
            raise ValueError(f"未知库位层号: {layer}")

        front_locations = [f"{station_prefix}{layer}{position}" for position in (1, 2)]
        if any(not self._slots[location_code].is_empty for location_code in front_locations):
            raise RuntimeError(f"{station_prefix}{layer}层前排仍有货物，不能执行后排补位")

        moved_goods: dict[str, list[str]] = {}
        for back_position, front_position in ((3, 1), (4, 2)):
            back_location = f"{station_prefix}{layer}{back_position}"
            front_location = f"{station_prefix}{layer}{front_position}"
            back_slot = self._slots[back_location]
            front_slot = self._slots[front_location]

            if back_slot.is_empty:
                continue

            goods = list(back_slot.goods)
            front_slot.goods = goods
            back_slot.clear()
            moved_goods[f"{back_location}->{front_location}"] = goods

        return moved_goods
    
    # 清空指定库位的所有货物
    def clear_slot(self, location_code: str) -> bool:
        slot = self._slots.get(location_code)
        if not slot:
            return False
        slot.clear()
        return True
    
    # 清空指定工作站的所有库位
    def clear_station(self, station_prefix: str) -> None:
        slots = self.get_station_slot(station_prefix)
        for slot in slots:
            slot.clear()
    
    # 清空所有工作站的全部库位
    def clear_all(self) -> None:
        for slot in self._slots.values():
            slot.clear()

    # 将所有库位信息导出为 RCS 协议要求的 container 数组格式
    def to_rcs_container(self) -> list[dict]:
        result = []
        for code in sorted(self._slots.keys()):
            slot = self._slots[code]
            result.append({
                "storage_bin": slot.location_code,
                "qty": slot.qty,
                "goods": list(slot.goods),
            })
        return result
    
    # 解析库位编码，返回其各部分信息
    @staticmethod
    def parse_location(location_code: str) -> tuple[str, int, int]:
        return location_code[0], int(location_code[1]), int(location_code[2])
    
    # 从库位编码中提取工作站编号前缀
    @staticmethod
    def get_station_prefix(location_code: str) -> str:
        return location_code[0]
    
    # 从库位编码中提取层号
    @staticmethod
    def get_layer(location_code: str) -> int:
        return int(location_code[1])
    
    # 从库位编码中提取位置号
    @staticmethod
    def get_position(location_code: str) -> int:
        return int(location_code[2])
    
    # 判断该库位是否在靠近机械臂的前区（位置1或2）
    @staticmethod
    def is_front_position(location_code: str) -> bool:
        return location_code[2] in ("1", "2")
    
    # 判断该库位是否在远离机械臂的后区（位置3或4)
    @staticmethod
    def is_back_position(location_code: str) -> bool:
        return location_code[2] in ("3", "4")
