# -*- coding: utf-8 -*-
"""IndexTTS-Node 节点定义（阶段 1：Loader / Unload / 单条生成）。

交互原则：能选择就不手输（下拉/文件选择优先）；参数默认值取自全书定版参数
（temp 0.6 / top_p 0.8 / beams 4 / emo 0.75，FP32）。
"""
import os
import sys

# ComfyUI 加载 custom node 时不一定把节点目录加入 sys.path，
# 这里显式加入，保证 `from indextts...` 解析到本目录下的 indextts 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gc
import re
import torch
import soundfile as sf
from datetime import datetime

import folder_paths

# 全局单例缓存：同一 (model_dir, fp16, low_vram) 配置只加载一次
MODEL_CACHE = {}

# 停顿标记（与 scripts/fix/pause_processor.py 一致）
PAUSE_PATTERN = re.compile(r"\[(?:pause|wait|stop):(\d+(?:\.\d+)?)(ms|s)?\]", re.IGNORECASE)


def _get_tts(model_dir, fp16, low_vram):
    """懒加载 IndexTTS2 单例；配置变更时先释放旧模型，防止多份驻留显存。"""
    key = (str(model_dir), bool(fp16), bool(low_vram))
    if key in MODEL_CACHE:
        return MODEL_CACHE[key]
    for k in list(MODEL_CACHE):
        try:
            MODEL_CACHE[k].offload_model()
        except Exception:
            pass
        MODEL_CACHE.pop(k, None)
    gc.collect()
    torch.cuda.empty_cache()
    from indextts.infer_v2 import IndexTTS2
    tts = IndexTTS2(
        cfg_path=os.path.join(model_dir, "config.yaml"),
        model_dir=model_dir,
        use_fp16=fp16,
        low_vram=low_vram,
    )
    MODEL_CACHE[key] = tts
    return tts


def _strip_pause_marks(text):
    """把 [pause:N] 标记替换为逗号后送 TTS（与 pause_processor 生成侧行为一致）。"""
    return PAUSE_PATTERN.sub("，", text)


def _load_audio_tensor(path):
    """读 wav 为 ComfyUI AUDIO（新内核格式：dict {waveform: [B,C,T] float32, sample_rate}）。"""
    data, sr = sf.read(path, dtype="float32", always_2d=True)  # [T, C]
    wav = torch.from_numpy(data).permute(1, 0).unsqueeze(0)   # [1, C, T]
    return {"waveform": wav, "sample_rate": sr}


def _clean_path(s):
    """去掉用户输入路径首尾误带的引号。"""
    s = (s or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1].strip()
    return s


def _resolve_ref(value):
    """参考音频路径解析：下拉选项是相对路径（相对 input/references），这里拼成绝对路径；
    手输的绝对路径 / SMB 路径原样返回。"""
    value = _clean_path(value)
    if not value:
        return value
    if os.path.isfile(value):
        return value
    base = os.path.join(folder_paths.get_input_directory(), "references")
    cand = os.path.join(base, value.replace("/", os.sep))
    if os.path.isfile(cand):
        return cand
    return value


def _check_interrupt():
    """检测 ComfyUI 前端 Cancel 信号，中断批量循环。"""
    try:
        from server import PromptServer
        from comfy.model_management import InterruptProcessingException
        if PromptServer.instance.interrupt_processing:
            raise InterruptProcessingException()
    except InterruptProcessingException:
        raise
    except Exception:
        pass


def _free_all_models():
    for k in list(MODEL_CACHE):
        try:
            MODEL_CACHE[k].offload_model()
        except Exception:
            pass
        MODEL_CACHE.pop(k, None)
    gc.collect()
    torch.cuda.empty_cache()


class IndexTTSLoader:
    """IndexTTS2 模型加载（全局单例，懒加载；默认 FP32）。"""

    @classmethod
    def INPUT_TYPES(cls):
        default_dir = os.path.join(folder_paths.models_dir, "index_tts")
        return {
            "required": {
                "model_dir": ("STRING", {"default": default_dir}),
                "fp16": ("BOOLEAN", {"default": False}),
                "low_vram": ("BOOLEAN", {"default": False}),
            }
        }

    RETURN_TYPES = ("INDEXTTS_MODEL",)
    RETURN_NAMES = ("model",)
    FUNCTION = "load"
    CATEGORY = "IndexTTS"

    def load(self, model_dir, fp16, low_vram):
        return (_get_tts(model_dir, fp16, low_vram),)


