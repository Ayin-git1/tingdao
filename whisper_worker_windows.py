#!/usr/bin/env python3
"""Windows Whisper worker using faster-whisper and a local CTranslate2 model."""
import argparse
import json


def stamp(seconds):
    seconds = max(0.0, float(seconds or 0))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(int(minutes), 60)
    if hours:
        return f"{hours}:{minutes:02}:{seconds:05.2f}"
    return f"{minutes:02}:{seconds:05.2f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--lang", default="")
    ap.add_argument("--prompt", default="")
    ap.add_argument("--total", type=float, default=0)
    ap.add_argument("--silence-skip", action="store_true")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    from faster_whisper import WhisperModel

    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    options = {"beam_size": 5, "vad_filter": args.silence_skip}
    if args.lang and args.lang != "auto":
        options["language"] = args.lang
    if args.prompt:
        options["initial_prompt"] = args.prompt
    segments, _ = model.transcribe(args.audio, **options)
    result = []
    texts = []
    for segment in segments:
        text = (segment.text or "").strip()
        result.append({"start": float(segment.start), "end": float(segment.end),
                       "text": text})
        if text:
            texts.append(text)
            print(f"[{stamp(segment.start)} --> {stamp(segment.end)}] {text}", flush=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"segments": result, "text": "".join(texts)}, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
