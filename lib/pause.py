# -*- coding: utf-8 -*-
"""停顿后处理核心（复制改造自 scripts/fix/pause_processor.py v6，已验证）。

自动模式：文本含 [pause:N] 标记 → 生成后处理（whisper 对齐定位 + 能量谷精修 + 静音调整），
并产出"停顿操作记录"（供修复节点使用，修复时用户无需重新找位置）。
"""
import difflib
import math
import os
import re
import wave

import numpy as np

PAUSE_PATTERN = re.compile(r"\[(?:pause|wait|stop):(\d+(?:\.\d+)?)(ms|s)?\]", re.IGNORECASE)

_WHISPER_CACHE = {}


def parse_pause_tags(text):
    """返回 (marks, clean_text)。标记替换为逗号；marks: [{pos: 逗号序号1起, ms}]"""
    marks = []
    clean = text
    comma_idx = 0
    for m in PAUSE_PATTERN.finditer(text):
        dur = float(m.group(1))
        if m.group(2) and m.group(2).lower() == "ms":
            dur = dur
        else:
            dur = dur * 1000
        dur = int(max(0, min(dur, 30000)))
        clean = clean[: m.start()] + "，" + clean[m.end():]
        comma_idx += 1
        marks.append({"pos": comma_idx, "ms": dur})
    return marks, clean


def get_whisper(model_name="base", download_root=None):
    """whisper 全局单例（CPU）。download_root 指向 models/index_tts/whisper/。"""
    key = (model_name, download_root)
    if key not in _WHISPER_CACHE:
        import whisper
        _WHISPER_CACHE[key] = whisper.load_model(model_name, device="cpu", download_root=download_root)
    return _WHISPER_CACHE[key]


def load_wav(path):
    """读取 wav 全部样本（保持原采样率）。返回 (float32[-1,1] 一维, sr)。"""
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        n = w.getnframes()
        data = w.readframes(n)
    audio = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    return audio, sr


