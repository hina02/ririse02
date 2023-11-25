import time
from logging import getLogger

logger = getLogger(__name__)


def atimer(func):
    async def wrapper(*args, **kwargs):
        start = time.time()
        result = await func(*args, **kwargs)
        end = time.time()
        logger.info(f"Time: {end - start} seconds")
        return result

    return wrapper


def timer(func):
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        logger.info(
            f"Function {func.__name__} took {round(end_time - start_time, 4)} seconds to run."
        )
        return result

    return wrapper
