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
- 训练：epsilon prediction，batch 16，5 万–10 万步起步
- 采样：DDIM 20–50 步；可做 style classifier-free guidance
- 优点：比 GAN 稳定，适合做多书体条件模型
- 风险：735 对非常小，容易记住训练字；必须看留出汉字的结果

### 3. 预训练 diffusion + ControlNet

- 用 source glyph 作为结构控制，目标书体作为文本/embedding 条件
- 需要更多数据和更强 GPU；当前 86×87 小图不一定比小尺寸 DDPM 更有优势
- 如果后续扩到数千对，再考虑

## 训练环境

当前项目 `.venv` **未安装** `torch`、`torchvision`、`diffusers`、`accelerate`。机器是 Apple M4，可用 MPS，但训练前需要单独确认依赖和耗时。

建议先安装最小集合：

```bash
pip install torch torchvision diffusers accelerate
```

训练代码建议单独放在 `src/hanzi_evolution/ml/train_style_diffusion.py`，不要混入采集包。

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

## 下一步

1. 用 `scripts/build_style_pairs.py` 固定数据清单和 split
2. 实现检索基线，记录留出字的最近邻结果
3. 安装 PyTorch/diffusers，训练 64×64 四书体条件 DDPM
4. 先看 8 个 test 字的生成结果，再决定是否扩数据或换预训练模型