class IndexTTSUnload:
    """释放 IndexTTS 模型显存（TTS 跑完、进视频流程前调用）。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("INDEXTTS_MODEL",)}}

    RETURN_TYPES = ()
    FUNCTION = "unload"
    OUTPUT_NODE = True
    CATEGORY = "IndexTTS"

    def unload(self, model):
        _free_all_models()
        return ()


class IndexTTSSingle:
    """单条 TTS 生成。pause_mode=True 时 [pause:N] 走全波形精确停顿（生成一遍 → 静音核心延长/缩短/插入，免重解码）。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("INDEXTTS_MODEL",),
                "text": ("STRING", {"multiline": True, "default": "测试一下。"}),
                "spk_ref": ("STRING", {"default": ""}),
                "emo_ref": ("STRING", {"default": ""}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2**63 - 1}),
                "temperature": ("FLOAT", {"default": 0.6, "min": 0.01, "max": 2.0, "step": 0.05}),
                "top_p": ("FLOAT", {"default": 0.8, "min": 0.01, "max": 1.0, "step": 0.05}),
                "top_k": ("INT", {"default": 20, "min": 0, "max": 200}),
                "num_beams": ("INT", {"default": 4, "min": 1, "max": 8}),
                "do_sample": ("BOOLEAN", {"default": True}),
                "repetition_penalty": ("FLOAT", {"default": 10.0, "min": 1.0, "max": 30.0, "step": 0.5}),
                "emo_alpha": ("FLOAT", {"default": 0.75, "min": 0.0, "max": 1.0, "step": 0.05}),
                "speaking_speed": ("FLOAT", {"default": 1.0, "min": 0.5, "max": 2.0, "step": 0.1}),
                "interval_silence": ("INT", {"default": 400, "min": 0, "max": 2000,
                                             "tooltip": "段间插入静音（ms）：每段结束到下一段开始的固定停顿"}),
                "pause_mode": ("BOOLEAN", {"default": False, "tooltip": "开启 [pause:N] 精确停顿控制（全波形：生成后检测停顿，静音核心延长/缩短/插入，免重解码）"}),
                "detect_cfm_steps": ("INT", {"default": 25, "min": 10, "max": 50, "step": 1,
                                             "tooltip": "已弃用（全波形版生成只跑一次 diffusion_steps，此参数无作用），保留兼容旧工作流"}),
                "out_name": ("STRING", {"default": ""}),
            }
        }

    RETURN_TYPES = ("AUDIO", "STRING", "INT", "STRING")
    RETURN_NAMES = ("audio", "wav_path", "used_seed", "log")
    FUNCTION = "generate"
    CATEGORY = "IndexTTS"

    def generate(
        self, model, text, spk_ref, emo_ref, seed, temperature, top_p, top_k,
        num_beams, do_sample, repetition_penalty, emo_alpha, speaking_speed, interval_silence,
        pause_mode, detect_cfm_steps, out_name,
    ):
        spk_ref = _resolve_ref(spk_ref)
        emo_ref = _resolve_ref(emo_ref)
        if not spk_ref or not os.path.isfile(spk_ref):
            raise ValueError(f"音色参考文件不存在: {spk_ref}")
        if not text.strip():
            raise ValueError("文本为空")

        out_dir = os.path.join(folder_paths.get_output_directory(), "indextts")
        os.makedirs(out_dir, exist_ok=True)
        if not out_name:
            out_name = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out_path = os.path.join(out_dir, out_name + ".wav")

        # pause_mode=True 时 [pause:N] 交给 infer 内部处理（全波形精确控制）；
        # 否则保持旧行为（标记替换为逗号，不处理停顿）
        infer_text = text if pause_mode else _strip_pause_marks(text)
        result = model.infer(
            spk_audio_prompt=spk_ref,
            emo_audio_prompt=emo_ref if emo_ref and os.path.isfile(emo_ref) else None,
            emo_alpha=emo_alpha,
            text=infer_text,
            output_path=out_path,
            seed=None if seed < 0 else seed,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            num_beams=num_beams,
            do_sample=do_sample,
            repetition_penalty=repetition_penalty,
            speaking_speed=speaking_speed,
            interval_silence=interval_silence,
            pause_mode=pause_mode,
            detect_cfm_steps=detect_cfm_steps,
        )
        used_seed = seed
        seed_file = out_path + ".seed"
        if os.path.isfile(seed_file):
            with open(seed_file, "r", encoding="utf-8") as f:
                used_seed = int(f.read().strip())
        audio = _load_audio_tensor(out_path)
        log = f"已生成: {out_path}\n实际 seed: {used_seed}"
        return (audio, out_path, used_seed, log)


