# -*- coding: utf-8 -*-
"""任务 manifest 读写与断点续跑判定。"""
import hashlib
import json
import os
from datetime import datetime


def params_hash(params):
    """参数签名：参数变更时任务失效重跑。"""
    blob = json.dumps(params, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(blob.encode("utf-8")).hexdigest()[:12]


def load_manifest(path):
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_manifest(path, manifest):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def new_manifest(task, params):
    return {
        "task": task,
        "created": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "params_hash": params_hash(params),
        "params": params,
        "segments": [],
    }


def get_segment(manifest, seg_id):
    for s in manifest.get("segments", []):
        if s["id"] == seg_id:
            return s
    return None


def add_segment(manifest, seg):
    manifest.setdefault("segments", []).append(seg)


def round_done(segment, round_no):
    for r in segment.get("rounds", []):
        if r.get("round") == round_no and r.get("status") == "ok":
            return True
    return False


def segment_complete(manifest, seg_id, rounds):
    seg = get_segment(manifest, seg_id)
    if seg is None:
        return False
    return all(round_done(seg, r) for r in range(1, rounds + 1))
