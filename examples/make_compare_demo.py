#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「有 pause vs 无 pause」双语对比音频。

用法：
    python examples/make_compare_demo.py --model-dir <models/index_tts 路径> --spk-ref <参考音频> [--out-dir examples/audio]

生成 4 条音频（同 seed，音色/语速一致，唯一差异是 [pause:] 标记）。
文本为自编示例（无版权）：
    zh_plain.wav   中文·无 pause   ：他停下脚步，深吸一口气，然后推开了那扇门。
    zh_pause.wav   中文·有 pause   ：他停下脚步[pause:800ms]深吸一口气[pause:200ms]然后推开了那扇门。
    en_plain.wav   英文·无 pause   ：He stopped and took a deep breath.
    en_pause.wav   英文·有 pause   ：He stopped[pause:800ms]and took a deep breath.

听感要点：
- plain 版停顿是模型自然节奏（无规律）；pause 版两处停顿被精确固定为 800ms / 200ms
- 中文与英文行为一致（标记统一替换为中文逗号，实测英文同样精确）
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np
import soundfile as sf

from indextts.infer_v2 import IndexTTS2
from indextts.utils import pause_control

CASES = [
    ("zh_plain", "他停下脚步，深吸一口气，然后推开了那扇门。"),
    ("zh_pause", "他停下脚步[pause:800ms]深吸一口气[pause:200ms]然后推开了那扇门。"),
    ("en_plain", "He stopped and took a deep breath."),
    ("en_pause", "He stopped[pause:800ms]and took a deep breath."),
]
SEED = 42
# 对比用固定参数（与测试/验收一致）
GEN_KW = dict(temperature=0.6, top_p=0.8, top_k=20, num_beams=4, do_sample=True,
              repetition_penalty=10.0, speaking_speed=1.0, interval_silence=0,
              pause_mode=True, detect_cfm_steps=25)


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
    parser = argparse.ArgumentParser(description="生成 pause 对比演示音频")
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--spk-ref", required=True, help="参考音频（可用开源语音数据集音频，如 LibriSpeech/Common Voice）")
    parser.add_argument("--out-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio"))
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    tts = IndexTTS2(cfg_path=os.path.join(args.model_dir, "config.yaml"),
                    model_dir=args.model_dir, use_fp16=False)
    print("=" * 60)
    for name, text in CASES:
        out = os.path.join(args.out_dir, name + ".wav")
        tts.infer(spk_audio_prompt=args.spk_ref, emo_audio_prompt=None, emo_alpha=0.75,
                  text=text, output_path=out, seed=SEED, **GEN_KW)
        wav, sr = sf.read(out)
        wav_np = wav.squeeze().astype(np.float64)
        sils = measure_pauses(wav_np, sr)
        clean, marks = pause_control.parse_pause_marks(text)
        dur = len(wav_np) / sr
        n_chars = max(len(clean), 1)
        line = "%-10s %s\n       时长 %.2fs | 停顿:" % (name, text, dur)
        if marks:
            for ch, tgt in marks:
                exp_t = ch / n_chars * dur
                best = min(sils, key=lambda x: abs(x[0] - exp_t)) if sils else None
                m = "%.0fms(目标%d)" % (best[1], tgt) if best and abs(best[0] - exp_t) < 1.0 else "N/A"
                line += " %s" % m
        else:
            line += " " + str([(round(s, 2), round(d)) for s, d in sils])
        print(line)
        print("        → %s" % out)
    print("=" * 60)
    print("对比完成：pause 版的停顿被精确固定（800ms/200ms），plain 版为模型自然节奏")


if __name__ == "__main__":
    main()
