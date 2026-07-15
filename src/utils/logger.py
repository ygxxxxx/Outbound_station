from loguru import logger
import sys
from pathlib import Path

# 日志目录基于项目根目录定位，不依赖当前工作目录 CWD
LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)  # 建立logs文件夹

logger.remove()  # 移除logger默认配置
logger.configure(extra={"tag": "unknown"})

# 添加日志处理器，日志输出到控制台和文件
# 显示格式： 时间 - 日志级别 - 模块名 - 函数名 - 行号 - 日志消息
logger.add(
    sys.stdout,
    level="DEBUG",
    format="{time:HH:mm:ss} - {level:<8} - {extra[tag]} - {function} - {line} - {message} ",
    enqueue=True,
    backtrace=True,
    diagnose=True,
)

# 显示格式： 时间 - 日志级别 - 模块名 - 函数名 - 行号 - 日志消息
# 日志文件达到50MB时自动切分，保留30天的日志，过期日志自动删除，旧日志压缩为gz格式
# 显示异常的完整堆栈与变量信息
logger.add(
    str(LOG_DIR / "log.log"),
    level="INFO",
    format="{time} - {level:<8} - {extra[tag]} - {function} - {line} - {message} ",
    rotation="50 MB",
    retention="30 days",
    compression="gz",
    enqueue=True,
    backtrace=True,
    diagnose=True,
)
