#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IndexTTS2-PauseControl 冒烟测试。

跑一句含 [pause:N] 的文本，验证两处停顿是否命中目标时长。
需要：GPU + IndexTTS2 模型权重（models/index_tts/）。

用法：
    python test/smoke_test.py --model-dir <models/index_tts 路径> --spk-ref <参考音频>
    （模型目录需含 config.yaml / gpt.pth / s2mel.pth 等；参考音频任意 5s+ wav）
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np
import soundfile as sf

from indextts.infer_v2 import IndexTTS2
from indextts.utils import pause_control

TEXT_ZH = "他停下脚步[pause:800ms]深吸一口气[pause:200ms]然后推开了那扇门。"
TEXT_EN = "He stopped[pause:800ms]and took a deep breath. He looked back[pause:200ms]before opening the door."
TARGETS = [800, 200]
TOLERANCE_MS = 60  # 实测偏差 ±32ms，留裕度
SEED = 42


def measure_pauses(wav_np, sr=22050, min_ms=60):
    """宽松阈值静音检测（与验收口径一致）：返回 [(起点s, 时长ms)]"""
    frame = int(0.01 * sr)
    thr = (100 / 32768.0) ** 2 * 3
    runs, in_sil, start = [], False, 0
    for i in range(0, len(wav_np) - frame, frame):
        e = float((wav_np[i:i + frame] ** 2).sum()) / frame
        if e < thr and not in_sil:
            in_sil, start = True, i
        elif e >= thr and in_sil:
            in_sil = False
            if (i - start) / sr * 1000 >= min_ms:
                runs.append((start / sr, (i - start) / sr * 1000))
    if in_sil and (len(wav_np) - start) / sr * 1000 >= min_ms:
        runs.append((start / sr, (len(wav_np) - start) / sr * 1000))
    return runs


def main():
    parser = argparse.ArgumentParser(description="pause 冒烟测试")
    parser.add_argument("--model-dir", required=True, help="IndexTTS2 模型目录（含 config.yaml）")
    parser.add_argument("--spk-ref", required=True, help="音色参考音频路径")
    parser.add_argument("--out", default="temp_smoke.wav", help="输出 wav 路径")
    parser.add_argument("--lang", choices=["zh", "en", "both"], default="both",
                        help="测试语言：zh=中文，en=英文，both=两者（默认）")
    args = parser.parse_args()

    tts = IndexTTS2(cfg_path=os.path.join(args.model_dir, "config.yaml"),
                    model_dir=args.model_dir, use_fp16=False)
    cases = []
    if args.lang in ("zh", "both"):
        cases.append(("zh", TEXT_ZH, args.out))
    if args.lang in ("en", "both"):
        cases.append(("en", TEXT_EN, args.out.replace(".wav", "_en.wav")))

    ok = True
    for lang, text, out in cases:
        print("=" * 50)
        print("[%s] %s" % (lang, text))
        tts.infer(
            spk_audio_prompt=args.spk_ref, emo_audio_prompt=None, emo_alpha=0.75,
            text=text, output_path=out, seed=SEED,
            temperature=0.6, top_p=0.8, top_k=20, num_beams=4, do_sample=True,
            repetition_penalty=10.0, speaking_speed=1.0, interval_silence=0,
            pause_mode=True, detect_cfm_steps=25,
        )
        wav, sr = sf.read(out)
        wav_np = wav.squeeze().astype(np.float64)
        sils = measure_pauses(wav_np, sr)
        clean, marks = pause_control.parse_pause_marks(text)
        dur = len(wav_np) / sr
        n_chars = max(len(clean), 1)
        print("停顿检测:", [(round(s, 2), round(d)) for s, d in sils])
        for mi, (ch, tgt) in enumerate(marks):
            exp_t = ch / n_chars * dur
            best = min(sils, key=lambda x: abs(x[0] - exp_t)) if sils else None
            if best is None or abs(best[0] - exp_t) > 1.0:
                print("FAIL 标记%d(目标%dms)：未找到停顿" % (mi, tgt))
                ok = False
                continue
            dev = best[1] - tgt
            status = "OK " if abs(dev) <= TOLERANCE_MS else "FAIL"
            if status == "FAIL":
                ok = False
            print("%s 标记%d: 目标%dms 实测%.0fms 偏差%+.0fms" % (status, mi, tgt, best[1], dev))

    print("SMOKE_TEST_PASS" if ok else "SMOKE_TEST_FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
