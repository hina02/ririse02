import logging
from openai import OpenAI
from openai_api.models.chat import ChatPrompt

client = OpenAI()


def output_json(
    user_message: str,
    client: OpenAI,
    model: str = "gpt-3.5-turbo-1106",
    system_message: str = "json format.",
):
    messages = ChatPrompt(
        system_message=system_message,
        user_message=user_message,
    ).create_messages()

    completion = client.chat.completions.create(
        model=model,
        temperature=0.0,
        messages=messages,
        response_format={"type": "json_object"},
    )
    return completion.choices[0].message.content


# ラベル、タイプが安定すれば、---Node_labels: ["Person"]、Relationship_types: ["Relation"]---　で埋めるといい。
def output_json_to_neo4j(
    user_message: str, client: OpenAI, model: str = "gpt-3.5-turbo-1106", seed: int = 0
):
    # プロンプトの設定
    system_message = """output json format to neo4j without id. output format example is here.
        If len(Nodes) > 2, Relationship_types is required.
        {{Nodes: [{{"label", "name", "properties"}}],
        Relationships: [{{"start_node": "", "end_node": "", "type": "", "properties": {{}}}}]}}
         """
    messages = ChatPrompt(
        system_message=system_message,
        user_message=user_message,
    ).create_messages()

    # リクエスト
    response = client.chat.completions.create(
        model=model,
        temperature=0.0,
        messages=messages,
        response_format={"type": "json_object"},
        seed=seed,  # シード値固定した方が安定するかもしれない。
    )
    response_text = response.choices[0].message.content
    logging.info(response_text)
    return response_text
