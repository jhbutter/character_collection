# FontDiffuser 目标书体结构原型输入对照（2026-10-19）

## 问题和结论

检验现代楷书 Content Encoder 输入是否限制大跨度书体转换。固定测试目标、同字库风格参考、模型权重、seed 42 和 20 步采样，只把内容图从现代楷书换成**同字同书体、不同具体字库且不同 SHA 的真实图**。

结果：两套权重的输出都随内容原型明显改变，说明结构输入有强影响；“旁、祭”的目标形体仍未稳定生成。替换结构原型是可行的条件设计方向，但单靠推理时换图不足以解决跨书体构型转换。

## 样本与边界

当前 `test` 清单中，只有金文的 6 个字（八、屮、旁、每、祭、禦）具备同字同书体、不同字库原型。甲骨文、小篆和隶书在这个严格条件下没有可用测试对照。本轮主要报告“旁”和“祭”，其结构原型与目标图分别来自不同实际金文字库，图片 SHA 不同；风格参考仍按既有规则来自 `train` 中目标字库的另一个字头。

**重要限制：结构原型本身是 test 字头的一张真实金文图。** 这属于已知目标书体形体辅助的 oracle 实验，只能检验“给了目标结构会怎样”；不检验从未知古文字字形的楷书图推断历史构型的能力。目标图为来源字库渲染图，也未经过人工确认的逐图映射审核。

## 对照图

每张图六列依次为：现代楷书内容图／同字金文结构原型／训练集风格参考／保留的目标图／现代楷书输入的生成图／金文原型输入的生成图。每组两次生成重置同一 seed，因此初始噪声相同；仅内容图改变。

| 字 | 官方原始权重 | 500 步微调权重 | 观察 |
| --- | --- | --- | --- |
| 旁 → 金文 | [旁_baseline.png](../data/ml/fontdiffuser/prototype_comparison/旁_baseline.png) | [旁_clean_finetuned.png](../data/ml/fontdiffuser/prototype_comparison/旁_clean_finetuned.png) | 现代内容图输出仍近似楷书“旁”；金文原型输入改变了下部笔形和布局，但没有准确匹配目标。 |
| 祭 → 金文 | [祭_baseline.png](../data/ml/fontdiffuser/prototype_comparison/祭_baseline.png) | [祭_finetuned.png](../data/ml/fontdiffuser/prototype_comparison/祭_finetuned.png) | 现代内容图输出近似现代“祭”；原型输入使输出构型明显改变，但与目标仍有较大差异。 |

另外试了“八”和“每”，部分候选原图是黑色实心底块中的反白字，和常见透明底黑字的输入分布不同，不能用它们判断结构原型是否改善效果。原始 PNG 保留作预处理诊断，没有纳入上述结论。核对“旁、祭”原始权重与微调权重的前四列像素完全相同，保证比较用的是同一输入条件。

## 复现

实现位于 `src/hanzi_evolution/ml/fontdiffuser_adapter.py` 的 `compare-prototype`，不会覆盖已有输出；结果 JSON 记录 pair ID、实际字库、SHA、checkpoint 和 oracle 标记。例如：

```bash
data/ml/fontdiffuser/venv/bin/python scripts/finetune_fontdiffuser.py compare-prototype \
  --split test --character 旁 --style jinwen \
  --target-pair-id 638ac45efb92b5b52b601b70 \
  --prototype-pair-id 44922f99a97680b770edb122 \
  --finetuned data/ml/fontdiffuser/run_003/best.pt \
  --output data/ml/fontdiffuser/prototype_comparison/旁_clean_finetuned.png \
  --device cuda:1 --seed 42 --steps 20
```

去掉 `--finetuned` 可跑官方原始权重，使用新输出路径即可。

## 下一步判断

1. 先把黑底反白和透明底黑字统一成同一前景极性，重新构建清单和 checkpoint；旧微调权重仍绑定旧预处理，不能直接声称适用于修正后的输入。
2. 建立更多经审核的跨字库、同字同书体目标图，训练“已知目标结构原型 → 另一具体字库字形”的任务，评估渲染能力。
3. 若目标书体没有任何真实原型，再研究独立的结构候选模型；该情况不能由本轮 oracle 实验推断已解决。

## 同书体原型微调补充实验

