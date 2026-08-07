#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IndexTTS2-PauseControl 核心函数单元测试。

纯函数级测试：不需要 GPU、不需要模型权重、不需要音频文件。
输入是文本与合成波形，几秒内跑完，CI 中自动执行。

覆盖：
  - parse_pause_marks：解析位置/时长/标点环境（含多标记 clean 坐标回归）
  - detect_pauses：空音频、纯语音、短静音、临界时长、多段静音
  - nw_align：匹配/超限/插入/跳过各形态
  - find_core_region + wav_shrink/extend_pause：定位策略与波形操作

用法：
    python test/unit_test.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np

from indextts.utils import pause_control as pc

FAIL = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (("  " + detail) if detail else ""))
    if not cond:
        FAIL.append(name)


SR = 22050


def voice(dur_s, amp=0.3, seed=0):
    """合成语音段（带确定种子的噪声，能量高于静音阈值）。"""
    rng = np.random.RandomState(seed)
    return (rng.rand(int(dur_s * SR)) * 2 - 1) * amp


def silence(dur_s):
    return np.zeros(int(dur_s * SR))


# ============================================================
# 1. parse_pause_marks
# ============================================================

def test_parse_pause_marks():
    print("\n== parse_pause_marks ==")

    # 空文本
    c, m = pc.parse_pause_marks("")
    check("空文本：clean 为空", c == "" and m == [])

    # 无标记
    c, m = pc.parse_pause_marks("他停下了脚步。")
    check("无标记：原样返回", c == "他停下了脚步。" and m == [])

    # 单个标记（首标记：clean 坐标 == 原文本坐标）
    c, m = pc.parse_pause_marks("他停下脚步[pause:800ms]深吸一口气。")
    check("单标记解析", len(m) == 1 and m[0][1] == 800 and m[0][0] == 5, str(m))
    check("单标记替换为逗号", c == "他停下脚步，深吸一口气。", c)

    # 多标记：clean 坐标回归（原文本坐标会随标记数递增偏移，必须等于 clean 坐标）
    #   clean = 他停下脚步(0-4)，(5)深吸一口气(6-10)，(11)然后(12-13)，(14)推门(15-16)。(17)
    text = "他停下脚步[pause:800ms]深吸一口气[pause:200]然后[pause:1s]推门。"
    c, m = pc.parse_pause_marks(text)
    check("多标记数量", len(m) == 3)
    check("多标记坐标（标记0）", m[0][0] == 5, f"{m[0][0]} vs 5")
    check("多标记坐标（标记1，前有替换）", m[1][0] == 11, f"{m[1][0]} vs 11")
    check("多标记坐标（标记2，前有两次替换）", m[2][0] == 14, f"{m[2][0]} vs 14")
    check("多标记时长", m[0][1] == 800 and m[1][1] == 200 and m[2][1] == 1000, str([x[1] for x in m]))

    # 标记在开头 / 结尾（空串守卫：side 必须是 none，不能误判为 after/before）
    c, m = pc.parse_pause_marks("[pause:300ms]开门。")
    check("标记在开头", m[0][0] == 0 and c.startswith("，"), str(m))
    check("标记在开头 side=none", m[0][2] == "none", m[0][2])
    c, m = pc.parse_pause_marks("推门[pause:500ms]")
    check("标记在结尾", len(m) == 1 and c.endswith("，"), c)
    check("标记在结尾 side=none", m[0][2] == "none", m[0][2])

    # 标点环境
    _, m = pc.parse_pause_marks("他说不行[pause:500ms]。")
    check("side=before（标记后是句号）", m[0][2] == "before", m[0][2])
    _, m = pc.parse_pause_marks("他离开了。[pause:400ms]好吧")
    check("side=after（标记前是句号）", m[0][2] == "after", m[0][2])
    _, m = pc.parse_pause_marks("标准同样严苛[pause:800ms]不多一分。")
    check("side=none（普通标记）", m[0][2] == "none", m[0][2])


# ============================================================
# 2. detect_pauses
# ============================================================

def test_detect_pauses():
    print("\n== detect_pauses ==")

    # 空音频
    check("空音频：无停顿", pc.detect_pauses(np.zeros(0), SR) == [])

    # 纯语音无静音
    check("纯语音：无停顿", pc.detect_pauses(voice(1.0), SR) == [])

    # 极短静音（<100ms）不算停顿
    wav = np.concatenate([voice(0.3), silence(0.08), voice(0.3)])
    check("80ms 静音不计", pc.detect_pauses(wav, SR) == [])

    # 150ms 静音计入
    wav = np.concatenate([voice(0.3), silence(0.15), voice(0.3)])
    pauses = pc.detect_pauses(wav, SR)
    check("150ms 静音计入", len(pauses) == 1 and abs(pauses[0][1] - 150) < 60, str(pauses))

    # 多段静音（600ms + 250ms）
    wav = np.concatenate([voice(0.5), silence(0.6), voice(0.4), silence(0.25), voice(0.5)])
    pauses = pc.detect_pauses(wav, SR)
    check("多段静音检出 2 段", len(pauses) == 2, str([(round(p[0], 2), round(p[1])) for p in pauses]))
    check("多段静音时长", abs(pauses[0][1] - 600) < 60 and abs(pauses[1][1] - 250) < 60,
          f"{pauses[0][1]:.0f}/{pauses[1][1]:.0f}")

    # 全零音频（整段都是静音）
    check("全零音频：1 段长静音", len(pc.detect_pauses(np.zeros(int(1.0 * SR)), SR)) == 1)


