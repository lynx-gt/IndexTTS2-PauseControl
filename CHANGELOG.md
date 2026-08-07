# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式。

## [Unreleased]

## [1.0.0] - 2026-08-07

### Added

- `[pause:N]` 精确停顿控制（全波形方案）：
  - 标记解析（`[pause:600ms]` / `[pause:1.5s]` / `[wait:]` / `[stop:]`）
  - 能量检测（宽松阈值找停顿段 + 严格阈值找静音核心区）
  - Needleman-Wunsch 全局对齐（仿射 gap、不对称定价、`w_dur=0.2`、
    `max_t_diff=0.8s` 时间硬上限）
  - 波形操作（静音核心延长/缩短/插入，按位置从后往前执行防坐标漂移）
- ComfyUI 节点：`IndexTTSSingle` / `IndexTTSBatch` 接入 `pause_mode`
- `IndexTTSListen` 新增 `task_dir` 连线输入与 `accept_round` 验收标记
  （写入任务 manifest.json）
- 批量生成 manifest 断点续跑、分句稿（一句一段）/多行文本两种输入
- 一键安装：`install.py`（跨平台：依赖安装 + 模型检查），支持 ComfyUI-Manager 安装
- 文档：方案说明（docs/PAUSE_CONTROL.md，含核心原理与文献引用）、双语 README、补丁说明（patch/）

### Changed

- `interval_silence` 默认值 200 → 400ms（段间固定停顿）
- 分句稿切分策略改为「一句一段」（句号在段尾，`[pause:N]` 写在句号前）
- 明确 `[pause:N]` 支持时长范围：推荐 150ms ~ 5s（下限≈100ms，上限无硬限制）
- 明确标记统一替换为全角中文逗号（，），中英文场景均精确

### Deprecated

- `detect_cfm_steps`：全波形版无作用，保留兼容旧工作流

### Removed（研究阶段弃用，代码保留供参考）

- token 级静音码注入方案（CORE10）：上下文相关杂音，生产不可靠

### Known limitations

- 长停顿后模型可能自带换气（呼吸声不被检测/处理）
- 停顿插入要求目标位置存在真静音（能量谷保护）
- 字符比例位置映射长句 ±0.4s 误差（NW + 时间硬上限兜底）
