import pytest
from src.models.containers import SlotInfo, CabinetStore
from src.models.outbound_task_model import Put_Goods


class TestSlotInfo:

    def test_new_slot_is_empty(self):
        slot = SlotInfo(location_code="A11")
        assert slot.is_empty is True
        assert slot.qty == 0

    def test_add_good(self):
        slot = SlotInfo(location_code="A11")
        slot.add_good("sku-1")
        assert slot.qty == 1
        assert slot.goods == ["sku-1"]
        assert slot.is_empty is False

    def test_add_multiple_goods(self):
        slot = SlotInfo(location_code="A11")
        slot.add_good("sku-1")
        slot.add_good("sku-2")
        slot.add_good("sku-1")
        assert slot.qty == 3
        assert slot.goods == ["sku-1", "sku-2", "sku-1"]

    def test_has_goods(self):
        slot = SlotInfo(location_code="A11")
        slot.add_good("sku-1")
        assert slot.has_goods("sku-1") is True
        assert slot.has_goods("sku-999") is False

    def test_remove_goods_success(self):
        slot = SlotInfo(location_code="A11")
        slot.add_good("sku-1")
        slot.add_good("sku-2")
        result = slot.remove_goods("sku-1")
        assert result is True
        assert slot.qty == 1
        assert slot.goods == ["sku-2"]

    def test_remove_goods_not_found(self):
        slot = SlotInfo(location_code="A11")
        slot.add_good("sku-1")
        result = slot.remove_goods("sku-999")
        assert result is False
        assert slot.qty == 1

    def test_clear(self):
        slot = SlotInfo(location_code="A11")
        slot.add_good("sku-1")
        slot.add_good("sku-2")
        slot.clear()
        assert slot.is_empty is True
        assert slot.qty == 0


class TestCabinetStoreInit:

    def test_create_default(self):
        store = CabinetStore.create()
        assert len(store._slots) == 48

    def test_create_contains_all_locations(self):
        store = CabinetStore.create()
        for prefix in ["A", "B", "C"]:
            for layer in range(1, 5):
                for pos in range(1, 5):
                    code = f"{prefix}{layer}{pos}"
                    assert code in store._slots
                    assert store._slots[code].location_code == code

    def test_create_all_slots_empty(self):
        store = CabinetStore.create()
        for slot in store._slots.values():
            assert slot.is_empty is True

    def test_create_nonexistent_location(self):
        store = CabinetStore.create()
        assert store.get_slot("D11") is None
        assert store.get_slot("A55") is None
        assert store.get_slot("A1") is None
        assert store.get_slot("") is None

    def test_init_slot_default_prefixes(self):
        store = CabinetStore()
        store.init_slot()
        assert len(store._slots) == 48
        assert "A11" in store._slots
        assert "C44" in store._slots

    def test_init_slot_custom(self):
        store = CabinetStore()
        store.init_slot(station_prefixes=["X", "Y"], layers=2, positions=2)
        assert len(store._slots) == 8
        assert "X11" in store._slots
        assert "Y22" in store._slots
        assert "X33" not in store._slots


class TestCabinetStoreQuery:

    def test_get_slot(self):
        store = CabinetStore.create()
        slot = store.get_slot("A21")
        assert slot is not None
        assert slot.location_code == "A21"

    def test_get_slot_not_found(self):
        store = CabinetStore.create()
        assert store.get_slot("Z99") is None

    def test_get_all_slot(self):
        store = CabinetStore.create()
        all_slots = store.get_all_slots()
        assert len(all_slots) == 48

    def test_get_station_slot(self):
        store = CabinetStore.create()
        a_slots = store.get_station_slot("A")
        assert len(a_slots) == 16
        for slot in a_slots:
            assert slot.location_code[0] == "A"

    def test_get_station_slot_empty_prefix(self):
        store = CabinetStore.create()
        z_slots = store.get_station_slot("Z")
        assert len(z_slots) == 0

    def test_get_slots_by_layer(self):
        store = CabinetStore.create()
        layer2 = store.get_slots_by_layer("A", 2)
        assert len(layer2) == 4
        for slot in layer2:
            assert slot.location_code == f"A2{slot.location_code[2]}"
        codes = sorted([s.location_code for s in layer2])
        assert codes == ["A21", "A22", "A23", "A24"]

    def test_find_goods(self):
        store = CabinetStore.create()
        store.put_goods_to_slot("A11", ["sku-1", "sku-2"])
        store.put_goods_to_slot("B23", ["sku-1"])
        result = store.find_goods("sku-1")
        assert len(result) == 2
        codes = sorted([s.location_code for s in result])
        assert codes == ["A11", "B23"]

    def test_find_goods_not_found(self):
        store = CabinetStore.create()
        assert store.find_goods("sku-999") == []

    def test_get_station_goods_count(self):
        store = CabinetStore.create()
        store.put_goods_to_slot("A11", ["sku-1", "sku-2"])
        store.put_goods_to_slot("A12", ["sku-3"])
        store.put_goods_to_slot("B11", ["sku-4"])
        assert store.get_station_goods_count("A") == 3
        assert store.get_station_goods_count("B") == 1
        assert store.get_station_goods_count("C") == 0

    def test_get_total_goods_count(self):
        store = CabinetStore.create()
        assert store.get_total_goods_count() == 0
        store.put_goods_to_slot("A11", ["sku-1"])
        store.put_goods_to_slot("C44", ["sku-2", "sku-3"])
        assert store.get_total_goods_count() == 3


