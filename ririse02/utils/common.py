import time
from logging import getLogger

import tiktoken
from openai import OpenAI

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
        logger.info(f"{func.__name__} Time: {round(end_time - start_time, 5)} seconds")
        return result

    return wrapper


client = OpenAI()


# token数の算出
def count_tokens(text: str, model="gpt-3.5-turbo-0613") -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.encoding_for_model(model)
    tokens = len(encoding.encode(text))
    return tokens
