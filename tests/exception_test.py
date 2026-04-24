# tests/test_exception.py
import pytest
from src.exception.exception import (
    OutboundStationError,
    CommunicationError,
    PLCCommunicationError,
    RCSCommunicationError,
    VisionGateCommunicationError,
    ABRTimeoutError,
    DeviceError,
    EmergencyStopError,
    DeviceFailureError,
    GripperFailureError,
    ConveyorJamError,
    BusinessProcessError,
    SortingError,
    VisionGateScanError,
    ParameterError,
    PackageInfoError,
)
from src.utils.logger import logger

logger = logger.bind(tag="test_exception")  # 绑定日志标签为测试模块

# 基本实例化测试
class TestInstantiation:
    def test_outbound_station_error_minimal(self):
        e = OutboundStationError()
        assert e.message is None
        assert e.device_name is None
        assert e.details is None
        logger.info("test_outbound_station_error_minimal → 正常通过")

    def test_outbound_station_error_full(self):
        e = OutboundStationError(message="测试异常", device_name="PLC_01", details="连接断开")
        assert str(e) == "测试异常 | 设备名称: PLC_01 | 详情: 连接断开"
        logger.info("test_outbound_station_error_full → 正常通过")

    def test_outbound_station_error_message_only(self):
        e = OutboundStationError(message="仅消息")
        assert str(e) == "仅消息"
        logger.info("test_outbound_station_error_message_only → 正常通过")

    def test_plc_communication_error(self):
        e = PLCCommunicationError(message="PLC连接中断", device_name="PLC_01")
        assert "PLC连接中断" in str(e)
        assert "PLC_01" in str(e)
        logger.info("test_plc_communication_error → 正常通过")

    def test_rcs_communication_error(self):
        e = RCSCommunicationError(message="RCS通信失败", details="服务未启动")
        assert "RCS通信失败" in str(e)
        assert "服务未启动" in str(e)
        logger.info("test_rcs_communication_error → 正常通过")

    def test_vision_gate_communication_error(self):
        e = VisionGateCommunicationError(message="视觉门通信超时")
        assert "视觉门通信超时" in str(e)
        logger.info("test_vision_gate_communication_error → 正常通过")

    def test_abr_timeout_error(self):
        e = ABRTimeoutError(message="ABR对接超时")
        assert "ABR对接超时" in str(e)
        logger.info("test_abr_timeout_error → 正常通过")

    def test_emergency_stop_error(self):
        e = EmergencyStopError(message="急停信号触发", device_name="工作站1")
        assert "急停信号触发" in str(e)
        logger.info("test_emergency_stop_error → 正常通过")

    def test_device_failure_error(self):
        e = DeviceFailureError(message="工作站设备故障")
        assert "工作站设备故障" in str(e)
        logger.info("test_device_failure_error → 正常通过")

    def test_gripper_failure_error(self):
        e = GripperFailureError(message="夹爪抓取失败")
        assert "夹爪抓取失败" in str(e)
        logger.info("test_gripper_failure_error → 正常通过")

    def test_conveyor_jam_error(self):
        e = ConveyorJamError(message="输送线堵料")
        assert "输送线堵料" in str(e)
        logger.info("test_conveyor_jam_error → 正常通过")

    def test_sorting_error(self):
        e = SortingError(message="分拣异常")
        assert "分拣异常" in str(e)
        logger.info("test_sorting_error → 正常通过")

    def test_vision_gate_scan_error(self):
        e = VisionGateScanError(message="视觉门扫码异常")
        assert "视觉门扫码异常" in str(e)
        logger.info("test_vision_gate_scan_error → 正常通过")

    def test_parameter_error(self):
        e = ParameterError(message="参数偏差", expected_value="100", actual_value="200")
        assert "参数偏差" in str(e)
        assert "期望值: 100" in str(e)
        assert "实际值: 200" in str(e)
        logger.info("test_parameter_error → 正常通过")

    def test_parameter_error_no_values(self):
        e = ParameterError(message="参数偏差")
        assert "参数偏差" in str(e)
        logger.info("test_parameter_error_no_values → 正常通过")

    def test_package_info_error(self):
        e = PackageInfoError(message="包裹信息异常", expected_value="5kg", actual_value="10kg")
        assert "包裹信息异常" in str(e)
        assert "期望值: 5kg" in str(e)
        assert "实际值: 10kg" in str(e)
        logger.info("test_package_info_error → 正常通过")


