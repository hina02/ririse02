import time
from logging import getLogger

logger = getLogger(__name__)


def atimer(func):
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        result = await func(*args, **kwargs)
        end_time = time.time()
        logger.info(f"{func.__name__} Time: {round(end_time - start_time, 5)} seconds")
        return result

    return wrapper


def timer(func):
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        logger.info(
            f"{func.__name__} Time: {round(end_time - start_time, 5)} seconds"
        )
        return result

    return wrapper
