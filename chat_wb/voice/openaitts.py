import uuid
from pathlib import Path
from openai import OpenAI
client = OpenAI()

script = "Today is a wonderful day to build something people love!"
# wav出力先
temp = str(uuid.uuid4())
speech_file_path = Path(__file__).parent / f"{temp}.wav"
response = client.audio.speech.create(
  model="tts-1",
  voice="echo",
  input=script,
)

response.stream_to_file(speech_file_path)
