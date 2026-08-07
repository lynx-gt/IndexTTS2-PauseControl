# IndexTTS2-PauseControl


IndexTTS2 精确停顿控制（`[pause:N]`）ComfyUI 节点包。

> **English**: [README_EN.md](README_EN.md)

在 IndexTTS2 的基础上实现**毫秒级精确停顿控制**：在文本任意位置写 `[pause:600ms]`，
生成音频中的对应停顿会被精确调整为 600ms（实测 20 个片段 40 个标记平均偏差 13ms，最大 32ms）。
无需 whisper、无需重解码——纯波形域操作。

## 功能

> **术语**：**分句**（segment）= 推理时按标点切出的标点句（官方 `split_sentences`
> 输出，代码变量 `segments`）；**片段** = 分句稿中的 `# 片段 N` 条目（批量生成
> 单位，一条 wav；一个片段可能含多个分句，片段内多句之间 = 分句间静音）。

- **`[pause:N]` 精确停顿**：文本任意标点处延长、缩短、插入停顿，**句中与句号前后统一支持**：
  - 句中标记（逗号/顿号处）：分句内波形域精确调整（±20ms）
  - 句号前标记（`…[pause:N]。`）：分句尾停顿——分句内命中则精确调整，未命中自动转分句间控制
  - 句号后标记（`…。[pause:N]`）：分句首停顿——直接由分句间静音控制
  - 分句尾兜底：分句内未命中时自动改由分句间静音实现目标时长；**最后一个分句**在音频末尾追加静音
- **句号=分句边界**：分句按标点句切分（不合并短句），句号处停顿 = 分句间静音
  ——无标记时由 `interval_silence` 统一控制（默认 400ms，稳定规整），有标记时精确覆盖
- **引号场景支持**：`句号+引号`（`…。'`）分句尾同样受控（分句间兜底，无需避让）
- **句内不切分**：逗号/顿号处标记在分句内波形操作，不重生成、不切句——避免句内语气/韵律异常
- **全波形方案**：标记转逗号让模型自然生成 → 能量检测定位停顿 → NW 全局对齐 → 静音核心波形操作（免重解码）
- **批量生成 + 候选试听 + 验收标记**：manifest 断点续跑、rounds 轮次候选、试听节点一键标记"第 N 轮通过验收"
- **分句稿支持**：Markdown 分句稿（一句一个片段）或多行文本批量生成

## 安装

### 方式一：完整包（开箱即用，推荐）

1. 将本仓库目录（即 `IndexTTS2-PauseControl/`）放到 ComfyUI 的 `custom_nodes/` 下，
   目录名保持 `IndexTTS2-PauseControl`
   （⚠️ 如已存在同名目录请先备份——覆盖会替换旧内容）
