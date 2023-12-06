import openai
import tiktoken


# token数の算出
def count_tokens(text: str, model_name: str = "gpt-3.5-turbo") -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.encoding_for_model(model_name)
    tokens = len(encoding.encode(text))
    return tokens


# embedding
def openai_embeddings(text: str) -> list[float]:
    model = "text-embedding-ada-002"
    return openai.Embedding.create(input=[text], model=model)["data"][0]["embedding"]