class IndexTTSBatch:
    """批量生成（分句稿或多行文本），rounds 候选 + manifest 断点续跑。
    pause_mode=True：文本 [pause:N] 走全波形精确停顿（infer 内部处理，免 whisper）；
    pause_mode=False：保持旧行为（whisper 后处理）。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("INDEXTTS_MODEL",),
                "segments_md": ("STRING", {"default": ""}),
                "text": ("STRING", {"multiline": True, "default": ""}),
                "spk_ref": ("STRING", {"default": ""}),
                "emo_strategy": (["固定", "目录随机"], {"default": "固定"}),
                "emo_ref": ("STRING", {"default": ""}),
                "emo_dir": ("STRING", {"default": ""}),
                "rounds": ("INT", {"default": 3, "min": 1, "max": 10}),
                "tag": ("STRING", {"default": "批量生成"}),
                "output_dir": ("STRING", {"default": ""}),
                "start": ("INT", {"default": 0, "min": 0}),
                "end": ("INT", {"default": 0, "min": 0}),
                "auto_pause": ("BOOLEAN", {"default": True}),
                "whisper_model": ("STRING", {"default": "base"}),
                "pause_mode": ("BOOLEAN", {"default": False, "tooltip": "开启 [pause:N] 全波形精确停顿（infer 内部处理，免 whisper 后处理；开启后 auto_pause 后处理自动跳过）"}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2**63 - 1}),
                "temperature": ("FLOAT", {"default": 0.6, "min": 0.01, "max": 2.0, "step": 0.05}),
                "top_p": ("FLOAT", {"default": 0.8, "min": 0.01, "max": 1.0, "step": 0.05}),
                "top_k": ("INT", {"default": 20, "min": 0, "max": 200}),
                "num_beams": ("INT", {"default": 4, "min": 1, "max": 8}),
                "do_sample": ("BOOLEAN", {"default": True}),
                "repetition_penalty": ("FLOAT", {"default": 10.0, "min": 1.0, "max": 30.0, "step": 0.5}),
                "emo_alpha": ("FLOAT", {"default": 0.75, "min": 0.0, "max": 1.0, "step": 0.05}),
                "speaking_speed": ("FLOAT", {"default": 1.0, "min": 0.5, "max": 2.0, "step": 0.1}),
                "interval_silence": ("INT", {"default": 400, "min": 0, "max": 2000,
                                             "tooltip": "段间插入静音（ms）：每段结束到下一段开始的固定停顿"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("task_dir", "manifest_path", "progress")
    FUNCTION = "run_batch"
    CATEGORY = "IndexTTS"
    OUTPUT_NODE = True

    def run_batch(
        self, model, segments_md, text, spk_ref, emo_strategy, emo_ref, emo_dir,
        rounds, tag, output_dir, start, end, auto_pause, whisper_model, pause_mode, seed,
        temperature, top_p, top_k, num_beams, do_sample, repetition_penalty,
        emo_alpha, speaking_speed, interval_silence,
    ):
        from lib.segments import parse_segments_md, parse_text_lines, pick_emotion_ref
        from lib.manifest import (load_manifest, save_manifest, new_manifest,
                                  get_segment, add_segment, round_done, segment_complete, params_hash)
        from lib.pause import parse_pause_tags, process_pause_marks

        spk_ref = _resolve_ref(spk_ref)
        emo_ref = _resolve_ref(emo_ref)
        if not spk_ref or not os.path.isfile(spk_ref):
            raise ValueError(f"音色参考文件不存在: {spk_ref}")

        # 1. 解析文本
        segments_md = _clean_path(segments_md)
        emo_dir = _clean_path(emo_dir)
        if segments_md and os.path.isfile(segments_md):
            segs = parse_segments_md(segments_md)
        else:
            segs = parse_text_lines(text)
        if not segs:
            raise ValueError("没有可用的文本（分句稿路径无效且文本为空）")
        if start:
            segs = [s for s in segs if s["index"] >= start]
        if end:
            segs = [s for s in segs if s["index"] <= end]
        if not segs:
            raise ValueError("start/end 范围内没有片段")

        # 2. 任务目录（填了即用，否则自动创建；续跑 = 填已有目录）
        output_dir = _clean_path(output_dir)
        if output_dir:
            task_dir = output_dir.strip()
        else:
            task_dir = os.path.join(folder_paths.get_output_directory(),
                                    f"{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        os.makedirs(task_dir, exist_ok=True)
        mf_path = os.path.join(task_dir, "manifest.json")

        # 3. manifest 与参数一致性
        params = {
            "segments_md": segments_md, "text": text, "spk_ref": spk_ref,
            "emo_strategy": emo_strategy, "emo_ref": emo_ref, "emo_dir": emo_dir,
            "rounds": rounds, "auto_pause": auto_pause, "whisper_model": whisper_model,
            "pause_mode": pause_mode,
            "seed": seed, "temperature": temperature, "top_p": top_p, "top_k": top_k,
            "num_beams": num_beams, "do_sample": do_sample,
            "repetition_penalty": repetition_penalty, "emo_alpha": emo_alpha,
            "speaking_speed": speaking_speed, "interval_silence": interval_silence,
        }
        manifest = load_manifest(mf_path)
        if manifest is None or manifest.get("params_hash") != params_hash(params):
            manifest = new_manifest(tag, params)
            save_manifest(mf_path, manifest)

        whisper_root = os.path.join(folder_paths.models_dir, "index_tts", "whisper")
        total = len(segs)
        done = 0
        for seg in segs:
            _check_interrupt()
            seg_id = seg["index"]
            if segment_complete(manifest, seg_id, rounds):
                done += 1
                continue
            entry = get_segment(manifest, seg_id)
            if entry is None:
                entry = {"id": seg_id, "text": seg["text"], "emotion": seg["emotion"],
                         "emo_ref": "", "rounds": [], "status": "ok"}
                add_segment(manifest, entry)
            entry["text"] = seg["text"]
            entry["emotion"] = seg["emotion"]
            emo = pick_emotion_ref(seg["emotion"], emo_strategy, emo_ref, emo_dir)
            entry["emo_ref"] = emo or ""
            marks, clean_text = parse_pause_tags(seg["text"])

            for rnd in range(1, rounds + 1):
                if round_done(entry, rnd):
                    continue
                out_path = os.path.join(task_dir, f"{seg_id:03d}_{rnd}.wav")
                infer_seed = None if seed < 0 else int(seed) + rnd * 1000
                # pause_mode=True：文本原样传 infer（内部 parse + 全波形处理），旧 whisper 后处理跳过
                model.infer(
                    spk_audio_prompt=spk_ref,
                    emo_audio_prompt=emo,
                    emo_alpha=emo_alpha,
                    text=seg["text"] if pause_mode else clean_text,
                    output_path=out_path,
                    seed=infer_seed,
                    temperature=temperature, top_p=top_p, top_k=top_k,
                    num_beams=num_beams, do_sample=do_sample,
                    repetition_penalty=repetition_penalty,
                    speaking_speed=speaking_speed, interval_silence=interval_silence,
                    pause_mode=pause_mode,
                    detect_cfm_steps=25,
                )
                used_seed = infer_seed
                seed_file = out_path + ".seed"
                if os.path.isfile(seed_file):
                    with open(seed_file, "r", encoding="utf-8") as f:
                        used_seed = int(f.read().strip())
                dur = 0.0
                try:
                    import wave as _wave
                    with _wave.open(out_path, "rb") as w:
                        dur = round(w.getnframes() / w.getframerate(), 3)
                except Exception:
                    pass
                # 自动 pause 后处理（旧 whisper 方案，pause_mode=True 时跳过——全波形已在 infer 内部完成）
                records = []
                if not pause_mode and auto_pause and marks:
                    processed = os.path.join(task_dir, f"{seg_id:03d}_{rnd}_p.wav")
                    records = process_pause_marks(
                        out_path, clean_text, marks, processed,
                        whisper_model=whisper_model, whisper_root=whisper_root)
                    if records and not any(r.get("type") == "fail" for r in records):
                        os.replace(processed, out_path)
                    elif records:
                        os.remove(processed) if os.path.isfile(processed) else None
                # 更新 manifest（每轮落盘，断点安全）
                rounds_list = [r for r in entry["rounds"] if r.get("round") != rnd]
                rounds_list.append({"round": rnd, "seed": used_seed, "wav": os.path.basename(out_path),
                                    "dur": dur, "status": "ok", "marks": records})
                entry["rounds"] = rounds_list
                save_manifest(mf_path, manifest)
            done += 1

        progress = f"任务完成：{done}/{total} 段 · 目录 {task_dir}"
        return (task_dir, mf_path, progress)


class IndexTTSListen:
    """候选试听：按任务目录 + 段号输出该段 3 轮的 AUDIO（任务/段号支持动态下拉）。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "task": ([""], {}),
                "custom_task": ("STRING", {"default": ""}),
                "segment": (["1"], {}),
                "custom_segment": ("INT", {"default": 0, "min": 0}),
                "task_dir": ("STRING", {"default": "",
                                        "tooltip": "接收「批量生成」节点的 task_dir 输出（连线传入时优先于 task/custom_task）"}),
                "accept_round": ("INT", {"default": 0, "min": 0, "max": 3, "step": 1,
                                         "tooltip": "验收标记：0=仅试听不改状态；1/2/3=标记该轮通过验收（写入任务 manifest.json，供后续流程选用）"}),
            }
        }

    RETURN_TYPES = ("AUDIO", "AUDIO", "AUDIO", "STRING")
    RETURN_NAMES = ("round1", "round2", "round3", "log")
    FUNCTION = "listen"
    CATEGORY = "IndexTTS"
    OUTPUT_NODE = True

    def listen(self, task, custom_task, segment, custom_segment, task_dir, accept_round):
        # 优先级：连线传入的 task_dir > 手动填写的 custom_task > 下拉 task
        tdir = _clean_path(task_dir) if _clean_path(task_dir) else \
            (_clean_path(custom_task) if _clean_path(custom_task) else _clean_path(task))
        if not tdir:
            raise ValueError("任务目录为空：请先运行「批量生成」，然后刷新页面从任务下拉选择；或手动填写任务目录路径")
        if not os.path.isdir(tdir):
            raise ValueError(f"任务目录无效: {tdir}")
        idx = int(custom_segment) if custom_segment else int(segment)
        # ---- 验收标记：accept_round>0 时写入任务 manifest.json ----
        mf_path = os.path.join(tdir, "manifest.json")
        if accept_round > 0:
            if not os.path.isfile(mf_path):
                raise ValueError(f"验收标记失败：任务目录下没有 manifest.json（{mf_path}）")
            import json as _json
            with open(mf_path, "r", encoding="utf-8") as f:
                mf = _json.load(f)
            entry = None
            for e in mf.get("segments", []):
                if e.get("id") == idx or e.get("index") == idx:
                    entry = e
                    break
            if entry is None:
                ids = sorted(e.get("id") for e in mf.get("segments", []))
                raise ValueError(
                    f"验收标记失败：manifest 中没有段 {idx}（实际段号：{ids}）。"
                    f"提示：每行文本=一段，001_x 是段1 的第x轮候选，不是第x段")
            for r in entry.get("rounds", []):
                r["accepted"] = (r.get("round") == accept_round)
            if not any(r.get("round") == accept_round for r in entry.get("rounds", [])):
                entry.setdefault("rounds", []).append(
                    {"round": accept_round, "wav": f"{idx:03d}_{accept_round}.wav", "accepted": True})
            with open(mf_path, "w", encoding="utf-8") as f:
                _json.dump(mf, f, ensure_ascii=False, indent=2)
        # ---- 读取验收状态（用于 log 展示）----
        accept_map = {}
        if os.path.isfile(mf_path):
            import json as _json
            try:
                with open(mf_path, "r", encoding="utf-8") as f:
                    mf = _json.load(f)
                for e in mf.get("segments", []):
                    if e.get("id") == idx or e.get("index") == idx:
                        for r in e.get("rounds", []):
                            accept_map[r.get("round")] = bool(r.get("accepted"))
                        break
            except Exception:
                pass
        outs, logs = [], []
        for rnd in (1, 2, 3):
            p = os.path.join(tdir, f"{idx:03d}_{rnd}.wav")
            if os.path.isfile(p):
                outs.append(_load_audio_tensor(p))
            else:
                logs.append(f"{idx:03d}_{rnd}.wav 不存在")
                sr = 22050
                wav = torch.zeros(1, 1, int(sr * 0.5))
                outs.append({"waveform": wav, "sample_rate": sr})
        # 提示超出 3 轮的候选（rounds>3 时生成但试听节点只显示前 3 轮）
        extra = [r for r in (4, 5, 6, 7, 8, 9, 10)
                 if os.path.isfile(os.path.join(tdir, f"{idx:03d}_{r}.wav"))]
        if extra:
            logs.append(f"提示：该段还有第 {'/'.join(map(str, extra))} 轮候选，Listen 仅显示前 3 轮（可把 accept_round 之外的部分用文件方式试听）")
        if accept_map:
            logs.append("验收状态: " + " ".join(
                f"轮{rnd}={'✓已通过' if accept_map.get(rnd) else '未验收'}" for rnd in (1, 2, 3)))
        if accept_round > 0:
            logs.append(f"→ 段{idx} 第{accept_round}轮已标记验收通过（已写入 manifest.json）")
        return (*outs, "\n".join(logs))


