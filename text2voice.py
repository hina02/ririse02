import os
import uuid
import subprocess
from pathlib import Path
import subprocess


VOICEPEAK_PATH = "C:/Program Files/VOICEPEAK/voicepeak.exe"


def playVoicePeak(script: str, narrator: str = "Asumi Ririse"):
    """
    任意のテキストをVOICEPEAKのナレーターに読み上げさせる関数
    script: 読み上げるテキスト（文字列）
    narrator: ナレーターの名前（文字列）
    """

    if narrator == "Asumi Shuo":
        happy = 0
        sad = 0
        angry = 0
        fun = 0
        speed = 120
        pitch = 0
        pose = 80
    elif narrator == "Asumi Ririse":
        happy = 10
        sad = 0
        angry = 0
        fun = 10
        speed = 125
        pitch = 0
        pose = 30
    else:
        pass

    # voicepeak.exeのパス
    exepath = Path(VOICEPEAK_PATH)
    # wav出力先
    temp = str(uuid.uuid4())
    outpath = Path(f"voice/{temp}.wav")
    # 引数を作成
    args = [
        str(exepath),
        "-s",
        script,
        "-n",
        narrator,
        "-o",
        str(outpath),
        "-e",
        f"happy={happy},sad={sad},angry={angry},fun={fun}",
        "--speed",
        f"{speed}",
        "--pitch",
        f"{pitch}",
        "--pose",
        f"{pose}",
    ]
    print(args)
    subprocess.run(args)
    return outpath


from pydub import AudioSegment

def adjust_volume(file_path: str, volume: float):
    sound = AudioSegment.from_file(file_path)
    adjusted_sound = sound + volume
    adjusted_sound.export(file_path, format="wav")

import time
import re
import threading
import queue
def play_voice_file(voice_queue):
    while True:
        file_path = voice_queue.get()  # キューからファイルパスを取得
        if file_path is None:
            break  # Noneがキューに入っていたら終了

        # 音声ファイルを再生
        process = subprocess.Popen(["start", "/wait", file_path], shell=True)
        # subprocess.Popen(["start", file_path], shell=True)
        process.wait()  # 音声の再生が終わるまで待つ

        voice_queue.task_done()  # キューの処理が完了したことを示す



def get_voice(text: str):
    # テキストを句読点で区切る
    chunks = re.split('[。！？]', text)
    file_paths = []

    voice_queue = queue.Queue()  # 共有キューの作成

    # 音声ファイルを再生するスレッドを起動
    player_thread = threading.Thread(target=play_voice_file, args=(voice_queue,))
    player_thread.start()

    for chunk in chunks:
        if chunk:
            # playVoicePeak は自前で定義する必要がある
            file_path = playVoicePeak(script=chunk, narrator="Asumi Ririse")  
            print(file_path)
            file_paths.append(file_path)

            voice_queue.put(file_path)  # ファイルパスをキューに追加

    voice_queue.put(None)  # スレッドに終了を伝えるためのNoneを追加

    # キューの処理を待つ
    voice_queue.join()

    # スレッドが完了するのを待つ
    player_thread.join()

    # 生成されたファイルパスのリストを返す
    return file_paths
