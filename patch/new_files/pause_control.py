# -*- coding: utf-8 -*-
"""精确停顿控制（[pause:N]）。

标记在生成前替换为中文逗号（让 LLM 按逗号自然停顿），生成后对 wav 做
能量检测找出停顿，用 Needleman-Wunsch 把标记与停顿全局对齐，再对静音
核心做延长/缩短/插入。全部操作在波形域完成，免重解码。
"""
import re

import numpy as np
import torch

# 检测参数
DETECT_FRAME_MS = 10        # 能量检测帧长
DETECT_THRESHOLD = (100 / 32768.0) ** 2  # 帧能量阈值（约 -50dBFS）
DETECT_MIN_PAUSE_MS = 100   # 小于此时长的静音视为字间气口，不算停顿

# 插入保护
INSERT_GUARD_MS = 100       # 插入点能量谷搜索窗口（预期位置 ±100ms）


_PAUSE_RE = re.compile(r"\[(?:pause|wait|stop):(\d+(?:\.\d+)?)(ms|s)?\]")


def parse_pause_marks(text):
    """解析 [pause:Nms] / [pause:N] / [pause:Ns] 标记，替换为中文逗号。

    返回 (clean_text, marks)：
      marks: [(标记在 clean_text 中的字符位置, 目标时长ms, 标点环境)]
      标点环境 period_side：'before'=标记紧邻句号前，'after'=紧邻句号后，
      'none'=普通标记。句号前标记用离预期最近的停顿核心（句号处停顿常被
      模型拆成多段），其余标记用最长的核心。
    """
    clean_parts = []
    marks = []
    pos = 0
    shift = 0  # 之前已替换标记的长度差（原文本 → clean 文本）
    for m in _PAUSE_RE.finditer(text):
        clean_parts.append(text[pos:m.start()])
        num = float(m.group(1))
        unit = m.group(2)
        ms = int(num * 1000) if unit == "s" else int(num)
        # 标点环境：看原文本中标记前后的字符
        # （注意空串守卫："" in "。！？…" 为 True，标记在开头/结尾时
        #   前一/后一字符为空串，必须排除，否则 side 会误判）
        side = "none"
        nxt = text[m.end():m.end() + 1]
        prv = text[max(0, m.start() - 1):m.start()]
        if nxt and nxt in "。！？…":
            side = "before"
        elif prv and prv in "。！？…":
            side = "after"
        # 标记在 clean_text 中的位置 = 原位置 - 之前已替换标记的长度差
        # （标记替换为单个逗号，clean 文本比原文本短）
        marks.append((m.start() - shift, ms, side))
        shift += len(m.group(0)) - 1
        clean_parts.append("，")
        pos = m.end()
    clean_parts.append(text[pos:])
    return "".join(clean_parts), marks


def detect_pauses(wav_np, sr=22050, min_ms=DETECT_MIN_PAUSE_MS):
    """能量检测静音段，返回 [(起点s, 时长ms, 核心起点s, 核心时长ms)]。

    核心区 = 段内用严格阈值（5×）扫描出的最长连续纯静音。弱尾音（鼻音
    收尾等）会被宽松阈值计入停顿段，但调整只作用于核心区——弱尾音是
    语音，必须保留。
    """
    frame = int(DETECT_FRAME_MS / 1000.0 * sr)
    thr = DETECT_THRESHOLD
    thr_strict = thr * 5.0
    runs, in_sil, start = [], False, 0
    n = len(wav_np)
    for i in range(0, n - frame, frame):
        e = float((wav_np[i:i + frame] ** 2).sum()) / frame
        if e < thr and not in_sil:
            in_sil, start = True, i
        elif e >= thr and in_sil:
            in_sil = False
            if (i - start) / sr * 1000 >= min_ms:
                runs.append((start / sr, (i - start) / sr * 1000))
    if in_sil and (n - start) / sr * 1000 >= min_ms:
        runs.append((start / sr, (n - start) / sr * 1000))
    # 每段求严格核心区
    out = []
    for s0, d in runs:
        s_f = int(s0 * sr)
        e_f = int((s0 + d / 1000.0) * sr)
        core_start, core_end = None, None
        best = (0, 0, 0)  # (len_frames, start_frame, end_frame)
        cur_start = None
        for f in range(s_f, e_f - frame, frame):
            e = float((wav_np[f:f + frame] ** 2).sum()) / frame
            if e < thr_strict:
                if cur_start is None:
                    cur_start = f
            else:
                if cur_start is not None:
                    ln = f - cur_start
                    if ln > best[0]:
                        best = (ln, cur_start, f)
                    cur_start = None
        if cur_start is not None:
            ln = e_f - cur_start
            if ln > best[0]:
                best = (ln, cur_start, e_f)
        if best[0] > 0:
            out.append((s0, d, best[1] / sr, best[0] / sr * 1000.0))
        else:
            out.append((s0, d, s0, d))  # 无严格核心，退化为整段
    return out


