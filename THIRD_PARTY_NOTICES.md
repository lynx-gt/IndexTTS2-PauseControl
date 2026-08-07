# Third-Party Notices

## bilibili IndexTTS2（模型与推理代码）

本仓库 `indextts/` 目录下的推理代码（含本项目对其的兼容性修改与功能扩展）
源自 [index-tts/index-tts](https://github.com/index-tts/index-tts)（bilibili IndexTTS2），
受其「bilibili Model Use License Agreement」约束。协议要点：

- **授权范围**：全球、非独占、不可转让、免版税；月活跃用户 >1 亿 或 年收入 >10 亿 RMB
  的组织使用须向 bilibili 另行申请书面授权。
- **禁止事项**：不得用 IndexTTS2 或其衍生作品改进其他 AI 模型（IndexTTS2 自身、
  其衍生作品或非商业 AI 模型除外）；不得用于高危场景（医疗诊断、自动驾驶、军事等）。
- **分发义务**：分发衍生作品必须附带本协议副本、保留原始版权声明，并在分发页面声明：
  "对本衍生作品中原始模型所做的任何修改均未经原始权利人的认可、担保或保证，
  原始权利人对本衍生作品相关的一切责任概不负责。"
- **管辖与语言**：适用中华人民共和国法律；中英文版本冲突时以中文版为准。

完整协议文本见 `LICENSE.bilibili.txt`（与官方仓库一致）。

## 其他依赖

- [BigVGAN](https://github.com/NVIDIA/bigvgan)：NVIDIA 开源，MIT License
- [MaskGCT](https://github.com/amphion-ai/amphion)：Amphion 开源，MIT License
- 其余 Python 依赖见 `requirements.txt`，各自遵循其原许可证

## 本项目原创部分

ComfyUI 节点（`nodes.py`、`lib/`、`api.py`、`js/`）与精确停顿控制方案
（`indextts/utils/pause_control.py` 的全波形实现部分、本文档）为本项目原创，
遵循 MIT License（见 `LICENSE`）。