# 继承关系测试
class TestInheritance:
    def test_all_inherit_from_outbound_station_error(self):
        classes = [
            CommunicationError, PLCCommunicationError, RCSCommunicationError,
            VisionGateCommunicationError, ABRTimeoutError,
            DeviceError, EmergencyStopError, DeviceFailureError,
            GripperFailureError, ConveyorJamError,
            BusinessProcessError, SortingError, VisionGateScanError,
            ParameterError, PackageInfoError,
        ]
        for cls in classes:
            assert issubclass(cls, OutboundStationError), f"{cls.__name__} 未继承 OutboundStationError"
        logger.info("test_all_inherit_from_outbound_station_error → 正常通过")

    def test_communication_errors_inherit_connection_error(self):
        for cls in [CommunicationError, PLCCommunicationError,
                     RCSCommunicationError, VisionGateCommunicationError]:
            assert issubclass(cls, ConnectionError), f"{cls.__name__} 未继承 ConnectionError"
        logger.info("test_communication_errors_inherit_connection_error → 正常通过")

    def test_abr_timeout_inherits_timeout_error(self):
        assert issubclass(ABRTimeoutError, TimeoutError)
        logger.info("test_abr_timeout_inherits_timeout_error → 正常通过")

    def test_device_errors_inherit_runtime_error(self):
        for cls in [EmergencyStopError, DeviceFailureError,
                     GripperFailureError, ConveyorJamError]:
            assert issubclass(cls, DeviceError), f"{cls.__name__} 未继承 DeviceError"
        logger.info("test_device_errors_inherit_runtime_error → 正常通过")

    def test_business_errors(self):
        assert issubclass(SortingError, BusinessProcessError)
        assert issubclass(VisionGateScanError, BusinessProcessError)
        logger.info("test_business_errors → 正常通过")

    def test_parameter_errors_inherit_value_error(self):
        assert issubclass(ParameterError, ValueError)
        assert issubclass(PackageInfoError, ValueError)
        logger.info("test_parameter_errors_inherit_value_error → 正常通过")

    def test_package_info_inherits_parameter_error(self):
        assert issubclass(PackageInfoError, ParameterError)
        logger.info("test_package_info_inherits_parameter_error → 正常通过")


