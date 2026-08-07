# -*- coding: utf-8 -*-
"""精确停顿控制（[pause:N]）。

生产方案为「全波形」：标记转逗号让 LLM 自然生成 → 能量检测停顿（物理信号）
→ Needleman-Wunsch（仿射 gap + 时间硬上限）全局对齐标记↔停顿
→ 波形域操作（静音核心延长/缩短/插入，免重解码）。

本文件同时保留 token 级研究记录（CORE10 静音码、码数标定、apply_actions）——
实验证明 LLM 语义码中不存在可生成的"静音码"，CORE10 注入在部分上下文
会产生杂音（prod_01 实测），故 token 级方案已弃用，仅作研究参考。
"""
import re

import numpy as np
import torch

# ---------------------------------------------------------------------------
# 常量（实验标定值）
# ---------------------------------------------------------------------------

# 真静音码 10 码核心：提取自目标音色生成音频的停顿段（去头尾过渡码）。
# 已跨音色验证（v27）：注入其他音色停顿处解码干净（内部 maxRMS 61.9，底噪范围 23~77）。
CORE10 = [5982, 5776, 215, 1327, 1004, 661, 7705, 879, 230, 2098]

# 码数→时长标定（v26，7 组 M 实测拟合）：
#   实测时长(ms) = 20.3 × M + 18.4（测量口径含约 20ms 系统偏差）
#   M = round((目标ms - 20) / 20.3)
MS_PER_CODE = 20.3
DUR_BIAS_MS = 20.0

# NW 对齐超参（v23 定版：30 段 M==N 53/53、M!=N 5/5 全对）
GAP_OPEN = 0.30      # 仿射 gap 打开代价（漏停/多停）
GAP_EXTEND = 0.05    # gap 每延长一个的代价

# 置信度阈值：匹配距离超过该值 → 列入人工确认清单
CONF_THRESHOLD = 0.25

# 检测参数
DETECT_FRAME_MS = 10          # 能量检测帧长
DETECT_THRESHOLD = (100 / 32768.0) ** 2   # 帧能量阈值（对应 -50dBFS 左右）
DETECT_MIN_PAUSE_MS = 100     # 最小停顿（低于此视为字间气口）

# 替换/插入细节
# 核心区安全余量：严格阈值核心区边界在 wav→codes 映射时有 ±2~3 码误差，
# 直接操作会切到前后字弱音（实测"也"被切、"分"尾被切）。
# 操作只作用于核心区两端各收缩 SAFE_MARGIN 码后的安全区，宁可停顿略短不切字。
SAFE_MARGIN = 2
# 延长时保留的停顿段两端过渡码数（防切字缓冲，覆盖 wav→codes 映射误差 ±2~3 码）
EDGE_KEEP_CODES = 2
INSERT_GUARD_MS = 100         # 插入点能量谷搜索窗口（预期位置 ±100ms）

# token 级静音码下限：<250ms 时 CORE10 中途截断序列在 cfm 渲染不稳定
# （切字+膨胀，e2e 150ms→649ms）。改用单码重复 [5982]*M（v33 验证干净：M=6→190ms）。
# 短区间每码 ≈31ms（v33/v34 综合），精度 ±100ms；≥250ms 用 CORE10 循环（精度 ±40ms）。
# 实证：150ms→单码重复5码→249ms（v34 污染数据，仅参考）；300ms（M=14）正常、700ms（M=33）正常。
MIN_TOKEN_PAUSE_MS = 0  # 不再跳过，短停顿用单码重复结构


# ---------------------------------------------------------------------------
# 1. 标记解析
# ---------------------------------------------------------------------------

_PAUSE_RE = re.compile(r"\[(?:pause|wait|stop):(\d+(?:\.\d+)?)(ms|s)?\]")


def parse_pause_marks(text):
    """解析 [pause:Nms] / [pause:N] / [pause:Ns] 标记。
    返回 (clean_text, marks)：
      clean_text：标记替换为逗号后的文本（喂给 LLM 生成）
      marks：[(标记在 clean_text 中的字符位置, 目标时长ms)]（按文本顺序）
    """
    clean_parts = []
    marks = []
    pos = 0  # clean_text 中的累计字符位置
    for m in _PAUSE_RE.finditer(text):
        clean_parts.append(text[pos:m.start()])
        num = float(m.group(1))
        unit = m.group(2)
        ms = int(num * 1000) if unit == "s" else int(num)
        marks.append((len("".join(clean_parts)), ms))  # 逗号位置 = 插入点
        clean_parts.append("，")
        pos = m.end()
    clean_parts.append(text[pos:])
    clean_text = "".join(clean_parts)
    return clean_text, marks


