# 代码说明（术语对照与数据流）

本文档把 README / 方案文档中的术语映射到代码符号，帮助阅读与维护源码。
方案设计见 [PAUSE_CONTROL.md](PAUSE_CONTROL.md)。

## 术语 ↔ 代码对照

| 文档术语 | 代码符号 | 位置 | 说明 |
|---------|---------|------|------|
| 分句（segment） | `segments`、`seg_idx` | `infer_v2.py` | `split_sentences` 输出的标点句（句号=分句边界） |
| 片段（分句稿条目） | `seg_id`（manifest） | `nodes.py` / `lib/` | 分句稿 `# 片段 N` 条目 = 批量生成单位，一条 wav |
| 分句内标记 | `seg_marks[seg_idx]` | `infer_v2.py` | 该分句要处理的标记，元素 4 元组 `(分句内偏移, 分句字符数, ms, side)` |
| 分句间标记 | `seg_breaks` | `infer_v2.py` | `{间隙索引: ms}`，键=分句 i 与 i+1 之间；拼接时覆盖 `interval_silence` |
| 分句尾候选 | `tail_cands` | `infer_v2.py` | `{分句索引: (ms, 标记下标)}`；命中→分句间跳过，未命中→分句间补时长，最后分句→末尾追加 |
| 标记位置 | `char_pos`、`marks_pos` | `pause_control.py` / `infer_v2.py` | clean 文本字符坐标（标记替换为逗号后的文本） |
| 停顿区间 | `pauses`、`pause_segs` | `pause_control.py` / `infer_v2.py` | `detect_pauses` 输出的波形静音段 |
| 静音核心 | `detect_pauses` 返回 4 元组 | `pause_control.py` | `(起点s, 时长ms, 核心起点s, 核心时长ms)`——只操作核心，不碰弱尾音 |
| 标记解析 | `parse_pause_marks` | `pause_control.py` | 返回 `(clean_text, marks)`；marks 元素 `(clean 位置, ms, side)`，side ∈ before/after/none |
| 对齐 | `nw_align` | `pause_control.py` | 返回 `(assign, inserted, skipped, conf)`；`max_t_diff=0.8s` 时间硬上限 |
| 波形操作 | `wav_extend_pause` / `wav_shrink_pause` | `pause_control.py` | 静音核心延长/缩短（margin 防切字） |
| 分句间静音 | `interval_silence` | `infer_v2.py` | 官方参数名（默认 400ms） |
| 分句不合并 | `merge_sentences=False` | `front.py` | `split_sentences_by_token` 开关：短句不合并，句号=分句边界 |
| token 字符长度 | `_clean_len` | `infer_v2.py` | token 在 clean 文本中占的字符数（▁ 词首标记不计入） |

## 数据流

```
文本
 → parse_pause_marks（标记→逗号，产出 marks：clean 坐标）
 → tokenizer.split_sentences(merge_sentences=False)（按标点句切分，不合并）
 → _distribute_pause_marks（标记分类：分句内 / 分句间 seg_breaks / 分句尾 tail_cands）
 → 逐分句生成：
    标记转逗号 → 模型生成 → detect_pauses（能量检测+静音核心）
    → nw_align（标记↔停顿对齐）→ 波形操作（分句内，按位置倒序）
    → tail_cands 联动：命中→seg_breaks[i]=0（分句间跳过）
                    未命中→seg_breaks[i]=ms（分句间补）或末尾追加（最后分句）
 → insert_interval_silence（分句间静音 = seg_breaks 覆盖 or interval_silence）
 → 输出 wav（soundfile，22050Hz mono 16bit）
```

## 关键文件

| 文件 | 职责 |
|------|------|
| `indextts/utils/pause_control.py` | 标记解析 / 停顿检测 / NW 对齐 / 波形操作——纯函数，可脱离 GPU 单测 |
| `indextts/infer_v2.py` | 推理主流程：分句、标记分配、生成循环、拼接（`IndexTTS2.infer()`） |
| `indextts/utils/front.py` | tokenizer 分句（`merge_sentences` 开关：句号=分句边界） |
| `nodes.py` | ComfyUI 节点：`IndexTTSSingle` / `IndexTTSBatch` / `IndexTTSListen`（试听+验收） / `IndexTTSFix` / `IndexTTSSrt` |
| `lib/` | manifest 读写、分句稿解析、旧 whisper 后处理（`pause_mode=False` 兼容路径） |
| `test/unit_test.py` | 核心函数单元测试（无需 GPU/模型，CI 自动跑） |

## 标记分配规则（`_distribute_pause_marks`）

按 `char_pos`（clean 字符坐标）定位分句（`seg_ranges` 同为 clean 坐标）：

- **句中**（side=none，非分句尾）：进 `seg_marks`，分句内处理
- **句号后**（side=after 且分句内偏移==0）：进 `seg_breaks`（分句间），分句内不处理
- **分句尾**（分句内偏移 ≥ 分句长-3 且标记后到分句尾全是标点——句号/句号+引号）：
  进 `seg_marks`（照常尝试）同时登记 `tail_cands`，命中判定在生成循环里做
- 越界（标记贴近文本末）：挂最后一个分句末位

> 引号场景：`…。'` 分句尾（句号+引号）同样登记分句尾候选；段尾标点检查
> 排除 `X[pause:N]Y。`（标记后还有内容字）的误判。
