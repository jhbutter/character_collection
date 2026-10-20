# FontDiffuser 预训练模型微调 PoC（2026-10-19）

## 结论

已在本机使用作者发布的 FontDiffuser 权重，完成数据适配、GPU 微调、验证、保存 checkpoint、留出字推理与原始权重对照。流程可用；当前生成图还不足以作为可靠的指定历史书体候选。验证去噪损失下降不能替代字头和书体的人工评估。

## 实验边界

- 上游：[FontDiffuser 官方仓库](https://github.com/yeungchenwa/FontDiffuser)，本地版本 `7b28ce9c3b357f4fb23296622f458cf169803539`；[官方权重](https://huggingface.co/spaces/yeungchenwa/FontDiffuser-Gradio/tree/main/ckpt)，加载时核对 SHA-256。
- 本机：GPU1，96×96 RGB，batch 2，学习率 `1e-5`，最多 500 步，20 步 DPM 推理，seed 42。
- 数据：原清单 735 对，按实际字库找训练集里不同字头作为风格参考；21 对缺参考跳过。有效 `train=515`、`val=97`、`test=102`，按字头划分。
- 只微调 U-Net；两个 encoder 冻结并保持 `eval`。按书体逆频率抽样；验证用固定的 16 个 val 示例选 checkpoint。未用 test 训练或选 checkpoint。
- 有效运行：`data/ml/fontdiffuser/run_003/`。先前 `run_001`、`run_002` 是实现验证；当时冻结 encoder 仍处于 `train` 模式，不能用作最终指标。`run_003` 已修正并从官方权重重新训练。

## 验证损失

| 模型 | 固定 16 个 val 示例的损失 |
| --- | ---: |
| 原始官方权重 | 0.009807 |
| 微调 100 步 | 0.007105 |
| 微调 200 步 | 0.006998 |
| 微调 300 步 | 0.006881 |
| 微调 400 步 | 0.006986 |
| 微调 500 步（best） | **0.006691** |

`run_003/best.pt` 与 `latest.pt` 均在 500 步；显存峰值预留约 2.777 GiB。完整配置和逐次记录分别在 `config.json`、`metrics.jsonl`。这里的损失是噪声预测与 offset 项的和，仅反映该小型固定验证集。

## 留出字对照

每张 PNG 从左到右是**楷书输入／另一个训练字头的同字库风格参考／真实目标／生成结果**。原始权重和微调结果使用相同数据、seed 42、20 步推理。

| 字与书体 | 原始权重 | 微调后 | 人工观察 |
| --- | --- | --- | --- |
| 八 → 甲骨文 | [baseline_八_jiaguwen.png](../data/ml/fontdiffuser/baseline_八_jiaguwen.png) | [finetuned_final_八_jiaguwen.png](../data/ml/fontdiffuser/finetuned_final_八_jiaguwen.png) | 生成图笔形略变，但仍是楷书“八”式张开的两笔；真实目标是接近竖向的两笔。 |
| 旁 → 小篆 | [baseline_旁_xiaozhuan.png](../data/ml/fontdiffuser/baseline_旁_xiaozhuan.png) | [finetuned_final_旁_xiaozhuan.png](../data/ml/fontdiffuser/finetuned_final_旁_xiaozhuan.png) | 微调前后都明显保留现代字形，下部结构与目标小篆差异大。 |

两例只展示生成流程与失败形态，不代表完整 102 对 test 集的统计。尚无可靠的字头正确率、书体分类或专家审阅结论。

## 使用方式与限制

命令、目录和预处理见 [微调说明](../docs/fontdiffuser_finetune.md)。当前记录仍为 `unverified/pending`，来源字形许可未逐图核验；作者上游标注非商业研究用途。所有生成图标为候选，不入真实字形库，也不能据此推断古文字的历史演化。

下一步如要提升效果，应先扩大经过核实的独立字头与同字库参考覆盖，再建立盲评的字头保持和书体准确率；当前不宜仅凭去噪损失继续长时间训练。

后续做了固定目标、参考图和 seed 的[目标书体结构原型输入对照](fontdiffuser_prototype_input.md)；原型会明显改变生成构型，但尚未可靠匹配目标。
