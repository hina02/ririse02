import asyncio
import aioprocessing
import os
import uuid
import subprocess
from pathlib import Path

VOICEPEAK_PATH = "C:/Program Files/VOICEPEAK/voicepeak.exe"

async def playVoicePeak(script: str, narrator: str = "Asumi Ririse"):
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
