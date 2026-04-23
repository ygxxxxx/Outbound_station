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