class TestCabinetStorePutGoods:

    def test_put_goods_to_slot(self):
        store = CabinetStore.create()
        result = store.put_goods_to_slot("A11", ["sku-1", "sku-2"])
        assert result is True
        slot = store.get_slot("A11")
        assert slot.goods == ["sku-1", "sku-2"]
        assert slot.qty == 2

    def test_put_goods_to_nonexistent_slot(self):
        store = CabinetStore.create()
        result = store.put_goods_to_slot("Z99", ["sku-1"])
        assert result is False

    def test_put_goods_to_slot_full(self):
        store = CabinetStore.create()
        result = store.put_goods_to_slot("A11", ["sku-1", "sku-2", "sku-3", "sku-4"])
        assert result is True
        assert store.get_slot("A11").qty == 4
        result = store.put_goods_to_slot("A11", ["sku-5"])
        assert result is False
        assert store.get_slot("A11").qty == 4

    def test_put_goods_exceed_capacity_mid_batch(self):
        store = CabinetStore.create()
        store.put_goods_to_slot("A11", ["sku-1", "sku-2", "sku-3"])
        result = store.put_goods_to_slot("A11", ["sku-4", "sku-5"])
        assert result is False
        slot = store.get_slot("A11")
        assert slot.qty == 4
        assert "sku-5" not in slot.goods

    def test_put_empty_list(self):
        store = CabinetStore.create()
        result = store.put_goods_to_slot("A11", [])
        assert result is True
        assert store.get_slot("A11").is_empty is True


class TestCabinetStoreBatchPutaway:

    def test_batch_putaway(self):
        store = CabinetStore.create()
        put_goods_list = [
            Put_Goods(storage_location="A11", abr_count=2, good_sku=["sku-1", "sku-2"]),
            Put_Goods(storage_location="B23", abr_count=1, good_sku=["sku-3"]),
        ]
        store.batch_putaway(put_goods_list)
        assert store.get_slot("A11").goods == ["sku-1", "sku-2"]
        assert store.get_slot("B23").goods == ["sku-3"]

    def test_batch_putaway_skip_zero_count(self):
        store = CabinetStore.create()
        put_goods_list = [
            Put_Goods(storage_location="A11", abr_count=0, good_sku=[]),
            Put_Goods(storage_location="A12", abr_count=1, good_sku=["sku-1"]),
        ]
        store.batch_putaway(put_goods_list)
        assert store.get_slot("A11").is_empty is True
        assert store.get_slot("A12").goods == ["sku-1"]