# ============================================================
# 3. nw_align
# ============================================================

def test_nw_align():
    print("\n== nw_align ==")

    # 1v1 时间接近 → 匹配
    a, ins, sk, _ = pc.nw_align([(1.0, 800)], [(1.05, 780)], 5.0, 5.0)
    check("1v1 匹配", a == [0] and ins == [] and sk == [], str((a, ins, sk)))

    # 1v1 时间超限 → 禁止匹配，走插入
    a, ins, sk, _ = pc.nw_align([(1.0, 800)], [(3.0, 780)], 5.0, 5.0, max_t_diff=0.8)
    check("时间超限→插入", a == [-1] and ins == [0], str((a, ins)))

    # 2 标记 1 停顿 → 匹配 + 插入
    a, ins, sk, _ = pc.nw_align([(1.0, 800), (2.0, 300)], [(1.05, 780)], 5.0, 5.0)
    check("2v1：匹配+插入", a == [0, -1] and ins == [1], str((a, ins)))

    # 1 标记 2 停顿 → 匹配 + 跳过
    a, ins, sk, _ = pc.nw_align([(1.0, 800)], [(1.05, 780), (3.5, 200)], 5.0, 5.0)
    check("1v2：匹配+跳过", a == [0] and sk == [1], str((a, sk)))

    # w_dur=0.2 时间主导：停顿时长接近非对应标记目标时仍按时间顺序匹配
    a, ins, sk, _ = pc.nw_align([(0.5, 750), (2.0, 200)], [(0.55, 229), (2.05, 778)], 5.0, 5.0)
    check("w_dur=0.2 顺序匹配", a == [0, 1], str(a))

    # 边界：无停顿（N=0，模型整段没停）→ 全部标记走插入
    a, ins, sk, _ = pc.nw_align([(0.5, 800)], [], 5.0, 5.0)
    check("N=0：标记全走插入", a == [-1] and ins == [0] and sk == [], str((a, ins, sk)))

    # 边界：无标记（M=0）→ 全部停顿视为多余
    a, ins, sk, _ = pc.nw_align([], [(0.5, 800), (1.5, 300)], 5.0, 5.0)
    check("M=0：停顿全跳过", a == [] and ins == [] and sk == [0, 1], str((a, ins, sk)))


# ============================================================
# 4. find_core_region + 波形操作
# ============================================================

def test_core_and_wave_ops():
    print("\n== find_core_region + wav_shrink/extend ==")

    # 两段停顿（0.2s 在 0.55s 处、0.5s 在 1.15s 处），窗口覆盖两者
    wav2 = np.concatenate([voice(0.5), silence(0.2), voice(0.2), silence(0.5), voice(0.5)])
    nearest = pc.find_core_region(wav2, 0.8, SR, window_s=0.5, select="nearest")
    longest = pc.find_core_region(wav2, 0.8, SR, window_s=0.5, select="longest")
    check("nearest 取最近的停顿", nearest is not None and abs(nearest[0] - 0.55) < 0.15, str(nearest))
    # 窗口 [0.3,1.3] 截断长停顿：B 被截为 0.4s 仍长于 A 的 0.2s
    check("longest 取窗口内最长", longest is not None and abs(longest[0] - 0.9) < 0.15, str(longest))

    # 缩短：600ms → 200ms
    wav = np.concatenate([voice(0.5), silence(0.6), voice(0.4), silence(0.25), voice(0.5)])
    pauses = pc.detect_pauses(wav, SR)
    mid0 = pauses[0][0] + pauses[0][1] / 2000.0
    shr = pc.wav_shrink_pause(wav, mid0, 200, SR)
    sp = pc.detect_pauses(shr, SR)
    check("缩短 600→~200ms", len(sp) == 2 and abs(sp[0][1] - 200) < 60, f"{sp[0][1]:.0f}")

    # 延长：600ms → 1000ms
    ext = pc.wav_extend_pause(wav, mid0, 1000, SR)
    ep = pc.detect_pauses(ext, SR)
    check("延长 600→~1000ms", len(ep) == 2 and abs(ep[0][1] - 1000) < 60, f"{ep[0][1]:.0f}")

    # 不动分支：目标大于当前时长时缩短不改变波形
    same = pc.wav_shrink_pause(wav, mid0, 1500, SR)
    check("缩短目标更大：不动", len(same) == len(wav))


def main():
    test_parse_pause_marks()
    test_detect_pauses()
    test_nw_align()
    test_core_and_wave_ops()
    print("\n" + "=" * 50)
    print("UNIT_TEST_PASS" if not FAIL else f"UNIT_TEST_FAIL ({len(FAIL)}): {FAIL}")
    sys.exit(0 if not FAIL else 1)


if __name__ == "__main__":
    main()
