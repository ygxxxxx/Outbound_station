from dataclasses import dataclass, field
from collections import defaultdict
from typing import Optional

# 单个库位信息
@dataclass
class SlotInfo:
    location_id: str
    station_id: int
    goods_ids: list[str] = field(default_factory=list)

    # 判空
    @property
    def is_empty(self) -> bool:
        return len(self.goods_ids) == 0

    # 判断库位是否满
    @property
    def is_full(self) -> bool:
        return len(self.goods_ids) == 4

    # 剩余容量
    @property
    def remaining_capacity(self) -> int:
        return 4 - len(self.goods_ids)

# 库存管理器
class CabinetStore:
    def __init__(self):
        # 库位编号
        self._by_location: dict[str, SlotInfo] = {}
        # 工作站编号
        self._by_station: dict[int, dict[str, SlotInfo]] = defaultdict(dict)
        # 货物id
        self._goods_index: dict[str, list[str]] = defaultdict(list)

    # 初始化库位
    @classmethod
    def create_from_config(
        cls,
        station_count: int = 3, # 工作站数量
        cabinet_layers: int = 4, # 每台工作站层数
        stacks_per_layer: int = 4, # 每层库位数量
        cabinet_prefixes: Optional[list[str]] = None, # 柜前缀
    ) -> "CabinetStore":
        store = cls() 
        if cabinet_prefixes is None:
            cabinet_prefixes = [chr(ord("A") + i) for i in range(station_count)]
        for station_id in range(1, station_count + 1):
            prefix = cabinet_prefixes[station_id - 1]
            for layer in range(1, cabinet_layers + 1):
                for stack in range(1, stacks_per_layer + 1):
                    location_id = f"{prefix}-{layer:02d}-{stack:02d}"
                    store.add_slot(SlotInfo(
                        location_id=location_id,
                        station_id=station_id,
                    ))
        return store

    # 添加库位
    def add_slot(self, slot: SlotInfo) -> None:
        self._by_location[slot.location_id] = slot
        self._by_station[slot.station_id][slot.location_id] = slot
        for gid in slot.goods_ids:
            self._goods_index[gid].append(slot.location_id)

    # 更新库位
    def update_slot(self, location_id: str, goods_ids: list[str]) -> None:
        slot = self._by_location.get(location_id)
        if slot is None:
            return
        for gid in slot.goods_ids:
            locs = self._goods_index.get(gid, [])
            if location_id in locs:
                locs.remove(location_id) # 清楚久关联
        slot.goods_ids = list(goods_ids) # 把货物列表添加到库位信息中
        for gid in slot.goods_ids:
            self._goods_index[gid].append(location_id) #添加新关联

    # 移除货物
    def remove_goods(self, location_id: str, goods_id: str) -> None:
        slot = self._by_location.get(location_id)
        if slot and goods_id in slot.goods_ids:
            slot.goods_ids.remove(goods_id)
            locs = self._goods_index.get(goods_id, [])
            if location_id in locs:
                locs.remove(location_id)

    # 获得单个库位信息
    def get_slot(self, location_id: str) -> Optional[SlotInfo]:
        return self._by_location.get(location_id)

    # 找到货物位置
    def find_by_goods(self, goods_id: str) -> list[SlotInfo]:
        loc_ids = self._goods_index.get(goods_id, [])
        return [self._by_location[lid] for lid in loc_ids if lid in self._by_location]

    # 获得工作站全部库位信息
    def find_by_station(self, station_id: int) -> list[SlotInfo]:
        return list(self._by_station[station_id].values())

    # 获得全部库位信息
    def get_all(self) -> list[SlotInfo]:
        return list(self._by_location.values())

    # 获得全部货物数量
    def get_all_goods_count(self) -> int:
        return sum(len(s.goods_ids) for s in self._by_location.values())

    # 获得单个工作站货物数量
    def get_station_goods_count(self, station_id: int) -> int:
        return sum(len(s.goods_ids) for s in self._by_station[station_id].values())
    

if __name__ == "__main__":
    cabint = CabinetStore.create_from_config(station_count = 3, cabinet_layers = 4, stacks_per_layer = 4)
    print(cabint.get_all())
    print(cabint.find_by_station(2))
