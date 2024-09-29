import os

from dotenv import load_dotenv

load_dotenv()
openai_api_key: str = os.getenv("OPENAI_API_KEY")
VOICEPEAK_PATH = os.environ.get("VOICEPEAK_PATH")

import openai

openai.api_key = openai_api_key

# openai debug log
os.environ["OPENAI_LOG"] = "debug"