def nw_align(marks, pauses, t_scale, wav_dur,
             w_dur=0.2, max_t_diff=0.8,
             gap_open=0.30, gap_extend=0.25,
             gapB_open=0.05, gapB_extend=0.01):
    """标记与停顿的全局最优对齐（仿射 gap）。

    marks/pauses 的特征都是 [时间归一化, 时长归一化]：
      时间 = 位置秒 / t_scale；时长 = ms / 2000
    匹配代价 = |Δt| + w_dur×|Δdur|；时间差超过 max_t_diff（秒）的候选
    对禁止匹配（超限只能走插入/跳过）。

    两个注意点（都是实测踩过的坑）：
    - w_dur 不能调大：时长权重过重时，自然停顿时长接近某个标记目标时长
      的停顿会被错误配对（w=1.0 时 20 段错 5 段，0.05~0.5 区间稳定）。
    - gapA（跳过标记=漏停，需插入处理）不能太便宜：否则"跳过标记"比
      "正确匹配"更划算，标记贴着一个停顿也会被漏掉。

    返回 (assign, inserted, skipped, conf)：
      assign[i]：匹配的停顿下标，-1 = 该标记未匹配（漏停）
      inserted / skipped：漏停标记、多余停顿的下标列表
      conf[i]：匹配距离，供人工确认参考
    """
    M, N = len(marks), len(pauses)
    if M == 0:
        # 无标记：全部停顿视为多余（不动）
        return [], [], list(range(N)), []
    if N == 0:
        # 无停顿：全部标记视为漏停（走插入路径，由插入保护决定是否生效）
        return [-1] * M, list(range(M)), [], [None] * M
    t_scale = max(t_scale, 1)
    A = np.array([[marks[i][0] / t_scale, marks[i][1] / 2000.0] for i in range(M)])
    B = np.array([[pauses[j][0] / t_scale, pauses[j][1] / 2000.0] for j in range(N)])
    INF = 1e9
    dp = np.full((M + 1, N + 1), INF, dtype=np.float64)
    gA = np.full((M + 1, N + 1), INF, dtype=np.float64)  # 跳过标记（漏停→插入）
    gB = np.full((M + 1, N + 1), INF, dtype=np.float64)  # 跳过停顿（多停→不动）
    dp[0, 0] = 0.0
    gA[1, 0] = gap_open
    for i in range(2, M + 1):
        gA[i, 0] = gA[i - 1, 0] + gap_extend
    for i in range(1, M + 1):
        dp[i, 0] = gA[i, 0]
    gB[0, 1] = gapB_open
    for j in range(2, N + 1):
        gB[0, j] = gB[0, j - 1] + gapB_extend
    for j in range(1, N + 1):
        dp[0, j] = gB[0, j]

    def cost(i, j):
        if abs(A[i][0] - B[j][0]) * t_scale > max_t_diff:
            return INF  # 时间硬上限：超限候选禁止匹配
        return abs(A[i][0] - B[j][0]) + w_dur * abs(A[i][1] - B[j][1])

    for i in range(1, M + 1):
        for j in range(1, N + 1):
            c = cost(i - 1, j - 1)
            m = dp[i - 1, j - 1] + c
            gA[i, j] = min(dp[i - 1, j] + gap_open, gA[i - 1, j] + gap_extend)
            gB[i, j] = min(dp[i, j - 1] + gapB_open, gB[i, j - 1] + gapB_extend)
            dp[i, j] = min(m, gA[i, j], gB[i, j])

    assign = [-1] * M
    conf = [None] * M
    i, j = M, N
    while i > 0 or j > 0:
        if i > 0 and j > 0 and abs(dp[i, j] - (dp[i - 1, j - 1] + cost(i - 1, j - 1))) < 1e-9:
            assign[i - 1] = j - 1
            conf[i - 1] = cost(i - 1, j - 1)
            i -= 1
            j -= 1
        elif i > 0 and gA[i, j] < INF and abs(dp[i, j] - gA[i, j]) < 1e-9:
            i -= 1
        else:
            j -= 1
    used = set(a for a in assign if a >= 0)
    skipped = [k for k in range(N) if k not in used]
    inserted = [i for i in range(M) if assign[i] == -1]
    return assign, inserted, skipped, conf


