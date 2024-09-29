import asyncio
import subprocess
import uuid
from pathlib import Path

import aioprocessing

from config import VOICEPEAK_PATH

VOICEPEAK_NARRATOR = {"彩澄りりせ": "Asumi Ririse", "彩澄しゅお": "Asumi Shuo"}

NARRATOR_SETTINGS = {
    "Asumi Shuo": {
        "happy": 0,
        "sad": 0,
        "angry": 0,
        "fun": 0,
        "speed": 110,
        "pitch": 0,
        "pose": 80,
    },
    "Asumi Ririse": {
        "happy": 10,
        "sad": 0,
        "angry": 0,
        "fun": 10,
        "speed": 125,
        "pitch": 0,
        "pose": 30,
    },
}


async def playVoicePeak(script: str, narrator: str = "彩澄りりせ"):
    """
    任意のテキストをVOICEPEAKのナレーターに読み上げさせる関数
    script: 読み上げるテキスト（文字列）
    narrator: ナレーターの名前（文字列）
    """

    # 辞書に一致しない場合、デフォルトのナレーターを設定
    narrator = VOICEPEAK_NARRATOR.get(narrator, "Asumi Ririse")

    # ナレーターごとの調整値
    settings = NARRATOR_SETTINGS.get(narrator, {})
    happy = settings.get("happy", 0)
    sad = settings.get("sad", 0)
    angry = settings.get("angry", 0)
    fun = settings.get("fun", 0)
    speed = settings.get("speed", 100)
    pitch = settings.get("pitch", 0)
    pose = settings.get("pose", 100)

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
        outpath,
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
    loop = asyncio.get_running_loop()
    process = aioprocessing.AioProcess(target=async_subprocess, args=(args,))
    await loop.run_in_executor(None, process.start)
    process.join()  # プロセスが終了するのを待つ

    return outpath


def async_subprocess(args):
    subprocess.run(args)
