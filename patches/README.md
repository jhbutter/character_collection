# 本地补丁

`xiaoxue_crawler-local.patch` 保存 `thirdparty/xiaoxue_crawler` 相对基线 `467e72bd471f871b26ee1d904c54ea6bb49ddd7b` 的本地修改，包括新增 `http_driver.py` 和 `read_font.py` / `download_img.py` / `requirements.txt` 的调整。

根仓库不跟踪 `thirdparty/`，因此用补丁保留可复现的本地差异。

应用：

```bash
git -C thirdparty/xiaoxue_crawler apply --check ../../patches/xiaoxue_crawler-local.patch
git -C thirdparty/xiaoxue_crawler apply ../../patches/xiaoxue_crawler-local.patch
```

重新生成（在 thirdparty 仓库目录）：

```bash
git add -N http_driver.py
git diff > ../../patches/xiaoxue_crawler-local.patch
git reset
```

上游未见 LICENSE；补丁仅供本地调试，不对外重新发布第三方代码。
