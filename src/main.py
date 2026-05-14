from src.business import request_handle
from src.utils.logger import logger

import time


logger = logger.bind(tag="Main")


def main():
    request_handle.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        request_handle.stop()
        logger.info("程序已停止")


if __name__ == "__main__":
    main()
