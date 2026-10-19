# 项目架构

## 分层

| 层 | 位置 | 职责 |
| --- | --- | --- |
| 核心数据层 | `src/hanzi_evolution/` | SQLAlchemy Core schema、Pydantic 输入契约、内容寻址存储、导入/导出、质量报告 |
| 结果页解析 | `src/hanzi_evolution/xiaoxue.py` | 金文、小篆、隶变、字形演变结果页；标准字头校验、零结果、分页数量 |
| CLI | `src/hanzi_evolution/cli.py` | `init-db`、`import-*`、`lookup`、`export`、`report`、`validate-images`；`crawl` 仍是 dry-run |
| 采集编排 | `src/hanzi_evolution/collection/` | 批次编排、预算、断点续跑、来源选择、现代参考 |
| 兼容入口 | `scripts/` | 保留原命令，转发到 `collection` 包 |
| 第三方抓取层 | `thirdparty/xiaoxue_crawler/` | HTTP 会话、官网表单、`HiddenFrom/PageTo` 翻页、甲骨文页面解析、图片下载校验 |
| 运行时数据 | `data/` | SQLite、原图档案、原始响应、批次状态、交付快照；不进入根 Git |
| 报告 | `reports/` | 采集结果、质量基线、来源审计；进入根 Git |

## 采集调用链

`scripts/expand_50.py` 只是兼容入口；实际实现是 `src/hanzi_evolution/collection/expand.py`：

```text
scripts/expand_50.py
└── src/hanzi_evolution/collection/expand.py
    ├── collection/common.py                         # PROJECT、thirdparty 路径、save_json、停止判定
    ├── thirdparty/read_font.preflight               # robots 检查
    ├── thirdparty/http_driver.HTTPDriver            # 请求、表单、翻页、限速
    ├── thirdparty/read_font.get_xiaozhuan_list_url  # 甲骨文页面/字头/分页
    ├── collection/complete_ten.result_pages         # 跨来源页面缓存
    │   └── collection/cross_source.collect_result
    │       └── src/hanzi_evolution/xiaoxue.parse_result_page[_or_empty]
    ├── collection/cross_source.attach_images        # 图片下载调度
    │   └── thirdparty/download_img.fetch_png / validate_image
    └── src/hanzi_evolution/store.import_records / write_directory_export
```

## 数据流

1. **审计与限速**：`preflight` 读取 robots；普通 404 视为不存在，401/403/429/5xx/受限页停止。
2. **查询**：官网表单 POST；分页按 `HiddenFrom`/`PageTo` 连续推进。
3. **原始归档**：响应 HTML、表单字段、哈希、请求日志写入 `data/batches/<批次>/raw/` 与 `requests.jsonl`。
4. **解析**：甲骨文由 thirdparty 解析；跨来源由主系统 `xiaoxue.py` 解析；标准字头不一致即失败。
5. **抽样**：甲骨文每字最多 5 张；跨来源按“汉字 + 字体阶段”合计最多 5 张。
6. **下载与校验**：逐张下载，校验 MIME、格式、尺寸、SHA-256；原图按哈希归档到 `data/images/original/`。
7. **入库**：整批事务；`source_record` 幂等；`image_asset` 哈希去重；`glyph_image` 保留各来源关联。
8. **导出**：`write_directory_export` 构建临时目录，校验哈希后发布；相同内容复用，不同内容必须换新目录。

## 关键目录

```text
src/hanzi_evolution/     核心包、Alembic、collection/ 采集编排
scripts/                 兼容入口（见 scripts/README.md）
config/                  6 个来源配置
docs/                    规划、架构、数据字典、来源审计、thirdparty 说明
reports/                 运行报告与质量基线
tests/                   离线测试
thirdparty/              独立 Git 克隆，根仓库忽略；本地补丁在 patches/
data/                    运行时数据，根仓库忽略
```

## 已知结构债务

- `collection/` 通过 `common.py` 把 thirdparty 加入 `sys.path`；thirdparty 仍是源码级依赖，不是 pip 包。
- `scripts/` 只保留兼容入口，避免旧命令失效；新增采集逻辑应写入 `collection/`。
- 主 CLI 的 `hanzi crawl` 仍是 dry-run，真实采集依赖独立脚本；长期应统一成一个 adapter/调度入口。
- thirdparty 是源码级依赖，不是 pip 包；本地修改未提交，根仓库通过 `patches/xiaoxue_crawler-local.patch` 跟踪。
- 主要验证是离线测试，真实网络回归需要显式 `--execute`，并受来源限速与封禁风险约束。

## 测试

```bash
.venv/bin/pytest -q
```

当前 80 项离线测试通过，覆盖导入幂等、冲突回滚、图片校验、目录导出、限额、零结果、PUA/多字头选择、预算和封禁路径。
