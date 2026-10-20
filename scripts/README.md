# 采集脚本入口

采集脚本是**兼容入口**，实际实现位于 `src/hanzi_evolution/collection/`；ML 脚本实现位于 `src/hanzi_evolution/ml/`。保留脚本路径是为了让既有命令和批次文档继续可用。

采集入口默认 dry-run；只有显式 `--execute` 才联网。训练入口只读取本地图片，不联网。单站串行、默认 7 秒间隔、每批最多 100 张新图；401/403/429/5xx/受限页立即停止。

| 脚本（兼容入口） | 实现 | 用途 | 默认输出 |
| --- | --- | --- | --- |
| `expand_50.py` | `collection/expand.py` | 50 字阶段兼容入口：甲骨文 11 号起补到 50 个有图字头，再补四来源 | `data/dataset_50` |
| `batch_collect.py` | `collection/batch.py` | 甲骨文编号区间批次，下载全部图片后导入 | `data/batches/jiaguwen_001_010` |
| `cross_source_mvp.py` | `collection/cross_source.py` | 早期“一、天”跨来源 MVP 抽样 | `data/dataset_cross_source_mvp`（历史） |
| `complete_ten.py` | `collection/complete_ten.py` | 早期 10 字四来源补采 | `data/dataset`（历史） |
| `create_demo_image.py` | 同文件 | 生成合成演示图片，不联网 | `data/demo_input` |
| `build_style_pairs.py` | `hanzi_evolution.ml.pairs` | 构建楷书参考到早期书体的成对清单，不联网、不训练 | `data/ml/style_pairs` |
| `style_ddpm.py` | `hanzi_evolution.ml.style_ddpm` | 训练 64×64 条件 DDPM、生成候选图及留出字对照图，不联网 | `data/ml/style_ddpm` |
| `finetune_fontdiffuser.py` | `hanzi_evolution.ml.fontdiffuser_adapter` | 用官方预训练权重微调及生成四列留出字对照图，不联网 | `data/ml/fontdiffuser` |

## 50 字阶段兼容命令

```bash
python scripts/expand_50.py                 # dry-run
python scripts/expand_50.py --execute       # 每批最多 100 张，重复执行续跑
hanzi collect-expand50 --execute            # 等价 CLI 入口
```

`collection/expand.py` 先补甲骨文到目标有图字头数，再跨来源；甲骨文每字最多 5 张，跨来源按“汉字 + 字体阶段”合计最多 5 张。零结果只在页面明确“共搜尋到 0 字”时记为 `no_result`。续采使用 `hanzi collect-expand --new-only`，跨来源只查询本批甲骨文编号对应的字头，包含金文；每批指定新的 `--folder` 和 `--output`，报告按批次目录名保存。例如：

```bash
hanzi collect-expand --start-id 70 --end-id 80 --target 54 --new-only \
  --folder data/batches/expand_54 --output data/dataset_54
# 核对 dry-run 后在同一命令末尾加 --execute；中断后重复同一命令续跑
```

2026-10-19 续采两批取得“介、公、余”，历史结果分别见 [expand_51_pilot](../reports/expand_51_pilot.md) 和 [expand_53_pilot](../reports/expand_53_pilot.md)；对应过渡目录已清理。当前100字结果见 [expand_100_screen](../reports/expand_100_screen.md)，目录为 `data/dataset_100_screen` 与 `data/dataset_100_by_style`。

## screen 后台续采（历史示例）

以下命令曾用于从 53 字扩到 60 字，包含金文；目前已完成 100 字采集：

```bash
screen -dmS hanzi-collect-60 bash scripts/run_collection_screen.sh 60 70 110 5
screen -ls
tail -f data/batches/expand_60_screen/run.log
```

`run_collection_screen.sh` 的参数依次为目标有图字头数、甲骨文起止编号和最多续跑轮数。每轮最多下载 100 张新图，默认 7 秒间隔；仅在图片预算用尽时自动续跑。遇到 401/403/429/5xx、访问受限、结构错误、跨来源失败或编号范围不足即停止，不自动改用其他网络通道。状态见 `data/batches/expand_60_screen/status.json`，报告见 `reports/expand_60_screen.json`；最终目录只在全部完成后创建。原图和数据库保留待审核状态，后台采集不会代替人工核验。

## 依赖

- 主包：`pip install -e '.[collection]'`（`collection` 额外安装 requests/selenium）
- thirdparty：见 `thirdparty/xiaoxue_crawler/requirements.txt` 和 `docs/thirdparty.md`
- `collection/common.py` 通过 `sys.path` 引用 `thirdparty/xiaoxue_crawler`，不是 pip 包。

## 状态与报告

批次状态逐条写入 `data/batches/<批次>/status.json`，原始响应和请求日志在同目录。报告写入 `reports/<批次>.json` / `.md`；当前 100 字结果见 [expand_100_screen](../reports/expand_100_screen.md)，50 字阶段结果见 [expand_50](../reports/expand_50.md)。
