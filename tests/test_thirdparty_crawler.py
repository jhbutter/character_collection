import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

REFERENCE = Path(__file__).resolve().parents[1] / "thirdparty/xiaoxue_crawler"


@pytest.fixture
def crawler(monkeypatch):
    pytest.importorskip("selenium")
    pytest.importorskip("requests")
    pytest.importorskip("lxml")
    monkeypatch.syspath_prepend(str(REFERENCE))
    spec = importlib.util.spec_from_file_location("reference_read_font", REFERENCE / "read_font.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    return module


class OfflineDriver:
    def __init__(self, html):
        self.page_source = html
        self.current_url = "https://xiaoxue.iis.sinica.edu.tw/jiaguwen?ZiOrder=1"

    def get(self, url):
        self.current_url = url

    def find_element(self, *args):
        from selenium.common.exceptions import NoSuchElementException
        raise NoSuchElementException("No pagination in fixture")


def arguments():
    return SimpleNamespace(target_url="https://xiaoxue.iis.sinica.edu.tw/jiaguwen?ZiOrder=%d",
                           root_url="https://xiaoxue.iis.sinica.edu.tw", size=64,
                           interval=5, max_pages=3, start_idx=1, transport="selenium",
                           user_agent="HanziResearchDebug/0.1")


def test_restricted_page_must_not_return_empty_success(crawler, tmp_path):
    html = (Path(__file__).parent / "fixtures/restricted.html").read_text()
    with pytest.raises(RuntimeError, match="受限"):
        crawler.get_xiaozhuan_list_url(OfflineDriver(html), arguments(), tmp_path, 1)


def test_unknown_layout_is_not_missing_record(crawler, tmp_path):
    with pytest.raises(RuntimeError, match="结构"):
        crawler.get_xiaozhuan_list_url(OfflineDriver("<html><body>changed website</body></html>"), arguments(), tmp_path, 1)


def test_old_dom_fixture_preserves_original_format(crawler, tmp_path):
    html = '<input id="ZiOrder" value="1"><table><tr><td class="VariantListA"><img src="/img?id=5&amp;size=32">合成出处</td></tr></table>'
    data = crawler.get_xiaozhuan_list_url(OfflineDriver(html), arguments(), tmp_path, 1)
    assert data["charname"] == "1"
    assert data["mapping_status"] == "unverified"
    assert data["imgList"] == [{"img_id": 0, "desc": "合成出处", "img_url": "https://xiaoxue.iis.sinica.edu.tw/img?id=5&size=64"}]
    assert len(list((tmp_path / "raw").glob("*.html"))) == 1


def test_offsite_image_stops_parser(crawler, tmp_path):
    html = '<table><tr><td class="VariantListA"><img src="https://example.invalid/evil.png"></td></tr></table>'
    with pytest.raises(RuntimeError, match="HTTPS"):
        crawler.get_xiaozhuan_list_url(OfflineDriver(html), arguments(), tmp_path, 1)


def test_pagination_repetition_is_error(crawler, tmp_path):
    class Driver(OfflineDriver):
        def find_element(self, *args):
            return SimpleNamespace(click=lambda: None)
    html = '<table><tr><td class="VariantListA"><img src="/image?id=1"></td></tr></table>'
    with pytest.raises(RuntimeError, match="重复"):
        crawler.get_xiaozhuan_list_url(Driver(html), arguments(), tmp_path, 1)


@pytest.mark.parametrize("status,body,expected", [
    (404, "not found", "not_found"),
    (200, "User-agent: *\nDisallow: /", "blocked"),
    (200, "<title>Access Restricted | ASCDC</title>", "blocked"),
    (403, "Forbidden", "blocked"),
    (429, "Too many requests", "blocked"),
    (503, "unavailable", "blocked"),
])
def test_robots_conditions(crawler, monkeypatch, tmp_path, status, body, expected):
    response = SimpleNamespace(status_code=status, content=body.encode(), text=body,
                               headers={"Content-Type": "text/plain"})
    monkeypatch.setattr(crawler.requests, "get", lambda *args, **kwargs: response)
    if expected == "blocked":
        with pytest.raises(crawler.AccessRestricted):
            crawler.preflight(arguments(), tmp_path)
    else:
        assert crawler.preflight(arguments(), tmp_path)["robots_status"] == expected


def test_modern_selenium_boot_and_quit(crawler, monkeypatch, tmp_path):
    args = arguments()
    args.save_path, args.font = tmp_path, "jiaguwen"
    args.start_idx = args.limit = 1
    args.html_file, args.probe, args.execute, args.chromedriver = None, False, True, None
    calls = []
    driver = SimpleNamespace(set_page_load_timeout=lambda n: calls.append(n), quit=lambda: calls.append("quit"))
    monkeypatch.setattr(crawler, "_parse_args", lambda: args)
    monkeypatch.setattr(crawler, "preflight", lambda *a: {})
    def chrome(*, options):
        calls.append("Chrome options keyword")
        return driver
    monkeypatch.setattr(crawler.webdriver, "Chrome", chrome)
    monkeypatch.setattr(crawler, "get_xiaozhuan_list_url", lambda *a: {"id": 1, "charname": "1", "imgList": []})
    assert crawler.main() == 0
    assert "Chrome options keyword" in calls
    assert calls[-1] == "quit"


def test_malformed_real_table_does_not_mix_citations(crawler, tmp_path):
    html = '<input id="ZiOrder" value="1"><img class="charValue" alt="&amp;0.4E00;" src="/head"><table><tr><td class="VariantListA"><img src="/img?id=1"><br>出处甲<td><td class="VariantListA"><img src="/img?id=2"><br>出处乙<td></tr></table>'
    data = crawler.get_xiaozhuan_list_url(OfflineDriver(html), arguments(), tmp_path, 1)
    assert data["charname"] == "一"
    assert data["raw_head"] == "1"
    assert [i["desc"] for i in data["imgList"] if i["desc"] != "字頭"] == ["出处甲", "出处乙"]


def test_http_driver_submits_actual_form(crawler, monkeypatch, tmp_path):
    driver = crawler.HTTPDriver(arguments(), tmp_path, crawler.check_page)
    pages = [
        '<form id="BasicFrom" action="/jiaguwen/PageResult/PageResult" method="post"><input name="ZiOrder" value="1"></form>',
        '<table><tr><td class="VariantListA"><img src="/image"></td></tr></table>',
    ]
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("data")))
        html = pages.pop(0)
        return SimpleNamespace(content=html.encode(), text=html, status_code=200,
                               headers={"Content-Type": "text/html"}, raise_for_status=lambda: None)
    monkeypatch.setattr(driver.session, "request", request)
    driver.get("https://xiaoxue.iis.sinica.edu.tw/jiaguwen/?ZiOrder=1")
    assert calls[1] == ("POST", "https://xiaoxue.iis.sinica.edu.tw/jiaguwen/PageResult/PageResult", {"ZiOrder": "1"})
    assert "VariantListA" in driver.page_source
    driver.quit()


