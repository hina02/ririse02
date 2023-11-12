from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import time
import os
import requests
from text2voice import get_voice

os.chdir("C:/Users/hiroh/.cursor-tutor/projects/python")
os.system("python text2voice.py")

BACKEND_URL = "http://127.0.0.1:8000"


def chat_request(user_message: str):
    url = f"{BACKEND_URL}/chat"
    params = {"user_message": user_message}
    return requests.get(url, params=params)


def gpt4v_request(user_message: str, base64_image_urls: list[str] | None = None):
    url = f"{BACKEND_URL}/gpt4v"
    data = {"user_message": user_message, "base64_image_urls": base64_image_urls}
    return requests.post(url, json=data)


class MyHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        else:
            file_name = os.path.basename(event.src_path)
            file_path = os.path.abspath(event.src_path)
            # 画像ファイル形式の場合のみ、RESTリクエストを行います
            if file_name.lower().endswith(
                (".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif")
            ):
                escaped_path = file_path.replace("\\", "\\\\")
                print(f"Event type: {event.event_type}  path : {event.src_path}")
                try:
                    response = gpt4v_request(
                        user_message=file_name, base64_image_urls=[escaped_path]
                    )
                    response.raise_for_status()
                    print(response.text)
                    get_voice(response.text)
                except requests.HTTPError as err:
                    print(f"HTTP error occurred: {err}")
