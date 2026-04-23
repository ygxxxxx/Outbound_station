# tests/utils_logger_test.py
import sys
from pathlib import Path

# 这一行是关键！把项目根目录加入 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 现在可以正常导入了
from src.utils.logger import logger

logger = logger.bind(name = "utils_logger_test")
# 测试
logger.info("日志测试")