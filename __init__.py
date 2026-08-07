# -*- coding: utf-8 -*-
"""IndexTTS2-PauseControl：IndexTTS2 精确停顿控制 ComfyUI 节点包。

依赖（ComfyUI python 环境）：json5 / munch / descript-audiotools / soundfile /
openai-whisper（停顿对齐用，模型在 models/index_tts/whisper/）。
"""
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from . import api  # noqa: F401  （注册 /indextts/* 动态下拉 API）

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
