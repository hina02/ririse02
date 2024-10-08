from openai import OpenAI
import tiktoken
import openai
from logging import getLogger

logger = getLogger(__name__)

client = OpenAI()

# token数の算出
def count_tokens(text: str, model="gpt-3.5-turbo-0613") -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.encoding_for_model(model)
    tokens = len(encoding.encode(text))
    return tokens


# ベクトル化
def get_embedding(text: str, model: str = "text-embedding-ada-002") -> list[float]:
    text = text.replace("\n", " ")
    result = client.embeddings.create(input=[text], model=model).data[0].embedding
    return result


# モデレーター
async def moderation(text: str) -> dict:
    """Returns an object containing the moderation label and the moderation output.
    response.categories: list of strings, response.flagged: boolean"""
    response = openai.moderations.create(input=text).results[0]
    return response
