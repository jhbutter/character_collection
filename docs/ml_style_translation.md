# 楷书到早期书体的风格转换（PoC）

## 任务定义

输入一张**现代楷书参考**，输出指定早期书体的字形：

```text
kaishu_reference  →  jiaguwen / jinwen / xiaozhuan / lishu
```

这不是历史年代推演。输入和输出都是来源字库渲染图，不是拓片、青铜器照片或简牍原物；模型学到的是**书体/字体风格映射**，不能声称还原真实历史演化。

## 当前配对数据

清单由 `scripts/build_style_pairs.py` 从数据库构建，输出：

```text
data/ml/style_pairs/
├── manifest.jsonl
└── stats.json
```

当前四种核心书体：

| 目标书体 | 有配对汉字数 | 配对数 |
|---|---:|---:|
| 甲骨文 `jiaguwen` | 50 | 313 |
| 金文 `jinwen` | 41 | 186 |
| 隶书 `lishu` | 41 | 182 |
| 小篆 `xiaozhuan` | 50 | 54 |
| **合计** | **50** | **735** |

- 源图：50 张 `kaishu_reference`
- 唯一目标图：735 张（同字同书体同 SHA 已去重）
- 37 个字四种书体都有
- 按汉字划分：train 35 字 / val 7 字 / test 8 字
- 同一个字的所有配对只出现在一个 split，避免同字泄漏

字段包括：`pair_id`、`character`、`split`、`source_style`、`target_style`、`source_image`、`target_image`、两个 SHA-256、来源/记录 ID 和 URL。图片路径相对 `data/`。

## 预处理建议

1. 读取 RGBA，取 alpha 非零包围盒，裁剪并居中
2. 转灰度；统一为黑字白底或白字黑底
3. resize 到 64×64 或 96×96，保持长宽比后 padding
4. 去重：按 `target_sha256` 和 `pair_id`
5. 轻量增强：±3° 旋转、1–2 px 平移、轻微膨胀/腐蚀；不要做会改变字形的强形变
6. 训练/验证/测试严格按 `split` 字段，不按图片随机划分

## 模型路线

### 0. 检索基线

对同一字直接取训练集中最近的对应书体图片，或用字形 embedding 检索近似字。用于回答“生成模型是否真的优于直接找图”。

### 1. 条件 GAN / pix2pix

- 输入：楷书图 1 通道 + 目标书体 embedding
- 输出：目标书体图 1 通道
- 64×64，U-Net generator + PatchGAN discriminator
- 优点：735 对可以训练，速度快，适合先验证数据管线
- 缺点：笔画细节可能糊，模式覆盖有限

### 2. 条件 diffusion（推荐先做小尺寸）

- 64×64 或 96×96 灰度
- U-Net 输入：noisy target 1 通道 + source glyph 1 通道（concat）
- 条件：目标书体 embedding + timestep embedding
- 训练：epsilon prediction，batch 16，以 1 万步为上限先验证，必要时延长至 3 万步
- 采样：DDIM 20–50 步；可做 style classifier-free guidance
- 优点：比 GAN 稳定，适合做多书体条件模型
- 风险：735 对非常小，容易记住训练字；必须看留出汉字的结果

### 3. 预训练 diffusion + ControlNet

- 用 source glyph 作为结构控制，目标书体作为文本/embedding 条件
- 需要更多数据和更强 GPU；当前 86×87 小图不一定比小尺寸 DDPM 更有优势
- 如果后续扩到数千对，再考虑

## 64×64 条件 DDPM 实现

实现位于 `src/hanzi_evolution/ml/style_ddpm.py`，兼容入口为 `scripts/style_ddpm.py`。仅在安装 `[ml]` 可选依赖时需要 PyTorch、Diffusers 和 NumPy；采集、数据库和目录导出不依赖训练包。