为避免“模型从未见过目标书体原型作为内容输入”的偏差，新增 `train --content-mode prototype`。从官方权重重新开始，只使用同字金文跨实际字库配对：`train=105` 对／23 字，`val=25` 对／5 字，`test=28` 对／6 字。每对的内容图是同一 split、同字同书体、不同字库且不同 SHA 的真实图；风格参考仍取训练集里目标字库的其他字头。两个 encoder 冻结，只训练 U-Net；GPU1、batch 2、学习率 `1e-5`、300 步。结果在 `data/ml/fontdiffuser/run_004_prototype/`，最佳为 300 步，峰值预留显存 2.777 GiB。

```bash
data/ml/fontdiffuser/venv/bin/python scripts/finetune_fontdiffuser.py train \
  --content-mode prototype --output data/ml/fontdiffuser/run_004_prototype \
  --device cuda:1 --batch-size 2 --max-steps 300 \
  --eval-every 100 --val-samples 16 --learning-rate 1e-5
```

验证损失按每个字选一个固定配对，因而实际是 5 个 val 字；训练期间第 100／200／300 步分别为 `0.033663`／`0.031907`／`0.029980`。同口径官方原始权重为 `0.040294`，原楷书微调权重 `run_003` 为 `0.032477`。

训练完成后才对 6 个留出 test 字各取一个固定配对评估：官方原始权重 `0.006213`，原楷书微调权重 `run_003` 为 `0.005072`，本轮原型微调权重 `run_004_prototype` 为 `0.005130`。本轮没有优于原楷书微调权重；val/test 数值差异很大，也反映出小样本与图像极性混杂使去噪损失不稳定。

留出字图：[旁](../data/ml/fontdiffuser/prototype_comparison/旁_prototype_trained.png)、[祭](../data/ml/fontdiffuser/prototype_comparison/祭_prototype_trained.png)。原型内容输入仍显著改变形状，但这两例没有稳定匹配目标；训练后“祭”仍明显偏离真实目标。因此本轮**没有证明原型微调能解决构型变化**。继续扩大训练步数的证据不足，下一步应先统一图像极性、审核跨字库配对，并用更多独立字头重做实验。

## 失败原因的补充诊断

收到“生成图并未改善”的反馈后，进行了两个不再训练模型的检查，使用同一 test 金文目标“旁”“祭”、seed 42、20 步采样。

1. **目标图自重建上限诊断。** 直接把真实目标图作为 Content Encoder 输入，同一目标字库的另字图作为风格参考，观察模型能否保留目标。官方原始权重的墨迹二值 IoU 为“旁”0.2271、“祭”0.1967；原型微调 `run_004_prototype` 为“旁”0.1837、“祭”0.1879。图见 [旁：原始](../data/ml/fontdiffuser/self_reconstruction/旁_official.png)、[旁：微调](../data/ml/fontdiffuser/self_reconstruction/旁_prototype_finetuned.png)、[祭：原始](../data/ml/fontdiffuser/self_reconstruction/祭_official.png)、[祭：微调](../data/ml/fontdiffuser/self_reconstruction/祭_prototype_finetuned.png)。每张依次为真实目标／风格参考／生成。IoU 是按灰度阈值128计算的同图重合诊断，不是书体或文字学正确率；这些低值和图像形态都表明模型即使得到目标结构仍不能稳定保留它。
2. **采样与参考图检查。** 在微调权重上把 guidance 从 1、2、3、5 扫到原设定 7.5；“旁”的自重建 IoU 范围 0.1493–0.1837，“祭”为 0.1868–0.2066，未出现稳定修复。当前默认风格参考因清单顺序取到笔画少的“上”；换成目标字库的“帝”“禘”（旁）及“祀”“祝”（祭）后生成形态会改变，但[旁的对照图](../data/ml/fontdiffuser/reference_sweep/旁_clean_ref_帝.png)、[祭的对照图](../data/ml/fontdiffuser/reference_sweep/祭_ref_祝.png)仍未稳定匹配真实目标。

**更新判断：** 已有结果不能支持“原型输入或短程 U-Net 微调改善了生成质量”。问题不仅是楷书到金文的结构距离；当前权重、输入分布、参考选择和少量训练字共同限制了生成。应暂停继续延长该训练配置，先统一黑字白底／反白图、审核配对，并建立严格的同书体自重建基线。任何进一步架构改动都要以该基线和留出字形体评估为门槛。
