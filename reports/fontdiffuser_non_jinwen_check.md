# 非金文书体的 FontDiffuser 留出字检查（2026-10-19）

用户要求暂时排除金文。本检查仅使用甲骨文、隶书、小篆，比较官方权重与此前楷书输入微调 `run_003`；没有新训练。

| 书体 | test 配对／字头 | 官方权重固定字头去噪损失 | `run_003` |
| --- | ---: | ---: | ---: |
| 甲骨文 | 35／8 | 0.006703 | 0.005629 |
| 隶书 | 29／7 | 0.008087 | 0.006879 |
| 小篆 | 8／8 | 0.007102 | 0.005725 |

每个 test 字头取清单中的第一个配对，固定 seed 42 评估。损失仅代表噪声预测及 offset，不是字形正确率；三类损失均下降不构成视觉质量改善的证据。先前[甲骨文“八”](../data/ml/fontdiffuser/finetuned_final_八_jiaguwen.png)、[小篆“旁”](../data/ml/fontdiffuser/finetuned_final_旁_xiaozhuan.png)均未可靠匹配真实目标。新增隶书对照：[八：官方](../data/ml/fontdiffuser/non_jinwen/八_lishu_baseline.png)／[微调](../data/ml/fontdiffuser/non_jinwen/八_lishu_finetuned.png)，[旁：官方](../data/ml/fontdiffuser/non_jinwen/旁_lishu_baseline.png)／[微调](../data/ml/fontdiffuser/non_jinwen/旁_lishu_finetuned.png)，也没有清楚的构型改善。

数据上，甲骨文有 313 对／50 字，小篆 54 对／50 字，隶书 182 对／41 字。除少数孤立字库外，每种书体基本只有一个覆盖充分的具体字库，因此金文使用的“同字同书体跨字库原型”实验在这三类上无法按相同条件复现。

下一轮不沿用金文原型结论；先以甲骨文、隶书、小篆分别建立人工判读的留出字对照，统一图像前景极性并核验映射。当前三种书体都没有足够证据支持继续只延长 `run_003` 训练。