# 捕获测试
class TestCatching:
    def test_catch_plc_by_communication_error(self):
        with pytest.raises(CommunicationError):
            raise PLCCommunicationError(message="PLC断开")
        logger.info("test_catch_plc_by_communication_error → 正常通过")

    def test_catch_plc_by_connection_error(self):
        with pytest.raises(ConnectionError):
            raise PLCCommunicationError(message="PLC断开")
        logger.info("test_catch_plc_by_connection_error → 正常通过")

    def test_catch_plc_by_outbound_station_error(self):
        with pytest.raises(OutboundStationError):
            raise PLCCommunicationError(message="PLC断开")
        logger.info("test_catch_plc_by_outbound_station_error → 正常通过")

    def test_catch_rcs_by_communication_error(self):
        with pytest.raises(CommunicationError):
            raise RCSCommunicationError(message="RCS断开")
        logger.info("test_catch_rcs_by_communication_error → 正常通过")

    def test_catch_vision_gate_comm_by_communication_error(self):
        with pytest.raises(CommunicationError):
            raise VisionGateCommunicationError(message="视觉门通信异常")
        logger.info("test_catch_vision_gate_comm_by_communication_error → 正常通过")

    def test_catch_abr_by_timeout_error(self):
        with pytest.raises(TimeoutError):
            raise ABRTimeoutError(message="ABR超时")
        logger.info("test_catch_abr_by_timeout_error → 正常通过")

    def test_catch_abr_by_outbound_station_error(self):
        with pytest.raises(OutboundStationError):
            raise ABRTimeoutError(message="ABR超时")
        logger.info("test_catch_abr_by_outbound_station_error → 正常通过")

    def test_catch_emergency_by_device_error(self):
        with pytest.raises(DeviceError):
            raise EmergencyStopError(message="急停")
        logger.info("test_catch_emergency_by_device_error → 正常通过")

    def test_catch_gripper_by_device_error(self):
        with pytest.raises(DeviceError):
            raise GripperFailureError(message="夹爪失败")
        logger.info("test_catch_gripper_by_device_error → 正常通过")

    def test_catch_conveyor_by_device_error(self):
        with pytest.raises(DeviceError):
            raise ConveyorJamError(message="堵料")
        logger.info("test_catch_conveyor_by_device_error → 正常通过")

    def test_catch_device_failure_by_device_error(self):
        with pytest.raises(DeviceError):
            raise DeviceFailureError(message="设备故障")
        logger.info("test_catch_device_failure_by_device_error → 正常通过")

    def test_catch_sorting_by_business_error(self):
        with pytest.raises(BusinessProcessError):
            raise SortingError(message="分拣异常")
        logger.info("test_catch_sorting_by_business_error → 正常通过")

    def test_catch_vision_scan_by_business_error(self):
        with pytest.raises(BusinessProcessError):
            raise VisionGateScanError(message="扫码异常")
        logger.info("test_catch_vision_scan_by_business_error → 正常通过")

    def test_catch_parameter_by_value_error(self):
        with pytest.raises(ValueError):
            raise ParameterError(message="参数偏差")
        logger.info("test_catch_parameter_by_value_error → 正常通过")

    def test_catch_package_info_by_parameter_error(self):
        with pytest.raises(ParameterError):
            raise PackageInfoError(message="包裹信息异常")
        logger.info("test_catch_package_info_by_parameter_error → 正常通过")

    def test_catch_all_by_outbound_station_error(self):
        all_errors = [
            PLCCommunicationError(message="a"),
            RCSCommunicationError(message="b"),
            VisionGateCommunicationError(message="c"),
            ABRTimeoutError(message="d"),
            EmergencyStopError(message="e"),
            DeviceFailureError(message="f"),
            GripperFailureError(message="g"),
            ConveyorJamError(message="h"),
            SortingError(message="i"),
            VisionGateScanError(message="j"),
            ParameterError(message="k"),
            PackageInfoError(message="l"),
        ]
        for err in all_errors:
            try:
                raise err
            except OutboundStationError:
                pass
            else:
                pytest.fail(f"{type(err).__name__} 未被 OutboundStationError 捕获")
        logger.info("test_catch_all_by_outbound_station_error → 正常通过")


# 输出格式测试
class TestStrFormat:
    def test_only_message(self):
        e = EmergencyStopError(message="急停")
        assert str(e) == "急停"
        logger.info("test_only_message → 正常通过")

    def test_message_with_device(self):
        e = GripperFailureError(message="抓取失败", device_name="夹爪1")
        assert str(e) == "抓取失败 | 设备名称: 夹爪1"
        logger.info("test_message_with_device → 正常通过")

    def test_message_with_all_fields(self):
        e = PLCCommunicationError(message="连接断开", device_name="PLC_01", details="心跳超时")
        result = str(e)
        assert "连接断开" in result
        assert "设备名称: PLC_01" in result
        assert "详情: 心跳超时" in result
        logger.info("test_message_with_all_fields → 正常通过")

    def test_parameter_error_str(self):
        e = ParameterError(message="速度参数偏差", expected_value="1.5", actual_value="3.0")
        result = str(e)
        assert "速度参数偏差" in result
        assert "期望值: 1.5" in result
        assert "实际值: 3.0" in result
        logger.info("test_parameter_error_str → 正常通过")

    def test_package_info_inherits_parameter_str(self):
        e = PackageInfoError(message="重量异常", expected_value="5kg", actual_value="8kg")
        result = str(e)
        assert "重量异常" in result
        assert "期望值: 5kg" in result
        assert "实际值: 8kg" in result
        logger.info("test_package_info_inherits_parameter_str → 正常通过")


if __name__ == "__main__":
    logger.info("==================== 开始异常类测试 ====================")
    pytest.main([__file__, "-v"])