@pytest.mark.parametrize("mime,valid", [("image/png", True), ("text/html", False)])
def test_downloader_validates_actual_format(crawler, mime, valid):
    from io import BytesIO
    from PIL import Image
    spec = importlib.util.spec_from_file_location("reference_download", REFERENCE / "download_img.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    buffer = BytesIO()
    Image.new("RGB", (10, 10), "white").save(buffer, format="PNG")
    if valid:
        metadata = module.validate_image(buffer.getvalue(), mime)
        assert (metadata["width"], metadata["height"]) == (10, 10)
    else:
        with pytest.raises(ValueError, match="MIME"):
            module.validate_image(buffer.getvalue(), mime)


def pagination_page(page, codes, total=3, pages=2, next_page=True):
    items = ''.join(f'<td class="VariantListA"><img src="/img?text={code}" alt="&amp;41.{code};">出处{code}</td>' for code in codes)
    link = f'<a class="Bookmarker" id="PageLink{page+1}">下一頁</a>' if next_page else ''
    return (f'<form id="HiddenFrom" method="post" action="/jiaguwen/PageResult/PageResult">'
        f'<input name="ZiOrder" id="ZiOrder" value="2"><input name="PageTo" id="PageTo" value="{page}">'
        '<input name="IsZiTou" value="0"><input name="CustomToken" value="keep-me">'
        '<select name="PaginalZiNum"><option value="5">5</option><option value="20" selected>20</option></select>'
        '<select name="ImageSize"><option value="36" selected>36</option></select>'
        '<img class="charValue" src="/head" alt="&amp;0.5143;">'
        f'<div>共搜尋到{total}字／{pages}頁</div><table><tr>{items}</tr></table>{link}</form>')


def test_next_page_posts_actual_form_fields(crawler, monkeypatch, tmp_path):
    driver = crawler.HTTPDriver(arguments(), tmp_path, crawler.check_page)
    driver.current_url = "https://xiaoxue.iis.sinica.edu.tw/jiaguwen/PageResult/PageResult"
    driver.page_source = pagination_page(1, ['E001','E002'])
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs['data']))
        html = pagination_page(2, ['E003'], next_page=False)
        return SimpleNamespace(content=html.encode(), text=html, status_code=200,
            headers={'Content-Type':'text/html'}, raise_for_status=lambda: None)
    monkeypatch.setattr(driver.session, 'request', request)
    driver.find_element(None, '下一頁').click()
    fields = calls[0][2]
    assert fields == {'ZiOrder':'2','PageTo':'2','IsZiTou':'0','CustomToken':'keep-me',
                      'PaginalZiNum':'20','ImageSize':'36'}
    assert calls[0][:2] == ('POST','https://xiaoxue.iis.sinica.edu.tw/jiaguwen/PageResult/PageResult')
    assert 'E003' in driver.page_source
    driver.quit()


