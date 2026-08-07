#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IndexTTS2-PauseControl 一键安装脚本（跨平台）。

用法：
    python install.py [--comfyui-dir <ComfyUI 根目录>]

功能：
    1. 定位 ComfyUI 目录（自动探测或手动指定）
    2. 检查本节点是否位于 custom_nodes/ 下
    3. 安装依赖到 ComfyUI 的 Python 环境
    4. 检查模型权重目录，缺失时给出下载指引

说明：模型权重（约 11.8GB）不在本仓库，需按指引从官方渠道下载。
"""
import argparse
import os
import shutil
import subprocess
import sys

REQUIRED_TOP = ["json5", "munch", "soundfile"]
OPTIONAL_TOP = ["descript-audiotools", "flatten_dict", "julius", "argbind",
                "markdown2", "randomname", "pystoi", "tensorboard"]
MODEL_DIR_NAME = "index_tts"
MODEL_HINT = [
    "config.yaml", "gpt.pth", "s2mel.pth", "bpe.model", "glossary.yaml",
]


def find_comfyui_dir():
    """从当前目录向上探测 ComfyUI 根目录（含 custom_nodes、models 的目录）。"""
    cur = os.path.abspath(os.path.dirname(__file__))
    for _ in range(6):
        if (os.path.isdir(os.path.join(cur, "custom_nodes"))
                and os.path.isdir(os.path.join(cur, "models"))):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def find_python(comfyui_dir):
    """定位 ComfyUI 的 Python 解释器（Windows 嵌入版 or 系统 python）。"""
    if sys.platform == "win32":
        cands = [
            os.path.join(os.path.dirname(comfyui_dir), "python", "python.exe"),
            os.path.join(comfyui_dir, "python", "python.exe"),
            os.path.join(comfyui_dir, "..", "python", "python.exe"),
        ]
        for c in cands:
            if os.path.isfile(c):
                return c
    return sys.executable


def run(cmd):
    print(">>", " ".join(cmd))
    return subprocess.run(cmd, shell=(sys.platform == "win32"))


def main():
    parser = argparse.ArgumentParser(description="IndexTTS2-PauseControl 安装脚本")
    parser.add_argument("--comfyui-dir", default="", help="ComfyUI 根目录（自动探测失败时手动指定）")
    args = parser.parse_args()

    node_dir = os.path.abspath(os.path.dirname(__file__))
    print("节点目录:", node_dir)

    comfyui = args.comfyui_dir.strip() or find_comfyui_dir()
    if not comfyui:
        print("!! 未找到 ComfyUI 根目录，请用 --comfyui-dir 指定（包含 custom_nodes/ 和 models/ 的目录）")
        sys.exit(1)
    print("ComfyUI 目录:", comfyui)

    # 1. 检查节点位置
    expected = os.path.join(comfyui, "custom_nodes", "IndexTTS2-PauseControl")
    if os.path.normpath(node_dir) != os.path.normpath(expected):
        print("!! 节点应位于 %s" % expected)
        print("   当前在 %s" % node_dir)
        print("   请把本仓库目录移动到 custom_nodes/ 下再运行本脚本")
        sys.exit(1)
    print("[OK] 节点位置正确")

    # 2. 安装依赖
    py = find_python(comfyui)
    print("Python:", py)
    print("== 安装依赖 ==")
    for pkg in REQUIRED_TOP:
        run([py, "-m", "pip", "install", pkg])
    print("== 可选依赖（缺省时部分功能不可用）==")
    # descript-audiotools 必须 --no-deps：其依赖约束（protobuf<3.20 等）会降级破坏
    # 用户环境（实测教训：protobuf 5.x→3.19、tensorboard 2.21→2.20）。其真正需要的
    # 小依赖（flatten_dict/julius/argbind/markdown2/randomname/pystoi）单独安装。
    run([py, "-m", "pip", "install", "--no-deps", "descript-audiotools"])
    for pkg in OPTIONAL_TOP:
        if pkg != "descript-audiotools":
            run([py, "-m", "pip", "install", pkg])

    # 3. 检查模型
    model_dir = os.path.join(comfyui, "models", MODEL_DIR_NAME)
    if os.path.isdir(model_dir):
        missing = [f for f in MODEL_HINT if not os.path.isfile(os.path.join(model_dir, f))]
        if missing:
            print("!! 模型目录存在但缺少文件:", ", ".join(missing))
            print("   请补齐模型（见 README / 官方 index-tts 仓库下载指引）")
        else:
            print("[OK] 模型文件齐全")
    else:
        print("!! 未找到模型目录: %s" % model_dir)
        print("   模型权重（约 11.8GB）需从官方渠道下载：")
        print("   - GitHub: https://github.com/index-tts/index-tts")
        print("   - HuggingFace / ModelScope: 搜索 index-tts")
        print("   下载后放入: %s" % model_dir)

    print()
    print("=" * 60)
    print("安装完成！请重启 ComfyUI，然后在工作流中添加 IndexTTSSingle/IndexTTSBatch 节点。")
    print("快速体验：[pause:N] 标记用法见 README.md")


if __name__ == "__main__":
    main()