```bash
.venv/bin/python -m pip install -e '.[ml]'
.venv/bin/python scripts/style_ddpm.py train \
  --manifest data/ml/style_pairs/manifest.jsonl \
  --data-root data --output data/ml/style_ddpm/run_001 \
  --batch-size 16 --max-steps 10000 --eval-every 500 --device cuda:0
```

训练图像来自清单指定的 `data/images/original/`，按 alpha 非零包围盒裁切，黑字白底等比缩放并居中至 64×64；版本为 `alpha-bbox-white-v1`。目标图加噪，与未加噪楷书源图拼成 2 通道输入。U-Net 用目标书体 class embedding 与时间步条件预测 1 通道噪声。默认四个书体，`channels=64 128 192 256`（约 22.1M 参数）；训练时只用 `train`，每次评估只用 `val`，`test` 留作最终检验。

输出目录保存 `config.json`、`metrics.jsonl`、可续训的 `latest.pt`、验证损失最低的 `best.pt`，以及 `previews/` 中按固定验证字头保存的“源图／生成图／目标图”对照图。配置包含清单 SHA-256；数据或模型配置变化时应换新的输出目录。默认 10k 步是上限，需观察验证损失和固定生成样本，不能仅凭训练损失延长至 30k 步。当前 536 对训练配对、batch 16 时，10k 步约重复 299 遍。

生成候选图示例（`source` 换成现有楷书 PNG 路径）：

```bash
.venv/bin/python scripts/style_ddpm.py sample \
  --checkpoint data/ml/style_ddpm/run_001/best.pt \
  --source data/images/original/<楷书图SHA>.png \
  --style jiaguwen --count 4 --steps 50 \
  --output data/ml/style_ddpm/candidates_001 --device cuda:0
```

输出是 64×64 PNG 和 `metadata.json`；已有目录不会被覆盖。输出标记为候选生成图，不入字形史料数据库。

对完整留出测试集生成逐字对照图：

```bash
.venv/bin/python scripts/style_ddpm.py evaluate \
  --checkpoint data/ml/style_ddpm/run_001/best.pt \
  --split test --manifest data/ml/style_pairs/manifest.jsonl \
  --data-root data --output data/ml/style_ddpm/test_001
```

每个测试字得到一张三列对照图：楷书源图／生成图／实际目标图；行按书体排列。`evaluate` 校验清单哈希与 checkpoint 一致，不使用 test 进行训练或选 checkpoint。对照图是人工评估材料，不自动证明生成图正确。

## 评估

必须按**留出汉字**评估：

- 字头保持：生成图是否还能被识别为同一个字
- 书体准确：目标书体分类器/人工判断
- 结构相似：SSIM、IoU、骨架距离
- 人工抽查：笔画连接、部件位置、是否有伪影
- FID 只作辅助：735 张图上的 FID 不稳定，不能单独作为结论

## 数据限制

- 735 对不是 735 个独立字；同一个字有多个目标图变体
- 甲骨文 313 对占主导，小篆只有 54 对，类别不平衡
- 图像只有约 86–87 像素，细节有限
- 全部记录仍 `unverified/pending`，逐图许可为空
- 目标图是字库渲染图，不是历史原物；模型输出不能当史料

## 当前结果与下一步

首轮本地实验在 3500 步得到最低验证损失，但 8 个留出测试字的生成图未可靠保持字头。完整配置、温度和对照图位置见 [实验报告](../reports/style_ddpm_poc.md)。

下一轮应先增加经过核实的独立字头，并建立字头保持的评估；再检查模型对楷书源图的敏感性，决定是否引入更强的结构条件。不能只靠延长训练或降低去噪损失来宣称历史字形生成成功。

## 预训练 FontDiffuser 路线

已完成独立环境下的官方权重微调试验。模型接收楷书内容图和同一具体字库的其他字头风格参考图；适配、运行命令和限制见 [FontDiffuser 微调说明](fontdiffuser_finetune.md)。
