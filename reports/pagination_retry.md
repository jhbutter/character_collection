# 多页逻辑修复与真实补采结果

日期：2026-10-18（Asia/Shanghai）。补采约21:49:54–22:03:12，分两批串行执行，默认请求间隔7秒，每批最多100张新图片。

## 结果

| 来源编号 | 字头 | 页数 | 网站声明字形数 | 实际下载并入库 |
|---|---|---:|---:|---:|
| 2 | 元 | 2 | 33 | 33 |
| 3 | 天 | 2 | 22 | 22 |
| 4 | 吏 | 2 | 22 | 22 |
| 6 | 帝 | 2 | 26 | 26 |

4个编号全部成功，新增103张不同哈希的字形图。加上原有6字头43图，数据库及最终目录现为10字头、146条字形、146张图片。编号1–10的原分页失败项全部补齐。

所有146张图片可解码，SHA-256与manifest一致，透明通道有非空内容；来源追溯率、图片校验通过率均1.0。这些指标仅描述当前10字头样本。

## 修改内容

1. 根据官网FeedbackScript.js的实际逻辑，读取“下一頁”链接的PageLink编号，修改HiddenFrom的PageTo并提交POST。
2. 保留真实表单全部input值与select选中值，不猜测新接口或丢失查询条件。
3. 每页核对来源编号、连续页码、网站声明的总页数/总字形数，记录原始响应哈希。
4. 检测重复页面、跨页重复字形、漏页、计数变化、总数不符和页数上限；异常时不返回完整记录。
5. 多页结果合并时只保留一次字头示意图；各实际字形保持独立出处和全局图片序号。
6. 批次报告改按批次目录名保存，避免覆盖历史首批报告。

## 保存位置

- 当前最终图片目录：data/dataset/<汉字>/甲骨文/*.png。
- 每字元数据：data/dataset/<汉字>/metadata.jsonl。
- 数据库：data/hanzi.sqlite。
- 完整快照：data/dataset_pagination_complete。
- 补采前43图目录备份：data/dataset_before_pagination。
- 元/天/吏的原始网页、JSONL和图片：data/batches/jiaguwen_multipage_002_004/records/<编号>/。
- 帝的原始网页、JSONL和图片：data/batches/jiaguwen_multipage_006/records/6/。
- 各批次请求日志requests.jsonl、下载日志downloads.jsonl、状态status.json保存在对应批次根目录。
- 机器报告：reports/jiaguwen_multipage_002_004.json、reports/jiaguwen_multipage_006.json。
- 全库质量报告：reports/current_quality.json。

## 验证与边界

49项离线测试通过，覆盖两页/三页、漏页、错误页码、重复字形、总数不符及批次停止规则。随后对4个真实双页记录逐一验证，解析数量与声明数量一致，并完成103张图片下载、事务入库及最终146图目录校验。

原始记录保持可追溯，待审阅状态不变：mapping_status=unverified、review_status=pending，具体断代仍null，逐图许可未自动赋值。当前资料目录为内部待审集；金文、小篆、空查询结果和超大页数尚未据本轮测试宣称全面支持。
