import hashlib
import re
import unicodedata
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from .adapters import GlyphInput

COLLECTION_NAMES = {"jinwen": "金文", "xiaozhuan": "小篆", "lishu": "隶变", "yanbian": "字形演变"}
PERIOD = re.compile(r"^(?:商(?:代)?(?:早期|中期|晚期)?|西周(?:早期|中期|晚期)?|東周|春秋(?:早期|中期|晚期)?|戰國(?:[.．·].+)?|秦|西漢|東漢|新莽|孫吳)$")


def canonical_image_url(src, base_url, size=64):
    parts = urlsplit(urljoin(base_url, src or ""))
    if (parts.scheme != "https" or parts.hostname != "xiaoxue.iis.sinica.edu.tw"
            or parts.port not in (None, 443) or parts.username is not None or not src):
        raise ValueError("图片不属于允许的官方HTTPS来源")
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "size"]
    query.append(("size", str(size)))
    return parts._replace(query=urlencode(query)).geturl()


def glyph_style(font, citation):
    if citation.startswith("說文古文"):
        return "shuowen_guwen"
    if citation.startswith("說文籀文"):
        return "shuowen_zhouwen"
    families = (("甲骨文", "jiaguwen"), ("金文", "jinwen"), ("楚系簡帛文字", "chuwenzi"),
                ("秦系簡牘文字", "qinwenzi"), ("傳抄古文字", "chuanchao"),
                ("戰國文字", "zhanguowenzi"), ("說文小篆", "xiaozhuan"),
                ("隸書", "lishu"))
    for label, style in families:
        if label in font:
            return style
    raise ValueError(f"未核验的字库分类：{font}")


def parse_result_page_or_empty(html, collection, expected_character, page_number=1, base_url=None):
    """解析结果页；只在页面明确声明 0 字且没有任何字形/编号时返回空结果。

    零结果不能由缺少结构推断：必须同时满足“共搜尋到 0 字”、无 VariantList
    单元格、无 StartOrder，且查询字头字段（若存在）与目标一致。其他情况仍按
    页面结构异常处理，避免把受限页或改版页记成来源未收录。
    """
    if collection not in COLLECTION_NAMES:
        raise ValueError("未核验的来源")
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    if any(word in text for word in ("Access Restricted", "Access Denied", "服務限制存取",
                                     "服务限制访问", "驗證碼", "验证码")):
        raise ValueError("访问受限页面")
    info = soup.select_one(".Information")
    summary = info.get_text(" ", strip=True) if info else ""
    if re.search(r"共搜尋到\s*0\s*字(?:\s*／\s*0\s*頁)?", summary):
        if page_number != 1:
            raise ValueError("零结果不应出现在分页中")
        start_orders = [node.get_text(strip=True) for node in soup.select("span#StartOrder")]
        if soup.select("td.VariantListA,td.VariantListB") or any(start_orders):
            raise ValueError("零结果页面仍包含字形或字头编号，不能按空结果处理")
        hidden = soup.find(id="EudcFontChar")
        if hidden is not None and hidden.get("value") not in ("", expected_character):
            raise ValueError("零结果查询字段与目标字头不一致")
        return {"source_record_id": None, "character": expected_character,
                "expected_glyph_count": 0, "page_count": 1,
                "glyphs": [], "modern_reference": None, "empty": True}
    return parse_result_page(html, collection, expected_character, page_number, base_url)


