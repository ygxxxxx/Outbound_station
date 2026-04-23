from loguru import logger   
import sys
 
logger.remove()  # Remove the default logger 
handler_id = logger.add("test_loguru.log", level="WARNING", rotation="1 MB",
                        format="{time} - {level} - {message}")

logger.add(sys.stdout, format="{time} - {level} - <level>{message}</level> - {extra}")

with logger.contextualize(programer = "want"):
    logger.debug("This is a debug message")
    logger.info("This is an info message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")
    logger.critical("This is a critical message")


child = logger.bind(foo = "bar", hello = "world")

child.info("mes from child logger")


@logger.contextualize(bar = "baz")
def test():
    logger.info("mes from test func")

test()


try:
    1/0
except:
    logger.exception("An error occurred")

with logger.catch(ZeroDivisionError, level = "WARNING"):
    1 / 0 

@logger.catch()
def test2():
    logger.info("mes from test func")