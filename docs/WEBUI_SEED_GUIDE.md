# WebUI 接入指南：seed 固定（可复现生成）

> 适用：Gradio WebUI（官方 index-tts 仓库的 `webui.py` / `webui_v2.py` 或基于
> 其改的整合包）。打补丁后 `infer_v2.py` 已支持 `seed` 参数；本文说明如何在
> WebUI 界面上加一个 seed 输入框。

## 原理

- 后端（补丁已含）：`IndexTTS2.infer(seed=None)`——传 seed 则固定（同 seed +
  同文本可精确复现）；不传则随机，并把实际 seed 写入 `<输出>.wav.seed` 文件
- 需要做的：在 webui.py 界面加输入框 → 把值传给 `infer(seed=...)`
- 不改界面也能用：不传 seed = 自动随机 + 记录 `.seed` 文件（只是不能在界面固定）

## 步骤

### 1. 定位 webui.py 的生成函数

找 `tts.infer(` 调用所在函数（通常是"生成"按钮的回调，如 `gen_single`）。
以官方 `webui_v2.py` 为例，结构大致是：

```python
async def gen_single(emo_control_method, prompt, text, ...,
                     *args, progress=gr.Progress()):
    do_sample, top_p, top_k, temperature, ... = args   # 高级参数按位置解包
    output = await tts.infer(..., **kwargs)
```

### 2. 界面加 seed 输入框

在高级参数区（`gr.Accordion` 内）加一个控件：

```python
with gr.Row():
    seed_input = gr.Textbox(
        label="seed（留空=随机）",
        value="",
        placeholder="如 42；留空自动随机并记录 .seed 文件",
    )
```

> 用 `gr.Textbox` 而非 `gr.Number`：留空表示随机，填数字表示固定，不用区分
> "0 是否合法"。

### 3. 生成回调签名加 seed 参数

⚠️ **关键**：Gradio 的按钮回调是**纯位置传参**——新参数必须加在回调签名
的对应位置，且**不能放在 `*args` 之后**（会被 `*args` 吞掉，这是最常见的坑）。

```python
async def gen_single(emo_control_method, prompt, text, ...,
                     seed_input,            # ← 新增，必须放在 *args 之前
                     *args, progress=gr.Progress()):
```

### 4. 传给 infer

```python
seed = int(seed_input) if seed_input.strip() else None
output = await tts.infer(..., seed=seed)   # None=随机（记录 .seed 文件）
```

### 5. 按钮的 inputs 列表加 seed_input

```python
gen_button.click(
    gen_single,
    inputs=[emo_control_method, prompt_audio, input_text_single, ...,
            seed_input,        # ← 与签名顺序一致（在 advanced_params 之前）
            *advanced_params],
    outputs=[output_audio],
)
```

## 验证

1. seed 填 `42` 生成一次 → 记下输出路径；再生成一次 → 两次音频 MD5 应一致
2. seed 留空生成 → 输出目录出现 `<输出>.wav.seed` 文件，内容为实际使用的 seed
3. 想复现某次随机结果：读 `.seed` 文件 → 把数字填进 seed 输入框 → 重新生成

## 常见问题

- **回调报参数数量不匹配**：`inputs` 列表的元素顺序/数量与回调签名不一致——
  逐一对照，新增的 `seed_input` 在两边都要有且位置对应
- **seed 填了但每次结果不同**：确认 `torch.manual_seed` 生效（补丁内已处理），
  且推理参数（temperature 等）也一致——同 seed 下参数不同结果不同
- **整合包 webui.py 与官方差异大**：以上是官方结构的示例；只要找到你的
  webui.py 里 `tts.infer(` 的调用处，按同样思路加控件、传参即可，无需照搬代码
