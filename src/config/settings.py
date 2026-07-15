import os
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from src.utils.logger import logger

# 项目根目录（基于本文件位置定位，不依赖当前工作目录 CWD）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

logger = logger.bind(tag = "settings") # 绑定日志标签为settings模块

# config文件中的设置内容，全部使用数据类
@dataclass
class PLCConfig:
    plc_address: str = "192.168.1.88"
    plc_port: int = 502
    timeout: int = 5
    read_cycle: int = 10

@dataclass
class RCSConfig:
    rcs_address: str = "0.0.0.0"
    rcs_status_port: int = 23310
    rcs_task_port: int = 23311

@dataclass
class VisionGateConfig:
    vg_address: str = "127.0.0.1"
    vg_port: int = 23320

@dataclass
class ExceptionConfig:
    max_retry_count: int = 3


@dataclass
class Config:
    plcconfig: PLCConfig = field(default_factory=PLCConfig)
    rcsconfig: RCSConfig = field(default_factory=RCSConfig)
    exceptionconfig: ExceptionConfig = field(default_factory=ExceptionConfig)
    visiongateconfig: VisionGateConfig = field(default_factory=VisionGateConfig)


# 加载config文件
def load_config(path=None):
    if path is None:
        # 支持环境变量 OUTBOUND_CONFIG 指定配置文件，便于部署时切换配置而不改代码
        env_path = os.environ.get("OUTBOUND_CONFIG")
        path = Path(env_path) if env_path else PROJECT_ROOT / "config" / "config.yaml"
    p = Path(path)
    try:
        data = {}
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

        plc_data = data.get("PLC", {})
        rcs_data = data.get("RCS", {})
        visiongate_data = data.get("visiongate", {})
        exception_data = data.get("exception", {})
        

        logger.info("config文件导入成功")

        return Config(
            plcconfig=PLCConfig(
                plc_address = plc_data.get("plc_address", PLCConfig.plc_address),
                plc_port = plc_data.get("plc_port", PLCConfig.plc_port),
                timeout = plc_data.get("timeout", PLCConfig.timeout),
                read_cycle = plc_data.get("read_cycle", PLCConfig.read_cycle),
            ),
            rcsconfig = RCSConfig(
                rcs_address = rcs_data.get("rcs_address", RCSConfig.rcs_address),
                rcs_status_port = rcs_data.get("rcs_status_port", RCSConfig.rcs_status_port),
                rcs_task_port = rcs_data.get("rcs_task_port", RCSConfig.rcs_task_port),
            ),
            exceptionconfig = ExceptionConfig(
                max_retry_count = exception_data.get(
                    "max_retry_count", ExceptionConfig.max_retry_count
                ),
            ),
            visiongateconfig = VisionGateConfig(
                vg_address=visiongate_data.get(
                    "vg_address", VisionGateConfig.vg_address
                ),
                vg_port = visiongate_data.get(
                    "vg_port", VisionGateConfig.vg_port
                )
            )
        )
    except Exception as e:
        logger.error(f"加载config文件失败: {e}")
        return Config()
    # 出现异常返回默认Config()


config = load_config()
