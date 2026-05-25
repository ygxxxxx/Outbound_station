import yaml
from pathlib import Path
from dataclasses import dataclass, field
from src.utils.logger import logger

logger = logger.bind(tag = "settings") # 绑定日志标签为settings模块

# config文件中的设置内容，全部使用数据类
@dataclass
class PLCConfig:
    plc_address: str = "0.0.0.0"
    plc_port: int = 9000
    timeout: int = 5000
    read_cycle: int = 10


@dataclass
class RCSConfig:
    rcs_address: str = "0.0.0.0"
    rcs_port: int = 9001


@dataclass
class WorkStationConfig:
    count: int = 3
    gripper_count: int = 2
    cabinet_layers: int = 4
    max_stacks_per_layer: int = 4


@dataclass
class ConveyorConfig:
    cargo_min_spacing: int = 300
    speed: float = 1.5


@dataclass
class ScannerConfig:
    scanner_timeout: int = 500


@dataclass
class ExceptionConfig:
    max_retry_count: int = 3

@dataclass
class VisionGateConfig:
    vg_address: str = "0.0.0.0"
    vg_port: int = 9000

@dataclass
class Config:
    plcconfig: PLCConfig = field(default_factory=PLCConfig)
    rcsconfig: RCSConfig = field(default_factory=RCSConfig)
    workstationconfig: WorkStationConfig = field(default_factory=WorkStationConfig)
    conveyorconfig: ConveyorConfig = field(default_factory=ConveyorConfig)
    scannerconfig: ScannerConfig = field(default_factory=ScannerConfig)
    exceptionconfig: ExceptionConfig = field(default_factory=ExceptionConfig)
    visiongateconfig: VisionGateConfig = field(default_factory=VisionGateConfig)


# 加载config文件
def load_config(path="config/config.yaml"):
    p = Path(path)
    try:
        data = {}
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

        plc_data = data.get("PLC", {})
        rcs_data = data.get("RCS", {})
        workstation_data = data.get("workstation", {})
        conveyor_data = data.get("conveyor", {})
        scanner_data = data.get("scanner", {})
        exception_data = data.get("exception", {})
        visiongate_data = data.get("visiongate", {})

        logger.info("config文件导入成功")

        return Config(
            plcconfig=PLCConfig(
                plc_address=plc_data.get("plc_address", PLCConfig.plc_address),
                plc_port=plc_data.get("plc_port", PLCConfig.plc_port),
                timeout=plc_data.get("timeout", PLCConfig.timeout),
                read_cycle=plc_data.get("read_cycle", PLCConfig.read_cycle),
            ),
            rcsconfig=RCSConfig(
                rcs_address=rcs_data.get("rcs_address", RCSConfig.rcs_address),
                rcs_port=rcs_data.get("rcs_port", RCSConfig.rcs_port),
            ),
            workstationconfig=WorkStationConfig(
                count=workstation_data.get("count", WorkStationConfig.count),
                gripper_count=workstation_data.get(
                    "gripper_count", WorkStationConfig.gripper_count
                ),
                cabinet_layers=workstation_data.get(
                    "cabinet_layers", WorkStationConfig.cabinet_layers
                ),
                max_stacks_per_layer=workstation_data.get(
                    "max_stacks_per_layer", WorkStationConfig.max_stacks_per_layer
                ),
            ),
            conveyorconfig=ConveyorConfig(
                cargo_min_spacing=conveyor_data.get(
                    "cargo_min_spacing", ConveyorConfig.cargo_min_spacing
                ),
                speed=conveyor_data.get("speed", ConveyorConfig.speed),
            ),
            scannerconfig=ScannerConfig(
                scanner_timeout=scanner_data.get(
                    "scanner_timeout", ScannerConfig.scanner_timeout
                ),
            ),
            exceptionconfig=ExceptionConfig(
                max_retry_count=exception_data.get(
                    "max_retry_count", ExceptionConfig.max_retry_count
                ),
            ),
            visiongateconfig=VisionGateConfig(
                vg_address=visiongate_data.get(
                    "vg_address", VisionGateConfig.vg_address
                ),
                vg_port=visiongate_data.get(
                    "vg_port", VisionGateConfig.vg_port
                )
            )
        )
    except Exception as e:
        logger.error(f"加载config文件失败: {e}")
        return Config()
    # 出现异常返回默认Config()


config = load_config()
