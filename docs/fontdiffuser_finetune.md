# FontDiffuser 预训练权重微调实验

本实验将现代楷书参考图作为 `content`，将训练集里另一字头、同一具体字库的图作为 `style reference`，生成指定书体的候选字形。输出仅用于研究对照，不是历史字形证据。

## 本地结构

- `thirdparty/fontdiffuser/`：作者的 [FontDiffuser 仓库](https://github.com/yeungchenwa/FontDiffuser)，固定在 `7b28ce9c3b357f4fb23296622f458cf169803539`，保留独立 Git 历史；未修改上游文件。
- `data/ml/fontdiffuser/upstream/ckpt/`：作者发布的 [预训练权重](https://huggingface.co/spaces/yeungchenwa/FontDiffuser-Gradio/tree/main/ckpt)。适配器在加载时检查三个文件的 SHA-256。
- `data/ml/fontdiffuser/venv/`：隔离的 Python 3.10 环境；不改变主项目 `.venv`。
- `src/hanzi_evolution/ml/fontdiffuser_adapter.py`：数据适配、微调、生成；`scripts/finetune_fontdiffuser.py` 为入口。
- `data/ml/fontdiffuser/run_003/`：本轮有效实验的配置、指标和 U-Net checkpoint。

上述第三方代码、权重、环境、运行结果都由 `.gitignore` 排除。上游 README 标注非商业研究用途；公开分发或商用前需重新核对其授权。当前来源字形的逐图许可也尚未核实。

## 环境与数据

本机实验环境：`torch==1.13.1+cu117`、`torchvision==0.14.1+cu117`、`numpy==1.26.4`、`Pillow==10.4.0`、`diffusers==0.22.0`、`transformers==4.33.1`、`accelerate==0.23.0`、`huggingface-hub==0.21.4`、`kornia==0.7.0`、`info-nce-pytorch` 和 `PyYAML`。安装 PyTorch CUDA 轮子需使用 PyTorch cu117 索引。训练入口本身不联网。

输入是 `data/ml/style_pairs/manifest.jsonl` 的 735 对。按 `target_url` 里的实际 `font` 参数匹配风格参考；参考图必须来自 `train`、同一字库、不同字头。21 对没有合格参考而跳过，剩余 `train=515`、`val=97`、`test=102`。所有 split 按字头隔离。图像按 alpha 包围盒裁剪，保比例居中到 96×96、白底 RGB、数值范围 `[-1,1]`。这一步会放大原始约 86×87 像素的图，不能增加真实细节。

当前只训练官方 U-Net；content/style encoder 冻结并保持 `eval` 模式。使用噪声 MSE 加作者模型的 offset loss，按目标书体逆频率抽样。验证采用固定 seed、固定的 16 个不同字头/书体样本；checkpoint 保存清单 SHA-256，避免错配。

## 运行

在本机已备好仓库、权重和隔离环境后：

```bash
data/ml/fontdiffuser/venv/bin/python scripts/finetune_fontdiffuser.py train \
  --output data/ml/fontdiffuser/run_003 --device cuda:1 \
  --batch-size 2 --max-steps 500 --eval-every 100 \
  --val-samples 16 --learning-rate 1e-5
```

生成留出字的四列对照图（源楷书／风格参考／真实目标／生成）：

```bash
data/ml/fontdiffuser/venv/bin/python scripts/finetune_fontdiffuser.py sample \
  --split test --character 八 --style jiaguwen \
  --finetuned data/ml/fontdiffuser/run_003/best.pt \
  --output data/ml/fontdiffuser/finetuned_final_八_jiaguwen.png \
  --device cuda:1 --seed 42 --steps 20
```

去掉 `--finetuned` 即使用官方原始权重，方便相同 seed 对比。已有训练目录或生成图不会被覆盖。

## 结果解释

同口径原始权重验证损失为 `0.009807`。微调是否改善见 [实验报告](../reports/fontdiffuser_finetune_poc.md)。该损失是去噪目标，不等于字头正确率；必须看留出字的形体与书体。生成图不可导入史料数据库，所有现有真实样本仍为 `unverified/pending`。

## 结构原型输入对照

`compare-prototype` 在同一测试字头、同一目标书体下找不同具体字库的真实结构原型，固定 seed 对比“楷书输入”和“目标书体原型输入”。这使用了测试字头的真实目标书体信息，是 oracle 辅助对照，不衡量未知古文字形体的推断。命令、样本与结果见 [结构原型对照报告](../reports/fontdiffuser_prototype_input.md)。

同书体原型微调可用 `train --content-mode prototype`；它只选同一 split 的同字、同书体、不同字库且不同 SHA 的配对。当前仅金文满足条件，有效 train105/val25/test28。300 步试验的留出字没有显示稳定改善，见 [补充结果](../reports/fontdiffuser_prototype_input.md#同书体原型微调补充实验)。
