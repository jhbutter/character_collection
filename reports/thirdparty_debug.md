# 第三方爬虫调试结果（2026-10-18）

**结果：已实际采集并入库“一”的3条甲骨文字形、3张图片。**

## 上游及本地状态

- 目录：thirdparty/xiaoxue_crawler
- 上游：https://github.com/EvaWang/xiaoxue_crawler
- 基线：467e72bd471f871b26ee1d904c54ea6bb49ddd7b
- 修改：read_font.py、download_img.py、requirements.txt；新增 http_driver.py。
- 保留独立 Git 历史，未 commit/push。

## 确定的故障及修复

1. 原版单条启动立即 TypeError：chrome_options 不再支持。改为 options=，可指定 Service 路径。
2. 地区限制HTML会被记为成功空结果。回归测试先复现失败，再修为显式错误；不重试受限/验证码页。
3. 旧 GET 只预填表单，不执行查询。实测首页后，使用实际 BasicFrom action、method和input字段提交POST，普通HTTP即可取到结果。
4. 原 html.parser 对未闭合td产生嵌套，导致出处串联。lxml按表格规则修复结构，逐图出处不再串联。
5. charname错误读取编号。将页头标准字形alt中的码位用于来源字头展示；原编号另存raw_head，映射仍待审核。
6. 文件名写死甲骨文、重试计数耗尽、重复追加、浏览器不释放等问题已修；默认dry-run，限制调试范围。
7. 下载不再依赖wget，保存前检查域名、HTTP状态、MIME、大小、真实格式和解码结果，记录SHA-256与出处。

## 实测成果

| 字头 | 站内编号 | 图片 | 出处 | 尺寸 |
|---|---|---|---|---|
| 一 | 1 | 1_2.png | 鐵148.1 | 88×87 |
| 一 | 1 | 1_3.png | 前4.47.6；合10308；賓組 | 88×87 |
| 一 | 1 | 1_4.png | 佚434；合37497；黃組 | 88×87 |

图像是查询界面返回的字库渲染图，不是原物照片。均为非空透明PNG、3个不同哈希，原图归档成功；不将示意字头图算作古文字实例。

完整采集结果：data/thirdparty_debug/collected/jiaguwen/jiaguwen.jsonl。
请求日志：同目录requests.jsonl；下载清单downloads.jsonl；图片img/。
数据库：data/hanzi.sqlite。查询命令：`.venv/bin/hanzi lookup --character 一`。

主系统source_record保留来源URL、原始JSONL哈希和解析版本xiaoxue-legacy-v2，图片按哈希去重。3条记录均unverified/pending，逐图许可尚未赋值，默认正式导出为0条；不能把“成功下载”当作“已完成学术审核”。

## 复现命令

在项目根目录：

```bash
.venv/bin/python -m pip install --index-url https://pypi.org/simple -r thirdparty/xiaoxue_crawler/requirements.txt
.venv/bin/python thirdparty/xiaoxue_crawler/read_font.py --execute --transport http \
  --font jiaguwen --start_idx 1 --limit 1 --save_path data/thirdparty_debug/collected
.venv/bin/python thirdparty/xiaoxue_crawler/download_img.py --execute --limit 3 \
  --file_list data/thirdparty_debug/collected/jiaguwen/jiaguwen.jsonl \
  --save_path data/thirdparty_debug/collected/jiaguwen
.venv/bin/hanzi import-legacy data/thirdparty_debug/collected/jiaguwen/jiaguwen.jsonl \
  --source-config config/xiaoxue_jiaguwen.json --collection jiaguwen \
  --image-root data/thirdparty_debug/collected/jiaguwen/img
```

再次运行会跳过已完成编号；不加--execute时不联网。HTTP仅验证本条单页，检测到下一页时拒绝输出不完整记录；Selenium线上模式因ChromeDriver下载等待过久停止，未验证成功。不同书体仍需逐源实测。

需要重新clone时：`git clone https://github.com/EvaWang/xiaoxue_crawler.git thirdparty/xiaoxue_crawler`，但这只取得上游原版，不含本地修补。当前工作区是完整可运行的调试版本。

最终验证：`.venv/bin/pytest -q`，34 passed in 0.38s。再次导入同一JSONL跳过1条、增加0字形；内部审阅导出3行、默认正式导出0行。图片完整率和来源可追溯率均为1.0，仅描述本条3图样本。