def find_energy_valley(wav_np, center_sec, sr=22050, guard_ms=INSERT_GUARD_MS):
    """在 center_sec ± guard_ms 窗口内找帧能量最低点（插入落点，避免切字）。
    返回 (位置s, 帧能量)；调用方用能量判断该处是否为真静音（低于阈值才可插入）。"""
    frame = int(DETECT_FRAME_MS / 1000.0 * sr)
    guard = int(guard_ms / 1000.0 * sr)
    c = int(center_sec * sr)
    lo = max(0, c - guard)
    hi = min(len(wav_np) - frame, c + guard)
    best_i, best_e = c, None
    for i in range(lo, hi, frame):
        e = float((wav_np[i:i + frame] ** 2).sum()) / frame
        if best_e is None or e < best_e:
            best_e, best_i = e, i
    return best_i / sr, (best_e if best_e is not None else float("inf"))


def find_core_region(wav_np, center_s, sr=22050, strict_mult=5.0, min_core_ms=30, window_s=0.6,
                     select="longest"):
    """在 center_s ± window_s 窗口内找严格静音核心区，返回 (起点s, 终点s) 或 None。

    select：
      'longest'：窗口内最长的连续静音（默认，普通标记/句号后标记使用）
      'nearest'：离 center_s 最近的静音（句号前标记使用——句号处停顿常被
                 模型拆成多段，取最近的才能命中标记对应的那一段）
    """
    frame = int(DETECT_FRAME_MS / 1000.0 * sr)
    thr_strict = DETECT_THRESHOLD * strict_mult
    lo = max(0, int((center_s - window_s) * sr))
    hi = min(len(wav_np) - frame, int((center_s + window_s) * sr))
    # 收集窗口内所有严格静音段
    segs = []
    cur = None
    for f in range(lo, hi, frame):
        e = float((wav_np[f:f + frame] ** 2).sum()) / frame
        if e < thr_strict:
            if cur is None:
                cur = f
        else:
            if cur is not None:
                segs.append((cur, f))
                cur = None
    if cur is not None:
        segs.append((cur, hi))
    if not segs:
        return None
    if select == "nearest":
        cands = [s for s in segs if s[1] - s[0] >= int(min_core_ms / 1000.0 * sr)]
        pool = cands if cands else segs
        b2, d2 = None, None
        for a, b in pool:
            dd = abs((a + b) / 2.0 - center_s * sr)
            if d2 is None or dd < d2:
                d2, b2 = dd, (a, b)
        if b2 is not None:
            return b2[0] / sr, b2[1] / sr
        return None
    # longest（默认）
    best = max(segs, key=lambda s: s[1] - s[0])
    if best[1] - best[0] >= int(min_core_ms / 1000.0 * sr):
        return best[0] / sr, best[1] / sr
    return None


def wav_shrink_pause(wav_np, center_s, target_ms, sr=22050, margin_ms=15, select="longest"):
    """波形级缩短：把 center_s 处停顿的核心区裁剪到 target_ms。
    核心两端各留 margin_ms 缓冲防切字；核心已短于目标时不动。返回新 wav。"""
    core = find_core_region(wav_np, center_s, sr, select=select)
    if core is None:
        return wav_np
    cs, ce = core
    core_ms = (ce - cs) * 1000.0
    if core_ms <= target_ms + margin_ms * 2:
        return wav_np  # 核心已够短，不动
    keep_start_ms = max(margin_ms, target_ms - margin_ms)
    cut_at = int((cs + keep_start_ms / 1000.0) * sr)
    cut_to = int((ce - margin_ms / 1000.0) * sr)
    if cut_to > cut_at:
        return np.concatenate([wav_np[:cut_at], wav_np[cut_to:]])
    return wav_np


def wav_extend_pause(wav_np, center_s, target_ms, sr=22050, margin_ms=15, select="longest"):
    """波形级延长：在 center_s 处停顿的核心区中部插入静音到 target_ms。
    静音接静音，无拼接感；核心已长于目标时不动。返回新 wav。"""
    core = find_core_region(wav_np, center_s, sr, select=select)
    if core is None:
        return wav_np
    cs, ce = core
    core_ms = (ce - cs) * 1000.0
    add_ms = target_ms - core_ms
    if add_ms <= margin_ms:
        return wav_np
    add_samples = int(add_ms / 1000.0 * sr)
    insert_at = int(((cs + ce) / 2.0) * sr)
    return np.concatenate([wav_np[:insert_at], np.zeros(add_samples, dtype=wav_np.dtype), wav_np[insert_at:]])
