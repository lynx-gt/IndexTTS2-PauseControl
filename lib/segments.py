# -*- coding: utf-8 -*-
"""分句稿解析（复制改造自 scripts/08_batch_seed_compare.py）。

支持两种输入：
1. 分句稿 markdown：`# 片段 N [角色 / 情绪]` 标题 + 正文（优先取 `<!-- 处理后: ... -->`）
2. 纯文本：每行一段
"""
import os
import random
import re

SEGMENT_PATTERN = re.compile(
    r"# 片段 (\d+) \[(.+?) / (.+?)\]\n<!-- 标题: (.+?) -->\n(.*?)(?=\n# 片段 |\Z)",
    re.DOTALL,
)
PROC_PATTERN = re.compile(r"<!-- 处理后: (.*?) -->", re.DOTALL)


def parse_segments_md(md_path):
    """解析分句稿，返回 [{index, role, emotion, text}]。"""
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()
    segments = []
    for m in SEGMENT_PATTERN.finditer(content):
        index, role, emotion, body = int(m.group(1)), m.group(2).strip(), m.group(3).strip(), m.group(5)
        proc = PROC_PATTERN.search(body)
        text = proc.group(1).strip() if proc else body.strip()
        if text:
            segments.append({"index": index, "role": role, "emotion": emotion, "text": text})
    return segments


def parse_text_lines(text):
    """纯文本每行一段，返回 [{index, role, emotion, text}]。"""
    segments = []
    for i, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if line and not line.startswith("#"):
            segments.append({"index": i, "role": "", "emotion": "", "text": line})
    return segments


def pick_emotion_ref(emotion, emo_strategy, emo_ref, emo_dir):
    """情感参考选择：
    固定 = 直接用 emo_ref；目录随机 = 优先 emo_dir/{情绪}/ 子目录随机，否则 emo_dir 下随机。
    返回路径字符串或 None。"""
    if emo_strategy == "固定":
        return emo_ref if emo_ref and os.path.isfile(emo_ref) else None
    # 目录随机
    if not emo_dir or not os.path.isdir(emo_dir):
        return None
    base = emo_dir
    if emotion and os.path.isdir(os.path.join(emo_dir, emotion)):
        base = os.path.join(emo_dir, emotion)
    candidates = sorted(f for f in os.listdir(base) if f.lower().endswith(".wav"))
    if not candidates:
        return None
    return os.path.join(base, random.choice(candidates))