class TestCabinetStoreRemoveGoods:

    def test_remove_goods_from_slot(self):
        store = CabinetStore.create()
        store.put_goods_to_slot("A11", ["sku-1", "sku-2"])
        result = store.remove_goods_from_slot("A11", "sku-1")
        assert result is True
        assert store.get_slot("A11").goods == ["sku-2"]

    def test_remove_goods_not_in_slot(self):
        store = CabinetStore.create()
        store.put_goods_to_slot("A11", ["sku-1"])
        result = store.remove_goods_from_slot("A11", "sku-999")
        assert result is False
        assert store.get_slot("A11").qty == 1

    def test_remove_goods_from_nonexistent_slot(self):
        store = CabinetStore.create()
        result = store.remove_goods_from_slot("Z99", "sku-1")
        assert result is False

    def test_remove_goods_batch(self):
        store = CabinetStore.create()
        store.put_goods_to_slot("A11", ["sku-1", "sku-2", "sku-3"])
        count = store.remove_goods_batch("A11", ["sku-1", "sku-3"])
        assert count == 2
        assert store.get_slot("A11").goods == ["sku-2"]

    def test_remove_goods_batch_partial(self):
        store = CabinetStore.create()
        store.put_goods_to_slot("A11", ["sku-1"])
        count = store.remove_goods_batch("A11", ["sku-1", "sku-999"])
        assert count == 1

    def test_remove_goods_batch_nonexistent_slot(self):
        store = CabinetStore.create()
        count = store.remove_goods_batch("Z99", ["sku-1"])
        assert count == 0


class TestCabinetStoreClear:

    def test_clear_slot(self):
        store = CabinetStore.create()
        store.put_goods_to_slot("A11", ["sku-1", "sku-2"])
        result = store.clear_slot("A11")
        assert result is True
        assert store.get_slot("A11").is_empty is True

    def test_clear_slot_nonexistent(self):
        store = CabinetStore.create()
        result = store.clear_slot("Z99")
        assert result is False

    def test_clear_station(self):
        store = CabinetStore.create()
        store.put_goods_to_slot("A11", ["sku-1"])
        store.put_goods_to_slot("A22", ["sku-2"])
        store.put_goods_to_slot("B11", ["sku-3"])
        store.clear_station("A")
        assert store.get_slot("A11").is_empty is True
        assert store.get_slot("A22").is_empty is True
        assert store.get_slot("B11").goods == ["sku-3"]

    def test_clear_all(self):
        store = CabinetStore.create()
        store.put_goods_to_slot("A11", ["sku-1"])
        store.put_goods_to_slot("B22", ["sku-2"])
        store.put_goods_to_slot("C33", ["sku-3"])
        store.clear_all()
        assert store.get_total_goods_count() == 0
        for slot in store._slots.values():
            assert slot.is_empty is True


class TestCabinetStoreRCSExport:

    def test_to_rcs_container_format(self):
        store = CabinetStore.create()
        container = store.to_rcs_container()
        assert len(container) == 48
        assert container[0]["storage_bin"] == "A11"
        assert container[-1]["storage_bin"] == "C44"
        for item in container:
            assert "storage_bin" in item
            assert "qty" in item
            assert "goods" in item

    def test_to_rcs_container_with_goods(self):
        store = CabinetStore.create()
        store.put_goods_to_slot("A11", ["sku-1", "sku-2"])
        container = store.to_rcs_container()
        a11_item = next(item for item in container if item["storage_bin"] == "A11")
        assert a11_item["qty"] == 2
        assert a11_item["goods"] == ["sku-1", "sku-2"]
        empty_item = next(item for item in container if item["storage_bin"] == "A12")
        assert empty_item["qty"] == 0
        assert empty_item["goods"] == []

    def test_to_rcs_container_sorted(self):
        store = CabinetStore.create()
        container = store.to_rcs_container()
        codes = [item["storage_bin"] for item in container]
        assert codes == sorted(codes)

    def test_to_rcs_container_is_copy(self):
        store = CabinetStore.create()
        store.put_goods_to_slot("A11", ["sku-1"])
        container = store.to_rcs_container()
        container[0]["goods"].append("sku-fake")
        assert store.get_slot("A11").goods == ["sku-1"]


class TestCabinetStoreParseLocation:

    def test_parse_location(self):
        assert CabinetStore.parse_location("B23") == ("B", 2, 3)

    def test_get_station_prefix(self):
        assert CabinetStore.get_station_prefix("C41") == "C"

    def test_get_layer(self):
        assert CabinetStore.get_layer("A32") == 3

    def test_get_position(self):
        assert CabinetStore.get_position("A14") == 4

    def test_is_front_position(self):
        assert CabinetStore.is_front_position("A11") is True
        assert CabinetStore.is_front_position("A12") is True
        assert CabinetStore.is_front_position("A13") is False
        assert CabinetStore.is_front_position("A14") is False

    def test_is_back_position(self):
        assert CabinetStore.is_back_position("A13") is True
        assert CabinetStore.is_back_position("A14") is True
        assert CabinetStore.is_back_position("A11") is False
        assert CabinetStore.is_back_position("A12") is False