class IndexTTSFix:
    """停顿修复：从任务记录读停顿清单（批量 pause 时已落盘），按序号或时间点调整/删除。

    调整串格式（逗号分隔）：`2:800, 3:0`（序号:目标ms，0=删除）或 `7.53:500`（时间点:目标ms）。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "task": ([""], {}),
                "custom_task": ("STRING", {"default": ""}),
                "segment": (["1"], {}),
                "custom_segment": ("INT", {"default": 0, "min": 0}),
                "round": ("INT", {"default": 1, "min": 1, "max": 10}),
                "marks": ("STRING", {"multiline": True, "default": ""}),
                "out_suffix": ("STRING", {"default": "_fixed"}),
            }
        }

    RETURN_TYPES = ("AUDIO", "STRING", "STRING")
    RETURN_NAMES = ("audio", "wav_path", "log")
    FUNCTION = "fix"
    CATEGORY = "IndexTTS"
    OUTPUT_NODE = True

    def fix(self, task, custom_task, segment, custom_segment, round, marks, out_suffix):
        from lib.pause import fix_pause_at

        tdir = _clean_path(custom_task) if _clean_path(custom_task) else _clean_path(task)
        if not tdir:
            raise ValueError("任务目录为空：请先运行「批量生成」，然后刷新页面从任务下拉选择")
        if not os.path.isdir(tdir):
            raise ValueError(f"任务目录无效: {tdir}")
        idx = int(custom_segment) if custom_segment else int(segment)
        src = os.path.join(tdir, f"{idx:03d}_{round}.wav")
        if not os.path.isfile(src):
            raise ValueError(f"源文件不存在: {src}")
        if not marks.strip():
            raise ValueError("调整串为空（格式：`2:800, 3:0` 或 `7.53:500`）")

        # 解析调整串
        points = []
        for part in marks.replace("，", ",").split(","):
            part = part.strip()
            if not part:
                continue
            if ":" not in part:
                raise ValueError(f"无法解析: {part}（格式 序号:目标ms 或 时间点:目标ms）")
            k, v = part.rsplit(":", 1)
            target = int(float(v.strip()))
            k = k.strip()
            if "." in k:
                points.append((float(k), target))
            else:
                # 序号模式：从 manifest 记录里取该标记的时间戳
                mf = os.path.join(tdir, "manifest.json")
                sec = None
                if os.path.isfile(mf):
                    import json as _json
                    try:
                        with open(mf, "r", encoding="utf-8") as f:
                            man = _json.load(f)
                        for s in man.get("segments", []):
                            if s.get("id") == idx:
                                for r in s.get("rounds", []):
                                    if r.get("round") == round:
                                        for mk in r.get("marks", []):
                                            if mk.get("no") == int(k) and mk.get("pos_sec"):
                                                sec = mk["pos_sec"]
                    except Exception:
                        pass
                if sec is None:
                    raise ValueError(f"标记 #{k} 无时间戳记录（该段无 pause 标记？），请用时间点模式")
                points.append((sec, target))

        out_path = os.path.join(tdir, f"{idx:03d}_{round}{out_suffix}.wav")
        records = fix_pause_at(src, points, out_path)
        log_lines = ["调整完成:"]
        for r in records:
            if r.get("type") == "skip":
                continue
            if r.get("type") == "fail":
                log_lines.append(f"  {r.get('sec')}s: {r.get('reason')}")
            else:
                log_lines.append(
                    f"  {r.get('sec')}s: 当前 {r.get('orig_ms')}ms -> 目标 {r.get('target_ms')}ms"
                    + ("（已删除）" if r.get("type") == "delete" else ""))
        log = "\n".join(log_lines)
        audio = _load_audio_tensor(out_path)
        return (audio, out_path, log)


class IndexTTSSrt:
    """定版 + SRT：按 manifest 顺序 + 每段选择轮次，读最终 wav 实际时长段级累加生成字幕。

    chosen 格式：`1,2,1,3`（每段轮次，按段顺序）；单值 `3` = 全部用第 3 轮；空 = 全 1。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "task": ([""], {}),
                "custom_task": ("STRING", {"default": ""}),
                "chosen": ("STRING", {"default": ""}),
                "offset_ms": ("INT", {"default": 0, "min": 0, "max": 600000}),
                "srt_path": ("STRING", {"default": ""}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("srt_path", "srt_text", "log")
    FUNCTION = "build_srt"
    CATEGORY = "IndexTTS"
    OUTPUT_NODE = True

    def build_srt(self, task, custom_task, chosen, offset_ms, srt_path):
        import wave as _wave
        from lib.pause import PAUSE_PATTERN

        tdir = _clean_path(custom_task) if _clean_path(custom_task) else _clean_path(task)
        mf = os.path.join(tdir, "manifest.json")
        if not tdir or not os.path.isfile(mf):
            raise ValueError(f"manifest 不存在: {mf}")
        import json as _json
        with open(mf, "r", encoding="utf-8") as f:
            manifest = _json.load(f)

        segs = sorted(manifest.get("segments", []), key=lambda s: s.get("id", 0))
        if not segs:
            raise ValueError("manifest 中没有片段")
        chosen_list = [int(x) for x in chosen.replace("，", ",").split(",") if x.strip()]
        if len(chosen_list) == 1 and len(segs) > 1:
            chosen_list = chosen_list * len(segs)
        if not chosen_list:
            chosen_list = [1] * len(segs)

        lines, log_lines, t_ms = [], [], offset_ms
        missing = []
        for i, seg in enumerate(segs):
            rnd = chosen_list[i] if i < len(chosen_list) else 1
            wav_path = os.path.join(tdir, f"{seg['id']:03d}_{rnd}.wav")
            if not os.path.isfile(wav_path):
                missing.append(f"{seg['id']:03d}_{rnd}.wav")
                continue
            with _wave.open(wav_path, "rb") as w:
                dur_ms = int(w.getnframes() / w.getframerate() * 1000)
            start_ms = t_ms
            end_ms = t_ms + dur_ms
            text = PAUSE_PATTERN.sub("，", seg.get("text", "")).strip()
            def _fmt(ms):
                h, ms = divmod(ms, 3600000)
                m, ms = divmod(ms, 60000)
                s, ms = divmod(ms, 1000)
                return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
            lines.append(f"{i + 1}\n{_fmt(start_ms)} --> {_fmt(end_ms)}\n{text}\n")
            t_ms = end_ms
            log_lines.append(f"#{seg['id']:03d} 轮{rnd} {dur_ms}ms  {text[:20]}...")

        if missing:
            log_lines.append("缺失文件（跳过）: " + ", ".join(missing))
        srt_text = "\n".join(lines)
        out = srt_path.strip() if srt_path.strip() else os.path.join(tdir, "字幕.srt")
        with open(out, "w", encoding="utf-8") as f:
            f.write(srt_text)
        log = "\n".join(log_lines)
        return (out, srt_text, log)


NODE_CLASS_MAPPINGS = {
    "IndexTTSLoader": IndexTTSLoader,
    "IndexTTSUnload": IndexTTSUnload,
    "IndexTTSSingle": IndexTTSSingle,
    "IndexTTSBatch": IndexTTSBatch,
    "IndexTTSListen": IndexTTSListen,
    "IndexTTSFix": IndexTTSFix,
    "IndexTTSSrt": IndexTTSSrt,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "IndexTTSLoader": "IndexTTS Loader",
    "IndexTTSUnload": "IndexTTS Unload（释放显存）",
    "IndexTTSSingle": "IndexTTS 单条生成",
    "IndexTTSBatch": "IndexTTS 批量生成",
    "IndexTTSListen": "IndexTTS 候选试听",
    "IndexTTSFix": "IndexTTS 停顿修复",
    "IndexTTSSrt": "IndexTTS 定版 + SRT",
}
