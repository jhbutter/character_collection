# 扩展到 50 字：离线准备与封禁记录（2026-10-19）

> 后续：2026-10-19 已恢复访问并完成扩字，最终结果见 `reports/expand_50.md`。本文保留当时的离线准备与 401 封禁记录。

## 当时状态：采集暂停

为扩到 50 字做首次查询探测时，只发送了 1 个 `robots.txt` 请求（13:16:47），返回 HTTP 401，页面正文明确“您的IP已被 封鎖”。按项目规则立即停止：未访问查询页、未下载图片、未写数据库。

证据：

- `data/batches/expand_50_probe/preflight.json`
- `data/batches/expand_50_probe/raw/robots-d402076bd2fdd9624dc01034d904c664c69dd0048fc9bae4032c4eef691a093d.response`

该状态属于硬停止，不重试、不换代理、不伪装身份、不登录绕过。官方反馈入口：https://ascdc.sinica.edu.tw/contact

## 已完成的离线准备

- 新增 `scripts/expand_50.py`：默认 dry-run，解封后显式 `--execute`。
- 两阶段：先补甲骨文到 50 个有图字头，再为这 50 字补金文、小篆、隶变、字形演变。
- 甲骨文每字最多 5 张；跨来源仍按“汉字 + 字体阶段”合计最多 5 张。
- 每批最多 100 张新图；下载前做预算检查，避免半条记录。
- 默认 `--start-id 11 --end-id 60`，11–50 为主，51–60 仅在失败/无数据时补足；严格只做 11–50 可加 `--end-id 50`。
- 目标按“有图片的字头数”计算，不把尝试次数当成完成字数。
- 默认输出 `data/dataset_50`，不覆盖现有 `data/dataset`。
- 零结果解析只在页面明确“共搜尋到 0 字”、且无 `VariantList`/`StartOrder` 时记为 `no_result`；缺少结构、受限页或验证码仍失败/停止。
- 离线测试 77 项通过，新增覆盖：零结果严格判定、甲骨文前 5 张选择、预算前检查、封禁路径、缓存零结果页。

## 解封后的运行顺序

1. 先 dry-run 确认范围，不联网：

```bash
python scripts/expand_50.py
```

2. 单字烟测：只处理甲骨文 11 号，目标设为 11 个有图字头（现有 10 字已满，因此只新增 1 字及其跨来源）：

```bash
python scripts/expand_50.py --execute --start-id 11 --end-id 11 --target 11
```

3. 检查 `reports/expand_50.json`、`data/batches/expand_50/status.json` 与 `reports/expand_50.md`：
   - 若出现 `no_result`，确认页面确实是“0 字”；
   - 若出现 `failed`，先看错误是零结果结构不符、未知字体还是分页异常，不要强行重试；
   - 若出现 `blocked`，立即停止并保留证据。

4. 烟测通过后跑完整批次；每批最多 100 张，重复执行同一命令即可续跑：

```bash
python scripts/expand_50.py --execute
```

   严格只做甲骨文 11–50：

```bash
python scripts/expand_50.py --execute --end-id 50
```

5. 完成后检查 `data/dataset_50/manifest.json`：目标为 50 个汉字、每字每字体最多 5 张；如果导出目录已存在且内容不同，脚本会报 `export_error`，请换新目录，不覆盖旧快照。

## 预期工作量

- 甲骨文 40 字 × 最多 5 张 ≈ 200 张；跨来源约 500–700 张。
- 按 100 张/批，约 6–9 批；按 7 秒间隔，约 1.5–2.5 小时网络等待。
- 网络恢复前不发任何请求；当前数据库仍为 10 字、336 条关联、328 张不同原图。

## 仍需注意

- 零结果解析目前只有合成 fixture，**尚未用真实零结果页核验**；烟测阶段必须确认真实页面结构，不能把“未知页”当“来源未收录”。
- 新记录仍是 `mapping_status=unverified`、`review_status=pending`，逐图许可为空；50 字数据集仍是内部待审快照，不是可公开发布的数据包。
- 不自动归并繁简/异体；甲骨文字头必须来自来源标准字头，不用站内编号冒充 Unicode。
