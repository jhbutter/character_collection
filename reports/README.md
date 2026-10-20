# 报告索引

## 当前基线

- `expand_100_screen.md` / `expand_100_screen.json`：当前100字采集报告与批次状态
- `current_quality.json`：当前数据库质量指标（100字、2019条关联、2011张原图）
- `cleanup_2026_10_20.md`：中间快照与实验产物清理记录

## 历史报告

- `expand_50.*`、`expand_50_offline.md`：50字阶段与来源限制记录
- `expand_51_pilot.*`、`expand_53_pilot.*`、`expand_60_screen.*`：续采历史批次；对应过渡目录已清理
- `batch_10.*`：甲骨文首批 1–10
- `pagination_retry.md`、`jiaguwen_multipage_*.json`：双页字头补采
- `cross_source_mvp.*`：一、天跨来源 MVP
- `complete_ten.*`：10 字四来源补采
- `thirdparty_debug.md`、`trial_result.md`：早期来源与调试记录
- `demo_quality.json`：合成演示质量，不是真实史料

报告按批次名保存，不覆盖历史文件。`data/batches/<批次>/status.json` 是逐条运行状态，`reports/*.json` 是汇总。