def save_wav(path, samples, sr):
    data = np.clip(samples, -1.0, 1.0)
    pcm = (data * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def resample_audio(audio, sr, target_sr=16000):
    """重采样（whisper 需要 16kHz）。"""
    if sr == target_sr:
        return audio
    from scipy.signal import resample_poly
    gcd = math.gcd(sr, target_sr)
    return resample_poly(audio, target_sr // gcd, sr // gcd).astype(np.float32)


def transcribe(whisper_model, audio, sr):
    result = whisper_model.transcribe(
        audio, language="zh", word_timestamps=True, fp16=False,
        condition_on_previous_text=False,
        initial_prompt="以下是普通话的简体中文文本。",
    )
    entries = []
    for seg in result["segments"]:
        words = seg.get("words") or []
        if words:
            for w in words:
                t = w.get("word", "").strip()
                if t:
                    entries.append((t, w["start"], w["end"]))
        else:
            entries.append((seg["text"].strip(), seg["start"], seg["end"]))
    char_entries = []
    for t, s, e in entries:
        chars = list(t)
        if not chars:
            continue
        if len(chars) == 1:
            char_entries.append((chars[0], s, e))
        else:
            span = (e - s) / len(chars)
            for k, ch in enumerate(chars):
                char_entries.append((ch, s + k * span, s + (k + 1) * span))
    return char_entries


def align_text(text, entries):
    """逐字对齐，返回 [(char, start|None, end|None)]"""
    ref = list(text)
    ent = [t for t, _, _ in entries]
    sm = difflib.SequenceMatcher(a=ref, b=ent, autojunk=False)
    mapping = {}
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                mapping[i1 + k] = j1 + k
    aligned = []
    for i, ch in enumerate(ref):
        if i in mapping:
            _, s, e = entries[mapping[i]]
            aligned.append((ch, s, e))
        else:
            aligned.append((ch, None, None))
    return aligned


def find_comma_positions(aligned):
    """返回每个逗号的位置信息 [{idx, prev_t, next_t, center}]，逗号序号从1起"""
    timed = [i for i, (_, s, e) in enumerate(aligned) if s is not None]
    timed_set = set(timed)
    commas = []
    for i, (ch, s, e) in enumerate(aligned):
        if ch not in "，,":
            continue
        prev_t = next_t = None
        for j in range(i - 1, -1, -1):
            if j in timed_set:
                prev_t = (aligned[j][1] + aligned[j][2]) / 2
                break
        for j in range(i + 1, len(aligned)):
            if j in timed_set:
                next_t = (aligned[j][1] + aligned[j][2]) / 2
                break
        center = None
        if prev_t is not None and next_t is not None:
            center = (prev_t + next_t) / 2
        elif prev_t is not None:
            center = prev_t + 0.15
        commas.append({"idx": len(commas) + 1, "center": center,
                       "prev_t": prev_t, "next_t": next_t})
    return commas


def refine_energy_valley(audio, sr, center_s, window_ms=250, frame_ms=10):
    """在 center±window 内检测静音段并取其中点。返回时间s 或 None。"""
    win = int(window_ms / 1000 * sr)
    frame = int(frame_ms / 1000 * sr)
    thr = (100 / 32768.0) ** 2
    c = int(center_s * sr)
    start = max(0, c - win)
    end = min(len(audio), c + win)
    if end - start < frame * 2:
        return None
    regions = []
    in_sil = False
    sil_start = 0
    for i in range(start, end - frame, frame):
        chunk = audio[i:i + frame]
        e = float(np.dot(chunk, chunk)) / len(chunk)
        if e < thr and not in_sil:
            in_sil = True
            sil_start = i
        elif e >= thr and in_sil:
            in_sil = False
            regions.append((sil_start, i))
    if in_sil:
        regions.append((sil_start, end))
    if not regions:
        return None
    best = None
    for s0, s1 in regions:
        if s0 <= c <= s1:
            best = (s0, s1)
            break
    if best is None:
        best = min(regions, key=lambda r: abs(((r[0] + r[1]) / 2) - c))
    return (best[0] + best[1]) / 2 / sr


def adjust_silence(audio, sr, point_s, target_ms, search_ms=400):
    """把 point_s 处静音调整为 target_ms。
    返回 (调整后音频, 静音起点秒, 调整前静音毫秒)。"""
    target = int(target_ms / 1000 * sr)
    frame = int(0.010 * sr)
    thr = (100 / 32768.0) ** 2
    p = int(point_s * sr)

    s0 = p
    silence_run = 0
    need_confirm = max(1, int(0.020 * sr / frame))
    i = p - frame
    while i > 0:
        chunk = audio[i:i + frame]
        e = float(np.dot(chunk, chunk)) / len(chunk)
        if e < thr:
            s0 = i
            silence_run = 0
        else:
            silence_run += 1
            if silence_run >= need_confirm:
                break
        i -= frame

    s1 = p
    silence_run = 0
    i = p
    while i + frame < len(audio):
        chunk = audio[i:i + frame]
        e = float(np.dot(chunk, chunk)) / len(chunk)
        if e < thr:
            s1 = i + frame
            silence_run = 0
        else:
            silence_run += 1
            if silence_run >= need_confirm:
                break
        i += frame

    current_ms = int((s1 - s0) / sr * 1000)
    diff = target - (s1 - s0)
    if abs(diff) < int(0.005 * sr):
        return audio, s0 / sr, current_ms
    new_sil = np.zeros(target, dtype=np.float32)
    out = np.concatenate([audio[:s0], new_sil, audio[s1:]]).astype(np.float32)
    return out, s0 / sr, current_ms


def process_pause_marks(wav_path, clean_text, marks, out_path, whisper_model="base", whisper_root=None):
    """自动 pause 后处理。返回操作记录列表：
    [{no, pos_sec, orig_ms, target_ms, type: insert|adjust|fail, reason?}]"""
    records = []
    audio, sr = load_wav(wav_path)
    if not marks:
        return records
    model = get_whisper(whisper_model, whisper_root)
    entries = transcribe(model, resample_audio(audio, sr), 16000)
    aligned = align_text(clean_text, entries)
    commas = find_comma_positions(aligned)

    for m in marks:
        pos, target = m["pos"], m["ms"]
        rec = {"no": pos, "target_ms": target}
        if pos - 1 >= len(commas) or commas[pos - 1]["center"] is None:
            rec.update({"pos_sec": None, "orig_ms": None, "type": "fail", "reason": "无法定位标记位置"})
            records.append(rec)
            continue
        center = commas[pos - 1]["center"]
        pt = refine_energy_valley(audio, sr, center)
        if pt is None:
            pt = center
        audio, s0, current = adjust_silence(audio, sr, pt, target)
        rec.update({"pos_sec": round(s0, 3), "orig_ms": current,
                    "type": "insert" if current < 50 else "adjust"})
        records.append(rec)

    save_wav(out_path, audio, sr)
    return records


def fix_pause_at(wav_path, points, out_path):
    """手动修复模式：points = [(sec, target_ms)]，sec=0 时不做；target_ms=0 表示删除该处停顿。
    返回操作记录列表。"""
    audio, sr = load_wav(wav_path)
    records = []
    for sec, target in points:
        if sec <= 0:
            records.append({"sec": sec, "target_ms": target, "type": "skip"})
            continue
        pt = refine_energy_valley(audio, sr, sec)
        if pt is None:
            records.append({"sec": sec, "target_ms": target, "type": "fail",
                            "reason": "附近无静音段/边界可定位"})
            continue
        audio, s0, current = adjust_silence(audio, sr, pt, target)
        records.append({"sec": round(s0, 3), "orig_ms": current, "target_ms": target,
                        "type": "delete" if target < 50 else "adjust"})
    save_wav(out_path, audio, sr)
    return records
