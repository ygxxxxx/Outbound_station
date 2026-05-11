from dataclasses import dataclass
from typing import Optional


# 出库工作站顶层异常类
@dataclass
class OutboundStationError(Exception):
    message: Optional[str] = None
    device_name: Optional[str] = None
    details: Optional[str] = None

    # 允许日志打印错误详细信息
    def __str__(self):
        mes = [self.message]
        if self.device_name is not None:
            mes.append(f"设备名称: {self.device_name}")
        if self.details is not None:
            mes.append(f"详情: {self.details}")
        return " | ".join(mes)

# 通信异常基类
@dataclass
class CommunicationError(OutboundStationError, ConnectionError):
    pass

# PLC通信异常
@dataclass    
class PLCCommunicationError(CommunicationError):
    pass

# RCS通信异常
@dataclass
class RCSCommunicationError(CommunicationError):
    pass

# 协议版本错误
@dataclass
class ProtocolVersionError(RCSCommunicationError):
    seq: int = 0
    cmd: int = 0
    remaining: bytes = b''

# 数据解析错误
@dataclass
class ProtocolDataError(RCSCommunicationError):
    seq: int = 0
    cmd: int = 0
    remaining: bytes = b''

# 视觉门通信异常
@dataclass
class VisionGateCommunicationError(CommunicationError):
    pass

# ABR对接超时异常
@dataclass
class ABRTimeoutError(OutboundStationError, TimeoutError):
    pass

# 设备异常基类
@dataclass
class DeviceError(OutboundStationError):
    pass

# 急停信号
@dataclass
class EmergencyStopError(DeviceError):
    pass

# 工作站设备故障
@dataclass
class DeviceFailureError(DeviceError):
    pass

# 夹爪抓取失败
@dataclass
class GripperFailureError(DeviceError):
    pass

# 输送线堵料
@dataclass
class ConveyorJamError(DeviceError):
    pass

# 业务流程异常基类
@dataclass
class BusinessProcessError(OutboundStationError):
    pass

# 分拣异常
@dataclass
class SortingError(BusinessProcessError):
    pass

# 视觉门扫码异常
@dataclass
class VisionGateScanError(BusinessProcessError):
    pass

# 参数异常基类
@dataclass
class ParameterError(OutboundStationError, ValueError):
    expected_value: Optional[str] = None
    actual_value: Optional[str] = None

    def __str__(self):
        mes = [super().__str__()]
        if self.expected_value is not None:
            mes.append(f"期望值: {self.expected_value}")
        if self.actual_value is not None:
            mes.append(f"实际值: {self.actual_value}")
        return " | ".join(mes)

# 包裹信息异常
@dataclass
class PackageInfoError(ParameterError):
    pass