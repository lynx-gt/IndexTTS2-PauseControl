#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IndexTTS2-PauseControl 回归测试。

5 段代表语句（延长 700~900ms + 缩短 180~250ms），断言：
  平均 |偏差| ≤ 50ms（验收基准 13ms），单标记最大 |偏差| ≤ 100ms（实测最大 32ms）。
固定 seed，结果可复现。需要 GPU + 模型权重。

用法：
    python test/regression_test.py --model-dir <路径> --spk-ref <参考音频> [--out-dir temp]
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

CASES = [
    "他停下脚步[pause:800ms]深吸一口气[pause:200ms]然后推开了那扇门。",
    "天色渐渐暗了下来[pause:900ms]风声越来越紧[pause:250ms]远处传来低沉的轰鸣。",
    "她走进房间[pause:700ms]放下背包[pause:180ms]打开了桌上的台灯。",
    "我们带上头盔[pause:850ms]三个光源[pause:200ms]还有备用绳索和急救包。",
    "他打算一直保持这个纪录[pause:750ms]直到退休[pause:220ms]他说一天都不会提前。",
]

MEAN_TOL_MS = 50
MAX_TOL_MS = 100


def measure_pauses(wav_np, sr=22050, min_ms=60):
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
    parser = argparse.ArgumentParser(description="pause 回归测试（5 段）")
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--spk-ref", required=True)
    parser.add_argument("--out-dir", default="temp_regression")
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    tts = IndexTTS2(cfg_path=os.path.join(args.model_dir, "config.yaml"),
                    model_dir=args.model_dir, use_fp16=False)
    all_devs = []
    for i, text in enumerate(CASES):
        out = os.path.join(args.out_dir, "r%02d.wav" % i)
        tts.infer(
            spk_audio_prompt=args.spk_ref, emo_audio_prompt=None, emo_alpha=0.75,
            text=text, output_path=out, seed=42 + i,
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
        devs = []
        for ch, tgt in marks:
            exp_t = ch / n_chars * dur
            best = min(sils, key=lambda x: abs(x[0] - exp_t)) if sils else None
            if best is None or abs(best[0] - exp_t) > 1.0:
                devs.append(999)
                print("[%02d] 标记%d 目标%dms：未找到停顿" % (i, len(devs) - 1, tgt))
                continue
            d = best[1] - tgt
            devs.append(d)
            print("[%02d] 目标%dms 实测%.0fms 偏差%+.0fms" % (i, tgt, best[1], d))
        all_devs.extend(devs)

    mean = np.mean(np.abs(all_devs))
    mx = np.max(np.abs(all_devs))
    print("=" * 50)
    print("平均|偏差|: %.0fms（阈值 %dms）| 最大|偏差|: %.0fms（阈值 %dms）" % (mean, MEAN_TOL_MS, mx, MAX_TOL_MS))
    ok = mean <= MEAN_TOL_MS and mx <= MAX_TOL_MS
    print("REGRESSION_TEST_PASS" if ok else "REGRESSION_TEST_FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
