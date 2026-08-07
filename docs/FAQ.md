# FAQ（常见问题）

## 安装与运行

**Q：安装后节点不出现？**
重启 ComfyUI；确认仓库目录名为 `IndexTTS2-PauseControl` 且位于
`custom_nodes/` 下；查看 ComfyUI 启动日志有无 import 报错。

**Q：`install.py` 报目录错误？**
仓库必须放在 `ComfyUI/custom_nodes/IndexTTS2-PauseControl/`（目录名不能改），
脚本会向上探测 ComfyUI 根目录并校验。

**Q：模型权重在哪下载？**
权重不属于本仓库（约 11.8GB），从官方 [index-tts/index-tts](https://github.com/index-tts/index-tts)
或其 HuggingFace/ModelScope 页面下载，放入 `ComfyUI/models/index_tts/`。

**Q：提示缺 descript-audiotools？**
它是可选依赖，请用 `install.py` 安装（自动 `--no-deps`，防止其依赖约束降级
你的 protobuf/tensorboard）。不要直接 `pip install descript-audiotools`。

**Q：能 `pip install .` 吗？**
**不能**。本项目以目录方式运行；`pip install .` 会因包名与官方 `indextts`
同名而覆盖官方推理包。

## [pause:N] 使用

**Q：标记不生效？**
检查：① 文本确实包含 `[pause:N]`（如 `[pause:600ms]`）② 节点 `pause_mode`
已开启 ③ 目标位置存在停顿或真静音（模型完全没停且无静音间隙时插入会被
拒绝——改写文本或换 seed 重试）。

**Q：支持的时长范围？**
推荐 150ms ~ 5s。下限约 100ms（检测下限）；上限无硬限制（波形插静音）。

**Q：英文文本能用吗？**
能。标记统一替换为全角中文逗号，模型按标点停顿，实测英文同样精确。

**Q：句号处怎么控制停顿？**
分句按句号切分（句号=分句边界），句号停顿默认 = 分句间静音（`interval_silence`，
默认 400ms，稳定规整）；需要精确覆盖时用标记：
`句子[pause:800ms]。`（句号前）或 `句子。[pause:800ms]`（句号后），两者均精确
（分句尾兜底：分句内未命中自动转分句间控制；最后一个分句在音频末尾追加静音）。
引号场景（`…。'`）同样支持。

**Q：停顿处有换气声？**
模型自然韵律（长停顿后可能吸气），工具不处理呼吸声（能量高于静音阈值）。
介意可对该分句做降噪后处理。

## 精度与稳定性

**Q：实测精度多少？**
验收 20 个片段 40 标记平均偏差 13ms，最大 32ms；回归 5 片段平均 5ms；
6 个片段压力测试（分句内/句号前/句号后/引号/无标记）每片段 3 候选全部命中。

**Q：为什么偶尔某个片段停顿不准？**
① 模型在标记处未产生停顿且无静音间隙时，插入会被保护性拒绝（宁缺毋滥）；
② 长单句（>40 字）多标记时字符比例误差可能超过匹配上限，个别标记未命中。
两者均可换 seed 或从多轮候选中挑选解决。

## 协议

**Q：可以商用吗？**
`indextts/` 部分受 bilibili 协议约束：月活超 1 亿或年收入超 1 亿人民币的组织
必须向官方申请商业许可；官方曾澄清"商业用途应事先向许可方登记"。个人创作
一般不受规模条款约束，但建议查看 `LICENSE.bilibili.txt` 并自行判断。

**Q：能用 IndexTTS2 训练/改进其他模型吗？**
bilibili 协议禁止用 IndexTTS2 或其衍生品改进其他 AI 模型（IndexTTS2 自身、
其衍生品或非商业 AI 模型除外）。
