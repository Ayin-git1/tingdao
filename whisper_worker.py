#!/usr/bin/env python3
"""听道 Whisper 转写子进程 worker。

为什么要子进程: mlx_whisper.transcribe 没有任何回调参数, 在主进程里跑就是一块
拆不开的整砖, 中途停不下来; 挪进子进程后 SIGTERM 即死(与当年 ffmpeg 收尾同款)。

协议:
  --audio PATH      要转写的音频(父进程已完成预处理/回退决策)
  --model PATH      本地模型目录
  --lang zh|en|...  空或 auto = 不指定
  --prompt TEXT     热词 initial_prompt(父进程拼好"以下是常用人名与术语：…")
  --total SEC       音频总时长; >0 才开 verbose 出进度段行
  --silence-skip    跳过静音救急档(词级时间戳必须成对打开, 见下)
  --out FILE        结果 JSON 落盘路径(段数组+全文, 父进程读它, 不靠解析 stdout)

进度: verbose=True 时 mlx 自己往 stdout 打 `[起 --> 止] 文本` 段行,
父进程逐行喂给 WhisperStdout 算百分比 —— 与旧版 redirect_stdout 劫持完全同一格式。
"""
import argparse
import json
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--lang", default="")
    ap.add_argument("--prompt", default="")
    ap.add_argument("--total", type=float, default=0)
    ap.add_argument("--silence-skip", action="store_true")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    import mlx_whisper
    kw = dict(path_or_hf_repo=a.model, verbose=bool(a.total),
              condition_on_previous_text=True,   # 整条音频要全程上下文
              word_timestamps=False)
    if a.silence_skip:
        # 库源码把静音跳过写在 `if word_timestamps:` 分支内(transcribe.py:432),
        # 只传阈值不开词级时间戳 = 死代码, 必须成对打开(与主进程旧逻辑一致)。
        kw["word_timestamps"] = True
        kw["hallucination_silence_threshold"] = 1.5
    if a.lang and a.lang != "auto":
        kw["language"] = a.lang
    if a.prompt:
        kw["initial_prompt"] = a.prompt

    res = mlx_whisper.transcribe(a.audio, **kw)
    segs = [{"start": float(s.get("start", 0) or 0),
             "end": float(s.get("end", 0) or 0),
             "text": (s.get("text") or "").strip()}
            for s in (res.get("segments") or [])]
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"segments": segs, "text": (res.get("text") or "").strip()},
                  f, ensure_ascii=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(143)