def test_parser_combines_all_pages_without_duplicate_heads(crawler, monkeypatch, tmp_path):
    driver = crawler.HTTPDriver(arguments(), tmp_path, crawler.check_page)
    def initial(url):
        driver.current_url = url
        driver.page_source = pagination_page(1, ['E001','E002'])
    monkeypatch.setattr(driver, 'get', initial)
    def request(method, url, **kwargs):
        html = pagination_page(2, ['E003'], next_page=False)
        return SimpleNamespace(content=html.encode(), text=html, status_code=200,
            headers={'Content-Type':'text/html'}, raise_for_status=lambda: None)
    monkeypatch.setattr(driver.session, 'request', request)
    record = crawler.get_xiaozhuan_list_url(driver, arguments(), tmp_path, 2)
    assert record['charname'] == '元'
    assert len([i for i in record['imgList'] if i['desc'] != '字頭']) == 3
    assert len([i for i in record['imgList'] if i['desc'] == '字頭']) == 1
    assert len(record['raw_sha256']) == 2
    assert record['page_count'] == 2
    assert record['expected_glyph_count'] == 3
    driver.quit()


@pytest.mark.parametrize('case', ['missing_page','wrong_count','wrong_page_number','repeated_glyph'])
def test_pagination_rejects_incomplete_or_repeated_results(crawler, monkeypatch, tmp_path, case):
    driver=crawler.HTTPDriver(arguments(),tmp_path,crawler.check_page)
    total=4 if case=='wrong_count' else 3
    first=pagination_page(1,['E001','E002'],total=total,next_page=case!='missing_page')
    last=pagination_page(1 if case=='wrong_page_number' else 2,
        ['E001' if case=='repeated_glyph' else 'E003'],total=total,next_page=False)
    def initial(url):
        driver.current_url=url
        driver.page_source=first
    monkeypatch.setattr(driver,'get',initial)
    monkeypatch.setattr(driver.session,'request',lambda *args,**kwargs: SimpleNamespace(
        content=last.encode(),text=last,status_code=200,headers={'Content-Type':'text/html'},raise_for_status=lambda:None))
    with pytest.raises(crawler.PageLayoutError):
        crawler.get_xiaozhuan_list_url(driver,arguments(),tmp_path,2)
    driver.quit()


def test_pagination_follows_three_pages_in_order(crawler,monkeypatch,tmp_path):
    driver=crawler.HTTPDriver(arguments(),tmp_path,crawler.check_page)
    def initial(url):
        driver.current_url=url
        driver.page_source=pagination_page(1,['E001','E002'],total=5,pages=3)
    monkeypatch.setattr(driver,'get',initial)
    calls=[]
    def request(method,url,**kwargs):
        page=int(kwargs['data']['PageTo'])
        calls.append(page)
        codes=['E003','E004'] if page==2 else ['E005']
        html=pagination_page(page,codes,total=5,pages=3,next_page=page<3)
        return SimpleNamespace(content=html.encode(),text=html,status_code=200,
            headers={'Content-Type':'text/html'},raise_for_status=lambda:None)
    monkeypatch.setattr(driver.session,'request',request)
    record=crawler.get_xiaozhuan_list_url(driver,arguments(),tmp_path,2)
    assert calls==[2,3]
    assert record['page_count']==3 and record['expected_glyph_count']==5
    assert len([i for i in record['imgList'] if i['desc']!='字頭'])==5
    assert len(record['raw_sha256'])==3
    driver.quit()


def test_header_prefers_standard_cjk_over_pua(crawler, tmp_path):
    html = ('<input id="ZiOrder" value="11"><span id="StartOrder">11</span>'
            '<table><tr><td class="ZiList">'
            '<img class="charValue" alt="&amp;0.797C;" src="/img?text=head">'
            '<img class="charValue" alt="&amp;0.EBEC;" src="/img?text=pua">'
            '</td></tr>'
            '<tr><td class="VariantListA"><img src="/img?id=5&amp;size=32">合成出处</td></tr></table>'
            '<div class="Information">共搜尋到1字／1頁</div>')
    data = crawler.get_xiaozhuan_list_url(OfflineDriver(html), arguments(), tmp_path, 11)
    assert data['charname'] == '祼'


def test_multiple_standard_heads_use_first_primary_head(crawler, tmp_path):
    html = ('<input id="ZiOrder" value="12"><span id="StartOrder">12</span>'
            '<table><tr><td class="ZiList">'
            '<img class="charValue" alt="&amp;0.7950;" src="/img?text=you">'
            '<img class="charValue" alt="&amp;0.53C8;" src="/img?text=again">'
            '</td></tr>'
            '<tr><td class="VariantListA"><img src="/img?id=5&amp;size=32">合成出处</td></tr></table>'
            '<div class="Information">共搜尋到1字／1頁</div>')
    data = crawler.get_xiaozhuan_list_url(OfflineDriver(html), arguments(), tmp_path, 12)
    assert data['charname'] == '祐'
