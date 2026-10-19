# 报告索引

## 当前基线

- `expand_50.md` / `expand_50.json`：50 字最终采集报告与逐批状态
- `expand_50_offline.md`：扩字前的离线准备和 401 封禁记录
- `current_quality.json`：当前数据库质量指标（50 字、1023 条关联、1015 张原图）

## 历史报告

- `batch_10.*`：甲骨文首批 1–10
- `pagination_retry.md`、`jiaguwen_multipage_*.json`：双页字头补采
- `cross_source_mvp.*`：一、天跨来源 MVP
- `complete_ten.*`：10 字四来源补采
- `thirdparty_debug.md`、`trial_result.md`：早期来源与调试记录
- `demo_quality.json`：合成演示质量，不是真实史料

报告按批次名保存，不覆盖历史文件。`data/batches/<批次>/status.json` 是逐条运行状态，`reports/*.json` 是汇总。
