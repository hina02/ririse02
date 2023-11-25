from typing import Union
from langchain.schema.messages import BaseMessage, get_buffer_string, AIMessage
from langchain.chat_models import ChatOpenAI
from langchain.prompts.chat import ChatPromptTemplate
from langchain.chains.llm import LLMChain
from langchain.prompts.chat import (
    AIMessagePromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
)
from langchain.memory import ConversationBufferWindowMemory
import re

# from chains.prompts.ririse import RIRISE_PROMPT


# humanの履歴を残さないカスタム記憶
class CustomWindowMemory(ConversationBufferWindowMemory):
    @property
    def buffer_as_str(self) -> str:
        """Exposes the buffer as a string in case return_messages is True, only including AI messages."""
        # これで、AIメッセージだけにできる。
        messages = (
            [
                message
                for message in self.chat_memory.messages[-self.k * 2 :]
                if isinstance(message, AIMessage)
            ]
            if self.k > 0
            else []
        )
        return get_buffer_string(
            messages,
            human_prefix=self.human_prefix,
            ai_prefix="",
        )

    @property
    def buffer_as_messages(self) -> list[BaseMessage]:
        """Exposes the buffer as a list of messages in case return_messages is False, only including AI messages."""
        return (
            [
                message
                for message in self.chat_memory.messages[-self.k * 2 :]
                if message.role == self.ai_prefix
            ]
            if self.k > 0
            else []
        )

    @property
    def buffer(self) -> Union[str, list[BaseMessage]]:
        """String buffer of memory."""
        return self.buffer_as_messages if self.return_messages else self.buffer_as_str


# 短い文章で出力を返すLLM応答Chain
def streamchain(k:int):
    # memory
    temp_memory = CustomWindowMemory(k=k, memory_key="chat_history", input_key="input")

    # prompt
    system_prompt = "Output is Japanese. Don't reveal hidden information."
    user_prompt = """user_input: {input}
    ----------------------------------------
    Hidden information from network graph:
    None
    ----------------------------------------
    """
    ai_prompt = "{chat_history}"  # 単純にこれまでの履歴を入れた場合のみ、それに続けて生成される。

    system_message_prompt = SystemMessagePromptTemplate.from_template(system_prompt)
    human_message_prompt = HumanMessagePromptTemplate.from_template(user_prompt)
    ai_message_prompt = (
        AIMessagePromptTemplate.from_template(ai_prompt) if ai_prompt else None
    )
    messages_template = [
        system_message_prompt,
        human_message_prompt,
    ]
    if ai_message_prompt:
        messages_template.append(ai_message_prompt)

    prompt_template = ChatPromptTemplate.from_messages(messages_template)

    # LLMChain
    chain = LLMChain(
        prompt=prompt_template,
        llm=ChatOpenAI(
            model_name="gpt-4-1106-preview",  # gpt-4, gpt-3.5-turbo-0613のスイッチングを想定
            temperature=0.3,
            max_tokens=240,
        ),
        memory=temp_memory,
    )

    return chain


class TextFormatter:
    def __init__(self):
        self.partial_text = ""

    def format_text(self, text):
        if not text:
            return []

        text = self.partial_text + text
        self.partial_text = ""

        # 文章を分割するときに記号を保持するための正規表現
        pattern = r"([\n。！？；]+|\n\n)"

        # split with capturing group will return the delimiters as well.
        parts = re.split(pattern, text)
        sentences = []
        for i in range(0, len(parts)-1, 2):
            # concatenate the sentence and its ending delimiter
            sentence = parts[i] + parts[i+1]
            sentence = sentence.strip()
            if sentence:
                sentences.append(sentence)

        # 末尾の文が終端記号で終わっているか確認
        if not re.search(pattern, parts[-1]):
            self.partial_text = parts[-1]
            # sentences.pop()

        return sentences