2. 安装依赖到 ComfyUI 的 Python 环境（见 `requirements.txt`）
3. 运行 `python install.py`（自动装依赖 + 检查模型目录），或手动按 `requirements.txt` 安装
4. 下载 IndexTTS2 模型权重到 `ComfyUI/models/index_tts/`
   （模型来源见官方 [index-tts/index-tts](https://github.com/index-tts/index-tts)，权重不属于本仓库）
5. 重启 ComfyUI

> 也支持 **ComfyUI-Manager** 一键安装（搜索 `IndexTTS2-PauseControl`）。
>
> ⚠️ 请以**目录方式运行**（放 `custom_nodes/` 下），**不要 `pip install .`**——本项目
> 包名与官方 `indextts` 同名，pip 安装会覆盖官方推理包。

### 方式二：打补丁（已有官方 indextts 包的用户）

如果你已有官方 IndexTTS2 推理代码（如官方整合包/官方 ComfyUI 节点），
只需应用本仓库 `patch/` 目录下的修改：

1. 将 `patch/modified/` 中列出的文件**覆盖**到你的 indextts 包对应位置
2. 将 `patch/新增文件/` 中列出的文件复制到对应目录
3. 在调用 `IndexTTS2.infer(...)` 时传入 `pause_mode=True` 即可（见 `patch/修改说明.md`）

> 使用说明：补丁形态基于「完整文件覆盖 + 修改说明」，而非 git diff——因为官方代码
> 版本会漂移，diff 可能打不上；覆盖文件更可靠。

## 快速开始

### [pause:N] 语法

```
他停下脚步[pause:800ms]深吸一口气[pause:200ms]然后推开了那扇门。
他停下来[pause:1.5s]深吸一口气。
```

支持格式：`[pause:600ms]` / `[pause:600]` / `[pause:1.5s]` / `[pause:0.8s]`
（也兼容 `[wait:]`、`[stop:]` 前缀）。标记会被替换为**全角中文逗号（，）**送入模型生成。

**句号前后**（分句边界停顿，最稳定）：

```
他深吸一口气[pause:800ms]。然后推开了门。    ← 句号前（分句尾）：分句内调整，未命中自动转分句间
他深吸一口气。[pause:800ms]然后推开了门。    ← 句号后（分句首）：直接由分句间静音控制
```

句号处停顿 = 分句间静音：无标记时 = `interval_silence`（默认 400ms），有标记时 = 标记时长。
**引号场景**（`…。'`）同样支持，无需避让。

**时长范围**：推荐 **150ms ~ 5s**。下限约 100ms（能量检测最小停顿；<150ms 时测量含
弱尾音偏差略大）；上限无硬限制（波形插静音，1s/2s/5s 均可，>5s 实用意义小）。

**中英文均可**：标记统一替换为中文逗号，英文句子实测同样精确（800ms 目标 → 实测
778ms；模型把逗号当停顿标点正常处理，无需区分语言）。

### ComfyUI 工作流

```
IndexTTSLoader → IndexTTSSingle(pause_mode=开) → PreviewAudio
IndexTTSLoader → IndexTTSBatch(pause_mode=开) → IndexTTSListen(试听/验收) → PreviewAudio×3
```

示例工作流见 `workflows/`（导入后需把 `spk_ref` 改为你的音色参考路径）。

### 效果对比（双语）

`examples/audio/` 提供 4 条对比音频（同 seed、同音色，唯一差异是 `[pause:]` 标记）：

| 文件 | 内容 | 实测停顿 |
|------|------|---------|
| `zh_plain.wav` | 他停下脚步，深吸一口气，然后推开了那扇门。 | 469/499/359ms（自然节奏，不规律） |
| `zh_pause.wav` | 他停下脚步[pause:800ms]深吸一口气[pause:200ms]… | **798ms / 190ms（精确命中）** |
| `en_plain.wav` | He stopped and took a deep breath. | 80/309ms（自然） |
| `en_pause.wav` | He stopped[pause:800ms]and took a deep breath. | **798ms（精确命中）** |

对比参考音频来自第三方收集音色（非本项目作者声音）。也可用
`examples/make_compare_demo.py` 配合你自己的参考音频重新生成：
`python examples/make_compare_demo.py --model-dir <模型路径> --spk-ref <参考音频>`。

**波形对比**（点击波形图下载音频试听）：

| 中文 | 英文 |
|------|------|
| [![zh_plain 波形](examples/audio/zh_plain.png)](examples/audio/zh_plain.wav)<br>zh_plain（无 pause） | [![en_plain 波形](examples/audio/en_plain.png)](examples/audio/en_plain.wav)<br>en_plain（无 pause） |
| [![zh_pause 波形](examples/audio/zh_pause.png)](examples/audio/zh_pause.wav)<br>zh_pause（有 pause） | [![en_pause 波形](examples/audio/en_pause.png)](examples/audio/en_pause.wav)<br>en_pause（有 pause） |

### 节点参数

| 节点 | 参数 | 说明 |
|------|------|------|
| IndexTTSSingle | `pause_mode` | 开启 `[pause:N]` 精确停顿控制 |
| IndexTTSSingle | `detect_cfm_steps` | **已弃用**（全波形版无作用），保留兼容旧工作流 |
| IndexTTSBatch | `pause_mode` | 批量开启；开启后自动跳过旧 whisper 后处理 |
| IndexTTSBatch | `rounds` | 每片段生成轮次（候选数） |
| IndexTTSBatch | `interval_silence` | 分句间插入静音 ms（句号切分后，句号处停顿 = 该值，默认 400） |
| IndexTTSListen | `task_dir` | 接收批量节点的 task_dir 输出（连线优先） |
| IndexTTSListen | `accept_round` | 验收标记：0=仅试听；1/2/3=标记第 N 轮通过（写入 manifest.json） |

### 分句稿格式（Markdown）

`segments_md` 接受分句稿 Markdown 文件（`IndexTTSBatch` 节点的 `segments_md` 填路径），格式：

```markdown
---
story: 我的故事
voice_ref: references/我的音色/main.wav
emotion_base: references/译制片语气
emotions: [平静, 紧张]
speaking_speed: 1.0
max_text_tokens_per_segment: 120
---

# 片段 001 [叙述 / 平静]
<!-- 标题: 标准同样严苛 -->
标准同样严苛[pause:800ms]不多一分。

<!-- 处理后: 标准同样严苛[pause:800ms]不多一分。 -->
```

- **YAML 头**（可选元信息）：story / voice_ref / emotion_base / emotions / speaking_speed / max_text_tokens_per_segment
- **片段标题**：`# 片段 N [角色 / 情绪]`——N 为片段序号，`[角色 / 情绪]` 用于情感参考选择（"目录随机"策略按情绪子目录挑选）
- **正文**：即生成文本，`[pause:N]` 标记原样保留；若提供 `<!-- 处理后: ... -->`，
  以其内容为准（正文可作展示稿，处理后内容送生成）
- **建议一句一个片段**（句号停顿由分句间静音统一控制）
- 不填分句稿时，可直接在 `text` 输入框按行写文本（每行 = 一个片段）

### 建议的文本组织方式

- 分句稿按**一句一个片段**切分；句号处停顿由分句间静音统一控制（`interval_silence`）
- 需要精确控制句号停顿的位置，直接写标记：
  - `句子[pause:800ms]。`（句号前）或 `句子。[pause:800ms]`（句号后）——两种写法均精确
- 句内停顿（逗号/顿号）直接用 `[pause:N]`，分句内精确调整
- 多标记长句（>40 字）若个别标记因模型停顿分布波动未命中，可换 seed 或从
  多轮候选中挑选（rounds=3 时通常有全命中的候选）

## 工作原理（简述）

1. **分句**：按标点句切分（句号=分句边界，短句不合并；句内不切，保持语气连贯）
2. **标记分类**：句中标记 → 分句内处理；句号前（分句尾）/句号后（分句首）标记 → 分句边界处理
3. **分句内处理**：标记转逗号 → 模型生成 → 能量检测定位停顿（物理信号，10ms 帧）→
   Needleman-Wunsch 全局对齐（容忍多停/漏停）→ 静音核心延长/缩短/插入（免重解码）
4. **分句边界处理**：分句尾标记命中则分句间跳过（防叠加），未命中则分句间补目标时长；
   最后一个分句未命中时在音频末尾追加静音
5. **拼接**：分句间静音 = `interval_silence`（默认 400ms），被标记覆盖的间隙用标记时长

详细方案、参数标定与精度数据见 [docs/PAUSE_CONTROL.md](docs/PAUSE_CONTROL.md)。

## 已知限制

- **长单句多标记**：预期位置按字符比例估算，长句（>40 字）误差可能超过匹配上限
  （0.8s），个别标记可能未命中——换 seed 或从多轮候选中挑选即可覆盖
- **分句尾模型无停顿**：分句内未命中时自动转分句间/末尾追加（目标时长仍达成），但停顿
  位置落在句号处而非标记字后——听感正确，位置略偏
- 长停顿后模型可能自带换气（呼吸声），换气能量高于静音阈值，不会被检测/处理——
  属模型自然韵律，如需去除请用后处理降噪
- 停顿插入要求目标位置存在真静音（能量谷保护），语音连续处插入会被拒绝（宁缺毋滥）
- 短停顿（<250ms）的测量口径含弱尾音，实测偏差略大（±30ms 内）

## 致谢

- **[bilibili IndexTTS2 团队](https://github.com/index-tts/index-tts)**：模型与推理代码
  （本项目的 `indextts/` 基于其开源实现修改）
- **[ComfyUI](https://github.com/comfyanonymous/ComfyUI)**：节点框架
- **[NVIDIA BigVGAN](https://github.com/NVIDIA/bigvgan)**、**[Amphion MaskGCT](https://github.com/amphion-ai/amphion)**：推理组件
- 序列比对算法：Needleman & Wunsch (1970)、Gotoh (1982)（详见 [docs/PAUSE_CONTROL.md](docs/PAUSE_CONTROL.md) §8）
- 示例对比音频的参考音色来自第三方收集音色

> 致谢不代表上述团队对本项目的认可或背书；对原模型的修改与官方无关（见 `THIRD_PARTY_NOTICES.md`）。

## 测试

`test/` 提供三层测试：

```bash
python test/unit_test.py    # 核心函数单元测试（无需 GPU/模型，CI 自动跑，30+ 断言）
python test/smoke_test.py --model-dir <模型目录> --spk-ref <参考音频>   # 中英双语冒烟
python test/regression_test.py --model-dir <模型目录> --spk-ref <参考音频>  # 5 片段回归
```

`unit_test.py` 覆盖标记解析/停顿检测/NW 对齐/波形操作（含边界：空音频、短静音、
无停顿、坐标回归），无需模型即可验证核心逻辑；冒烟/回归需要 GPU + 模型权重
（固定 seed 可复现）。发布版实测：冒烟中英 PASS；回归 5 片段平均偏差 5ms。

## License

- 本项目原创部分（ComfyUI 节点、pause 方案、文档）：MIT License（见 `LICENSE`）
- `indextts/` 推理代码：源自 bilibili IndexTTS2，受 **bilibili Model Use License
  Agreement** 约束（商用需官方授权等），完整条款见 `LICENSE.bilibili.txt` 与
  `THIRD_PARTY_NOTICES.md`
