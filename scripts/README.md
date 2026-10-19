# 采集脚本入口

所有脚本默认 dry-run；只有显式 `--execute` 才联网。单站串行、默认 7 秒间隔、每批最多 100 张新图；401/403/429/5xx/受限页立即停止。

| 脚本 | 用途 | 默认输出 |
| --- | --- | --- |
| `expand_50.py` | 当前入口：甲骨文 11 号起补到 50 个有图字头，再补四来源 | `data/dataset_50` |
| `batch_collect.py` | 甲骨文编号区间批次，下载全部图片后导入 | `data/batches/jiaguwen_001_010` |
| `cross_source_mvp.py` | 早期“一、天”跨来源 MVP 抽样 | `data/dataset_cross_source_mvp`（历史） |
| `complete_ten.py` | 早期 10 字四来源补采 | `data/dataset`（历史） |
| `create_demo_image.py` | 生成合成演示图片，不联网 | `data/demo_input` |

## 当前推荐流程

```bash
python scripts/expand_50.py                 # dry-run
python scripts/expand_50.py --execute       # 每批最多 100 张，重复执行续跑
```

`expand_50.py` 先补甲骨文到 50 个有图字头，再跨来源；目标按“有图片的字头数”计算。甲骨文每字最多 5 张；跨来源按“汉字 + 字体阶段”合计最多 5 张。零结果只在页面明确“共搜尋到 0 字”时记为 `no_result`。

## 依赖

- 主包：`pip install -e '.[collection]'`（`collection` 额外安装 requests/selenium）
- thirdparty：见 `thirdparty/xiaoxue_crawler/requirements.txt` 和 `docs/thirdparty.md`
- 脚本通过 `sys.path` 引用 `thirdparty/xiaoxue_crawler`，不是 pip 包。

## 状态与报告

批次状态逐条写入 `data/batches/<批次>/status.json`，原始响应和请求日志在同目录。报告写入 `reports/<批次>.json` / `.md`；当前 50 字结果见 [reports/expand_50.md](../reports/expand_50.md)。
