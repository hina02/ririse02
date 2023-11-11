# バッチ処理。chat.completionsでの利用はできない。価格は大差ないので、十分。
# ただ、JSON形式での出力もできない。

from openai import OpenAI

client = OpenAI()


def batch(
    text: str, iterate: int, max_tokens: int, model: str = "gpt-3.5-turbo-instruct"
):
    prompts = [text] * iterate
    response = client.completions.create(
        model=model,
        prompt=prompts,
        max_tokens=max_tokens,
    )

    # match completions to prompts by index
    results = [""] * len(prompts)
    for choice in response.choices:
        results[choice.index] = prompts[choice.index] + choice.text

    return results


results = batch("Once upon a time,", 10, 20)