# ---------------------------------------------------------------------------
# 2. 停顿检测（wav 域能量）
# ---------------------------------------------------------------------------

def detect_pauses(wav_np, sr=22050, min_ms=DETECT_MIN_PAUSE_MS):
    """能量检测静音段。返回 [(起点秒, 时长ms, 核心起点秒, 核心时长ms)]，按时间顺序。
    核心区 = 段内用严格阈值（5×）扫描出的最长连续纯静音——弱尾音（鼻音收尾等）
    被宽松阈值计入停顿段，但替换/截断只应作用于核心区（弱尾音是语音，必须保留）。
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


# ---------------------------------------------------------------------------
# 3. Needleman-Wunsch 对齐（仿射 gap）
# ---------------------------------------------------------------------------

def nw_align(marks, pauses, codes_len, wav_dur,
             w_dur=0.2, max_t_diff=0.8,
             gap_open=0.30, gap_extend=0.25,
             gapB_open=0.05, gapB_extend=0.01):
    """标记 ↔ 停顿 全局最优对齐（不对称 gap + 时间硬上限）。

    marks:   [(预期码位置, 目标时长ms)]
    pauses:  [(实测码位置, 实测时长ms)]
    特征 = [时间归一化(t/codes_len), 时长归一化(dur/2000)]
    代价 = |Δt| + w_dur×|Δdur|；时间差 > max_t_diff（秒）的候选对直接 INF（禁止匹配）
    w_dur=0.2（prod20 修正，2026-08-07）：时间特征主导。原 1.0 时
        自然停顿时长若巧合接近某个非对应标记的目标时长，NW 会牺牲
        时间匹配换取时长匹配（prod20_18 实测：标记0 目标 750ms 错配
        到 2.7s 处自然 778ms 停顿，正确停顿 229ms 反被跳过）。
    max_t_diff=0.8s（时间硬上限，与权重正交的硬保险）：正确匹配时间差
        实测最大 0.37s（20 段），0.8 留 2.2 倍裕度；错配场景（18 段
        w=1.0 时代 0.93s）被硬性排除，超限只能走插入/跳过路径
        （插入有能量谷+真静音保护，宁缺毋滥）。
    gapA（跳过标记=漏停，需插入处理）：open 0.30 / ext 0.25（近线性：
        每个漏停都要认真处理，extend 无大优惠——否则连续跳过标记比正确匹配便宜，
        prod_01 教训：标记1 贴着停顿却判插入）
    gapB（跳过停顿=模型多停，不动即可）：≈ 免费 0.05 / 0.01
    返回 (assign, inserted, skipped, conf)：
      assign[i] = 匹配的停顿索引 或 -1（插入）
      inserted：漏停标记索引（需补静音码）
      skipped：多余停顿索引（不动）
      conf[i]：匹配距离（> CONF_THRESHOLD 列入人工确认）
    """
    M, N = len(marks), len(pauses)
    # 特征（时间统一归一化到 [0,1]）
    t_scale = max(codes_len, 1)
    A = np.array([[marks[i][0] / t_scale, marks[i][1] / 2000.0] for i in range(M)])
    B = np.array([[pauses[j][0] / t_scale, pauses[j][1] / 2000.0] for j in range(N)])
    INF = 1e9
    dp = np.full((M + 1, N + 1), INF, dtype=np.float64)
    gA = np.full((M + 1, N + 1), INF, dtype=np.float64)  # skip 标记（漏停→插入）
    gB = np.full((M + 1, N + 1), INF, dtype=np.float64)  # skip 停顿（多停→不动）
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


# ---------------------------------------------------------------------------
# 4. 静音码构造
# ---------------------------------------------------------------------------

def edge_for(target_ms):
    """短停顿（单码重复结构）无需保留过渡，整段替换（EDGE=0）；
    长停顿（CORE10 循环）保留头尾过渡防切字（EDGE=EDGE_KEEP_CODES）。"""
    return 0 if target_ms < 250 else EDGE_KEEP_CODES


def silence_codes(target_ms, ms_per_code=MS_PER_CODE, bias_ms=DUR_BIAS_MS):
    """目标时长 → 静音码序列（分段结构）。
    <250ms：单码重复 [5982]*M（短静音在 cfm 稳定，每码≈31ms，精度±100ms）
    >=250ms：CORE10 循环截取（精度±40ms），M=(target-bias)/ms_per_code
    """
    if target_ms < 250:
        M = max(1, int(round(target_ms / 31.0)))
        return [5982] * M
    M = max(1, int(round((target_ms - bias_ms) / ms_per_code)))
    return (CORE10 * ((M + 9) // 10))[:M]


def find_energy_valley(wav_np, center_sec, sr=22050, guard_ms=INSERT_GUARD_MS):
    """在 center_sec ± guard_ms 窗口内找帧能量最低点（插入落点，避免切字）。
    返回 (位置秒, 帧能量)。调用方用能量判定是否为真静音（< DETECT_THRESHOLD 才可插入）。"""
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


# ---------------------------------------------------------------------------
# 5. 动作执行（替换/插入）
# ---------------------------------------------------------------------------

def apply_actions(codes, actions):
    """按对齐结果修改 codes。
    actions:
      ("replace_seg", a, b, seg_list, conf)：整段替换 [a,b) 为给定码序列（延长：EDGE=2 形态，
          调用方已算好码数；过渡码由调用方在 [a,b) 外保留）
      ("insert", pos, 0, target_ms, 0, None)：在 pos 插入目标静音码
    返回 (new_codes, report)：report = [(操作, 实际码数, 匹配距离)]
    """
    codes = codes.clone()
    report = []
    for act in actions:
        kind = act[0]
        if kind == "replace_seg":
            a, b, seg_list, conf = act[1], act[2], act[3], act[4]
            seg = torch.tensor(seg_list, dtype=codes.dtype, device=codes.device)
            codes = torch.cat([codes[:, :a], seg.unsqueeze(0), codes[:, b:]], dim=1)
            report.append(("replace", len(seg_list), conf))
        else:  # insert
            a, target_ms = act[1], act[3]
            a = max(0, min(codes.shape[-1], a))
            seg = torch.tensor(silence_codes(target_ms), dtype=codes.dtype, device=codes.device)
            codes = torch.cat([codes[:, :a], seg.unsqueeze(0), codes[:, a:]], dim=1)
            report.append(("insert", len(seg), None))
    return codes, report


def silence_codes_extra(n):
    """延长时补充静音码：CORE10 循环截取 n 码。"""
    return (CORE10 * ((n + 9) // 10))[:n]


# ---------------------------------------------------------------------------
# 6. 波形级操作（缩短/延长，wav 域精确定位，无 codes 映射误差）
# ---------------------------------------------------------------------------

def find_core_region(wav_np, center_s, sr=22050, strict_mult=5.0, min_core_ms=30, window_s=0.6):
    """在 center_s ± window_s 窗口内找严格静音核心区（能量 < thr×strict_mult 的最长连续段）。
    返回 (core_start_s, core_end_s)；找不到返回 None。
    """
    frame = int(DETECT_FRAME_MS / 1000.0 * sr)
    thr_strict = DETECT_THRESHOLD * strict_mult
    lo = max(0, int((center_s - window_s) * sr))
    hi = min(len(wav_np) - frame, int((center_s + window_s) * sr))
    best = (0, lo, lo)
    cur = None
    for f in range(lo, hi, frame):
        e = float((wav_np[f:f + frame] ** 2).sum()) / frame
        if e < thr_strict:
            if cur is None:
                cur = f
        else:
            if cur is not None:
                if f - cur > best[0]:
                    best = (f - cur, cur, f)
                cur = None
    if cur is not None and hi - cur > best[0]:
        best = (hi - cur, cur, hi)
    if best[0] >= int(min_core_ms / 1000.0 * sr):
        return best[1] / sr, best[2] / sr
    return None


def wav_shrink_pause(wav_np, center_s, target_ms, sr=22050, margin_ms=15):
    """波形级缩短：静音核心裁剪到 target_ms（核心两端各留 margin_ms 缓冲防切字）。
    核心已短于目标时不动。返回新 wav（numpy 数组）。
    """
    core = find_core_region(wav_np, center_s, sr)
    if core is None:
        return wav_np
    cs, ce = core
    core_ms = (ce - cs) * 1000.0
    keep_ms = target_ms
    if core_ms <= keep_ms + margin_ms * 2:
        return wav_np  # 核心已够短，不动
    # 保留：核心开头 (target_ms - margin_ms) + 核心结尾 margin_ms
    keep_start_ms = max(margin_ms, target_ms - margin_ms)
    cut_at = int((cs + keep_start_ms / 1000.0) * sr)
    cut_to = int((ce - margin_ms / 1000.0) * sr)
    if cut_to > cut_at:
        return np.concatenate([wav_np[:cut_at], wav_np[cut_to:]])
    return wav_np


def wav_extend_pause(wav_np, center_s, target_ms, sr=22050, margin_ms=15):
    """波形级延长：静音核心中部插入静音到 target_ms（静音接静音，无拼接感）。
    核心已长于目标时不动。返回新 wav（numpy 数组）。
    """
    core = find_core_region(wav_np, center_s, sr)
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
