# thirdparty/xiaoxue_crawler 说明

## 基线

- 上游：https://github.com/EvaWang/xiaoxue_crawler
- 本地基线：`467e72bd471f871b26ee1d904c54ea6bb49ddd7b`
- 根仓库不跟踪 `thirdparty/`，保留其独立 Git 历史。

## 本地修改

| 文件 | 状态 | 用途 |
| --- | --- | --- |
| `http_driver.py` | 新增（非 upstream） | HTTP 会话、官网表单 POST、`HiddenFrom/PageTo` 翻页、请求日志、限速 |
| `read_font.py` | 修改 | 甲骨文页面解析；PUA 外字不得覆盖标准字头；多个标准字头取第一个 CJK；robots 预检 |
| `download_img.py` | 修改 | 图片下载、MIME/格式/尺寸/哈希校验 |
| `requirements.txt` | 修改 | 本地运行依赖 |

这些修改未在第三方仓库提交。根仓库通过 `patches/xiaoxue_crawler-local.patch` 保存差异。

## 重新 clone 并应用补丁

```bash
git clone https://github.com/EvaWang/xiaoxue_crawler thirdparty/xiaoxue_crawler
git -C thirdparty/xiaoxue_crawler checkout 467e72bd471f871b26ee1d904c54ea6bb49ddd7b
git -C thirdparty/xiaoxue_crawler apply ../../patches/xiaoxue_crawler-local.patch
git -C thirdparty/xiaoxue_crawler status --short
```

补丁路径以 `thirdparty/xiaoxue_crawler` 为根，应用前建议先 `git apply --check`。

## 许可与发布

上游未见明确 LICENSE。当前修改仅用于本地调试和研究流程，未经另行核验不对外重新发布其代码。根仓库不包含 thirdparty 源码，只包含本项目的补丁和调用代码。
