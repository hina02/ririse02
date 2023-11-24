import time
import logging
import openai
import tiktoken
import spacy
from spacy.language import Language


def atimer(func):
    async def wrapper(*args, **kwargs):
        start = time.time()
        result = await func(*args, **kwargs)
        end = time.time()
        logging.info(f"Time: {end - start} seconds")
        return result

    return wrapper


def timer(func):
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        logging.info(
            f"Function {func.__name__} took {round(end_time - start_time, 4)} seconds to run."
        )
        return result

    return wrapper


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


# 日本語テキストを句読点で分割する関数（デフォルトは読点で分割）
# 日本語モデルをグローバルに1回だけロード
nlp = spacy.load("ja_core_news_sm")


# 更新設定
@Language.component("split_by_punctuation")
def split_by_punctuation(doc):
    punct_positions = [i for i, token in enumerate(doc) if token.text in ["、", "。"]]

    # 句読点の次の位置を新しい文の境界として設定
    for pos in punct_positions:
        if pos + 1 < len(doc):
            doc[pos + 1].is_sent_start = True
    return doc


# パイプラインの前処理を変更してカスタムの分割関数を使用する
if "custom_sentence_segmenter" not in nlp.pipe_names:
    nlp.add_pipe(
        "split_by_punctuation", name="custom_sentence_segmenter", before="parser"
    )


def split_japanese_text(text):
    doc = nlp(text)
    tokens = list(doc.sents)
    return tokens
