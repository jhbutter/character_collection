"""采集脚本共用的项目根目录、thirdparty 路径与状态工具。"""

import json
import sys
from pathlib import Path

import requests

PROJECT = Path(__file__).resolve().parents[3]
THIRDPARTY = PROJECT / "thirdparty/xiaoxue_crawler"
if str(THIRDPARTY) not in sys.path:
    sys.path.insert(0, str(THIRDPARTY))

# thirdparty 需在 sys.path 设置后导入；这里只依赖其中的受限页异常。
from read_font import AccessRestricted  # noqa: E402


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_stop_error(error):
    if isinstance(error, AccessRestricted):
        return True
    if isinstance(error, requests.HTTPError):
        return error.response is not None and (
            error.response.status_code in {401, 403, 429} or error.response.status_code >= 500
        )
    return isinstance(error, (requests.ConnectionError, requests.Timeout))