def parse_result_page(html, collection, expected_character, page_number=1, base_url=None):
    if collection not in COLLECTION_NAMES:
        raise ValueError("未核验的来源")
    base_url = base_url or f"https://xiaoxue.iis.sinica.edu.tw/{collection}/"
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    if any(word in text for word in ("Access Restricted", "Access Denied", "服務限制存取", "服务限制访问", "驗證碼", "验证码")):
        raise ValueError("访问受限页面")
    orders = soup.select("span#StartOrder")
    if len(orders) != 1 or not orders[0].get_text(strip=True).isdecimal():
        raise ValueError("结果不是一个可确认编号的字头")
    row = orders[0].find_parent("tr")
    standard_heads = []
    for image in row.select("img.charValue"):
        match = re.fullmatch(r"&(0|27)\.([0-9A-Fa-f]+);", image.get("alt", ""))
        if match:
            character = chr(int(match[2], 16))
            query = parse_qs(urlsplit(urljoin(base_url, image.get("src", ""))).query)
            if match[1] == "27" and (query.get("font") != ["北師大說文小篆"] or query.get("text") != [character]):
                continue
            if unicodedata.name(character, "").startswith("CJK UNIFIED IDEOGRAPH"):
                standard_heads.append((character, image))
    if not standard_heads or standard_heads[0][0] != expected_character:
        raise ValueError("结果字头与查询汉字不一致，不自动建立跨库映射")
    hidden = soup.find(id="EudcFontChar")
    if hidden and hidden.get("value") not in ("", expected_character):
        raise ValueError("来源查询字段与目标字头不一致")
    info = soup.select_one(".Information")
    summary = re.search(r"共搜尋到\s*(\d+)\s*字(?:\s*／\s*(\d+)\s*頁)?", info.get_text(" ", strip=True) if info else "")
    if not summary:
        raise ValueError("缺少已核验的结果数量声明")
    expected_count, page_count = int(summary[1]), int(summary[2] or 1)
    page_field = soup.find(id="PageTo")
    if page_count > 1 and (page_field is None or page_field.get("value") != str(page_number)):
        raise ValueError("来源分页页码不连续")
    glyphs = []
    for cell in soup.select("td.VariantListA,td.VariantListB"):
        image = cell.find("img")
        if not image:
            continue
        url = canonical_image_url(image.get("src"), base_url)
        font = parse_qs(urlsplit(url).query).get("font", [""])[0]
        citation = cell.get_text(" ", strip=True)
        if not citation:
            raise ValueError("字形缺少出处，不自动导入")
        style = glyph_style(font, citation)
        period_lines = [line for line in cell.stripped_strings if PERIOD.fullmatch(line)]
        if len(set(period_lines)) > 1:
            raise ValueError("同一字形存在多个断代标签，需人工核验")
        period = period_lines[0] if period_lines else None
        code = image.get("alt", "").strip("&;")
        if not code:
            raise ValueError("图片缺少来源字形编码")
        key = code + ":" + hashlib.sha256(citation.encode()).hexdigest()[:12]
        glyphs.append(GlyphInput(local_key=key, character=expected_character, script_style=style,
            period=period, date_basis=f"来源单元格断代原文：{period}" if period else None,
            citation=citation, image_url=url))
    reference = None
    if page_number == 1 and collection == "yanbian":
        _, image = standard_heads[0]
        url = canonical_image_url(image.get("src"), base_url)
        if parse_qs(urlsplit(url).query).get("font") == ["標楷體"]:
            reference = GlyphInput(local_key="modern-standard-head", character=expected_character,
                script_style="kaishu_reference", image_url=url,
                citation="小学堂现代表头；標楷體字体渲染，仅作现代字头参考，非历史楷书文物或碑帖样本")
    return {"source_record_id": orders[0].get_text(strip=True), "character": expected_character,
            "expected_glyph_count": expected_count, "page_count": page_count,
            "glyphs": glyphs, "modern_reference": reference}


def sample_by_style(glyphs, limit):
    selected, counts = [], {}
    for glyph in glyphs:
        style = glyph.script_style
        if counts.get(style, 0) < limit:
            selected.append(glyph)
            counts[style] = counts.get(style, 0) + 1
    return selected


def read_cached_sample(path, collection, character, per_style):
    import json
    from .adapters import RecordInput
    raw = path.read_bytes()
    packet = json.loads(raw)
    if packet['source'] != collection or packet['query_character'] != character:
        raise ValueError('缓存来源或字头不一致')
    sampling = packet['sampling']
    if sampling['per_style_limit'] != per_style:
        raise ValueError('抽样上限已改变，请使用新的MVP采集目录')
    record = RecordInput.model_validate(packet['normalized'])
    if record.local_id != packet['source_record_id'] or any(g.character != character for g in record.glyphs):
        raise ValueError('缓存的来源编号或字头不一致')
    if sampling['retained_glyph_count'] != len(record.glyphs) or sampling['available_glyph_count'] < len(record.glyphs):
        raise ValueError('缓存抽样数量不一致')
    for page in packet['pages']:
        if hashlib.sha256(page['html'].encode()).hexdigest() != page['sha256']:
            raise ValueError('缓存网页哈希不一致')
    return record, packet, raw


def select_missing_styles(glyphs, existing_rows, limit=5):
    counts, known = {}, set()
    for row in existing_rows:
        if row['image_path']:
            key = (row['character'], row['script_style'])
            counts[key] = counts.get(key, 0) + 1
            known.add((row['character'], row['script_style'], row['original_url']))
    selected = []
    for glyph in glyphs:
        key = (glyph.character, glyph.script_style)
        identity = (*key, glyph.image_url)
        if identity in known or counts.get(key, 0) >= limit:
            continue
        selected.append(glyph)
        known.add(identity)
        counts[key] = counts.get(key, 0) + 1
    return selected
