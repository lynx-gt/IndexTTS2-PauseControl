# 贡献指南（Contributing）

欢迎贡献！无论是提 issue、修 bug、改进方案还是补充文档。

## 提问 / 报告问题

- 先搜索 [issues](https://github.com/lynx-gt/IndexTTS2-PauseControl/issues) 是否已有相同问题
- 提 issue 时请附上：ComfyUI 版本、Python 版本、完整错误日志、复现步骤
  （含文本与参数）

## 提交 PR

1. Fork 本仓库，从 `main` 开分支
2. 改动前先跑测试：
   ```bash
   python test/smoke_test.py --model-dir <模型目录> --spk-ref <参考音频>
   python test/regression_test.py --model-dir <模型目录> --spk-ref <参考音频>
   ```
   （需要 GPU + 模型权重；无法运行的可说明，至少保证语法通过：
   `python -m compileall -q indextts nodes.py lib test examples install.py`）
3. 保持代码风格与现有文件一致（中文注释、函数文档字符串）
4. 改动后更新相应文档（README / docs/PAUSE_CONTROL.md / CHANGELOG.md）
5. 提交 PR，说明改动内容与测试结果

## 协议提醒

- 本项目原创部分：MIT License
- `indextts/` 推理代码源自 bilibili IndexTTS2，受其「bilibili Model Use
  License Agreement」约束（商用授权、禁止改进其他 AI 模型等）——修改该部分
  代码即产生官方协议的衍生作品，请遵守其条款
- 不要在本仓库引入有版权风险的示例内容（文本/音频/音色）

## 开发注意

- 全波形 pause 方案的原理与参数标定见 `docs/PAUSE_CONTROL.md`——改参数前先读
- 发布前更新 `CHANGELOG.md` 与版本号（pyproject.toml / git tag 同步）
