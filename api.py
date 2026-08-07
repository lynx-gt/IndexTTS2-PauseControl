# -*- coding: utf-8 -*-
"""IndexTTS 节点后端 API：为前端动态下拉提供数据（任务/段/参考音频）。"""
import json
import os

from aiohttp import web

import folder_paths
from server import PromptServer


def _manifest_path(task_dir):
    return os.path.join(task_dir, "manifest.json")


@PromptServer.instance.routes.get("/indextts/tasks")
async def list_tasks(request):
    """列出输出目录下所有含 manifest.json 的任务目录。"""
    root = folder_paths.get_output_directory()
    tasks = []
    if os.path.isdir(root):
        for d in sorted(os.listdir(root)):
            mf = _manifest_path(os.path.join(root, d))
            if not os.path.isfile(mf):
                continue
            try:
                with open(mf, "r", encoding="utf-8") as f:
                    m = json.load(f)
            except Exception:
                continue
            segs = m.get("segments", [])
            done = sum(1 for s in segs if s.get("status") == "ok")
            tasks.append({
                "name": d,
                "path": os.path.join(root, d),
                "progress": f"{done}/{len(segs)}",
                "created": m.get("created", ""),
            })
    return web.json_response(tasks)


@PromptServer.instance.routes.get("/indextts/tasks/{name}/segments")
async def list_segments(request):
    """列出任务内片段（id + 状态 + 文本预览）。"""
    name = request.match_info["name"]
    mf = _manifest_path(os.path.join(folder_paths.get_output_directory(), name))
    if not os.path.isfile(mf):
        return web.json_response([], status=404)
    try:
        with open(mf, "r", encoding="utf-8") as f:
            m = json.load(f)
    except Exception:
        return web.json_response([], status=500)
    segs = [{
        "id": s.get("id"),
        "status": s.get("status", "pending"),
        "text": (s.get("text") or "")[:24],
    } for s in m.get("segments", [])]
    return web.json_response(segs)


@PromptServer.instance.routes.get("/indextts/refs")
async def list_refs(request):
    """列出参考音频（相对 root 的 wav 路径）。root 默认 ComfyUI/input/references。"""
    root = request.query.get("root", "")
    if not root:
        root = os.path.join(folder_paths.get_input_directory(), "references")
    files = []
    if os.path.isdir(root):
        for dp, _dn, fn in os.walk(root):
            for f in sorted(fn):
                if f.lower().endswith((".wav", ".mp3", ".m4a", ".flac")):
                    rel = os.path.relpath(os.path.join(dp, f), root)
                    files.append(rel.replace("\\", "/"))
    return web.json_response(files)
