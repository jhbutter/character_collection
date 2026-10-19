import pytest
from hanzi_evolution.xiaoxue import parse_result_page, parse_result_page_or_empty


def html(head='一', source_id='987', font='中研院金文重文一', citation='器名<br>西周早期<br>集成123', summary='共搜尋到1字／1頁'):
    return (f'<form><input id="EudcFontChar" value="{head}"><input id="PageTo" value="1">'
        f'<table><tr><td class="ZiList"><span id="StartOrder">{source_id}</span></td>'
        f'<td><img class="charValue" alt="&amp;0.{ord(head):X};" src="/ImageText2/ShowImage.ashx?font=標楷體&amp;text={head}"></td></tr>'
        f'<tr><td class="Information">{summary}</td></tr>'
        f'<tr><td class="VariantListA"><img alt="&amp;31.E000;" src="/ImageText2/ShowImage.ashx?font={font}&amp;text=x">{citation}</td></tr></table></form>')


def test_mapping_uses_result_head_not_shared_source_id():
    page=parse_result_page(html(source_id='987'),'jinwen','一')
    assert page['source_record_id']=='987'
    assert page['glyphs'][0].character=='一'
    assert page['glyphs'][0].period=='西周早期'
    assert page['glyphs'][0].date_start is None
    assert '来源单元格' in page['glyphs'][0].date_basis


def test_mismatched_character_is_rejected():
    with pytest.raises(ValueError,match='字头'):
        parse_result_page(html(head='天'),'jinwen','一')


@pytest.mark.parametrize('font,style', [('中研院秦系簡牘文字重文一','qinwenzi'),('中研院隸書重文一','lishu')])
def test_lishu_collection_retains_per_image_family(font,style):
    page=parse_result_page(html(font=font,citation='出处<br>秦'),'lishu','一')
    assert page['glyphs'][0].script_style==style


def test_shuowen_guwen_is_not_automatically_small_seal():
    page=parse_result_page(html(font='北師大說文小篆',citation='說文古文',summary='共搜尋到1字，字形大小：'),'xiaozhuan','一')
    assert page['glyphs'][0].script_style=='shuowen_guwen'
    assert page['page_count']==1


def test_modern_header_is_separate_reference_not_ancient_glyph():
    page=parse_result_page(html(),'yanbian','一')
    assert len(page['glyphs'])==1
    assert page['modern_reference'].script_style=='kaishu_reference'
    assert '非历史' in page['modern_reference'].citation


def test_pua_or_missing_standard_head_does_not_become_modern_character():
    text=html().replace('&amp;0.4E00;','&amp;1.E000;')
    with pytest.raises(ValueError,match='字头'):
        parse_result_page(text,'jinwen','一')


def test_unknown_font_family_is_not_guessed_from_collection():
    with pytest.raises(ValueError,match='未核验'):
        parse_result_page(html(font='unknown font'),'jinwen','一')


def test_cross_source_sample_pipeline_merges_characters_and_preserves_ids(tmp_path):
    import json
    from PIL import Image
    from hanzi_evolution.adapters import RecordInput,SourceInput
    from hanzi_evolution.db import open_db
    from hanzi_evolution.store import import_records,export_rows,write_directory_export
    from hanzi_evolution.xiaoxue import sample_by_style
    Image.new('RGB',(12,12),'white').save(tmp_path/'test.png')
    engine=open_db(tmp_path/'db.sqlite')
    for collection,source_id,font,citation in [('jinwen','987','中研院金文重文一','器名<br>西周早期'),
                                             ('xiaozhuan','42','北師大說文小篆','說文‧一部')]:
        page=parse_result_page(html(source_id=source_id,font=font,citation=citation),collection,'一')
        glyphs=sample_by_style(page['glyphs']*3,1)
        glyphs=[g.model_copy(update={'image_path':'test.png'}) for g in glyphs]
        record=RecordInput(local_id=source_id,source_url=f'https://example.invalid/{collection}',raw_head=source_id,glyphs=glyphs)
        raw=json.dumps({'sampling':'mvp','normalized':record.model_dump()},ensure_ascii=False).encode()
        import_records(engine,tmp_path,SourceInput(id=collection,name='合成测试',is_test=True),[record],raw,'fixture',tmp_path)
    rows=export_rows(engine,True,True)
    assert {r['source_record_id'] for r in rows}=={'987','42'}
    result=write_directory_export(rows,tmp_path,tmp_path/'dataset',True,True)
    assert result['character_count']==1 and result['glyph_count']==2
    assert (tmp_path/'dataset/一/金文').is_dir()
    assert (tmp_path/'dataset/一/小篆').is_dir()
    engine.dispose()


def test_modern_reference_has_explicit_export_folder(tmp_path):
    from PIL import Image
    from hanzi_evolution.adapters import RecordInput,SourceInput
    from hanzi_evolution.db import open_db
    from hanzi_evolution.store import import_records,export_rows,write_directory_export
    glyph=parse_result_page(html(),'yanbian','一')['modern_reference']
    Image.new('RGB',(12,12),'white').save(tmp_path/'test.png')
    glyph=glyph.model_copy(update={'image_path':'test.png'})
    engine=open_db(tmp_path/'db.sqlite')
    import_records(engine,tmp_path,SourceInput(id='reference',name='现代字头合成测试',is_test=True),
        [RecordInput(local_id='1',glyphs=[glyph])],b'synthetic','fixture',tmp_path)
    write_directory_export(export_rows(engine,True,True),tmp_path,tmp_path/'dataset',True,True)
    assert (tmp_path/'dataset/一/现代楷书参考').is_dir()
    assert not (tmp_path/'dataset/一/楷书').exists()
    engine.dispose()


def test_mvp_cache_preserves_original_image_paths_and_checks_sampling(tmp_path):
    import hashlib,json
    from hanzi_evolution.adapters import RecordInput
    from hanzi_evolution.xiaoxue import read_cached_sample
    text=html(source_id='987')
    page=parse_result_page(text,'jinwen','一')
    record=RecordInput(local_id='987',glyphs=[page['glyphs'][0].model_copy(update={'image_path':'batches/sample/images/one.png'})])
    packet={'source':'jinwen','query_character':'一','source_record_id':'987',
        'sampling':{'per_style_limit':2,'available_glyph_count':1,'retained_glyph_count':1},
        'pages':[{'html':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}],
        'normalized':record.model_dump()}
    path=tmp_path/'record.jsonl'
    path.write_text(json.dumps(packet,ensure_ascii=False)+'\n')
    restored,_,raw=read_cached_sample(path,'jinwen','一',2)
    assert restored.glyphs[0].image_path=='batches/sample/images/one.png'
    assert raw==path.read_bytes()
    with pytest.raises(ValueError,match='上限'):
        read_cached_sample(path,'jinwen','一',3)
    with pytest.raises(ValueError,match='字头'):
        read_cached_sample(path,'jinwen','天',2)
    packet['pages'][0]['html']+='changed'
    path.write_text(json.dumps(packet,ensure_ascii=False))
    with pytest.raises(ValueError,match='哈希'):
        read_cached_sample(path,'jinwen','一',2)


def test_fill_style_limit_uses_global_count_and_skips_existing_urls():
    from hanzi_evolution.xiaoxue import select_missing_styles
    glyph = parse_result_page(html(), 'jinwen', '一')['glyphs'][0]
    existing = [{'character': '一', 'script_style': 'jinwen', 'image_path': 'one.png',
                 'original_url': f'https://example.invalid/{i}'} for i in range(4)]
    candidates = [glyph.model_copy(update={'image_url': existing[0]['original_url']}), glyph,
                  glyph.model_copy(update={'image_url': 'https://example.invalid/new'})]
    selected = select_missing_styles(candidates, existing)
    assert selected == [glyph]
    other = glyph.model_copy(update={'character': '天'})
    assert select_missing_styles([other], existing) == [other]


def test_standard_header_allows_parenthetical_private_use_reference():
    text = html(head='上').replace('</td></tr>', '<img class="charValue" alt="&amp;0.F3F2;"></td></tr>', 1)
    page = parse_result_page(text, 'xiaozhuan', '上')
    assert page['character'] == '上'
    assert page['glyphs'][0].character == '上'


def test_result_uses_primary_header_not_parenthetical_variant():
    text = html(head='旁').replace('</td></tr>', '<img class="charValue" alt="&amp;0.3AC4;"></td></tr>', 1)
    assert parse_result_page(text, 'xiaozhuan', '旁')['character'] == '旁'
    with pytest.raises(ValueError, match='字头'):
        parse_result_page(text, 'xiaozhuan', '㫄')


def test_seal_header_requires_confirmed_font_and_matching_text():
    text = html(head='元').replace('&amp;0.5143;', '&amp;27.5143;').replace('font=標楷體', 'font=北師大說文小篆')
    text = text.replace('</td></tr>', '<img class="charValue" alt="&amp;0.5140;"></td></tr>', 1)
    assert parse_result_page(text, 'jinwen', '元')['character'] == '元'
    with pytest.raises(ValueError, match='字头'):
        parse_result_page(text.replace('font=北師大說文小篆', 'font=unknown'), 'jinwen', '元')
    with pytest.raises(ValueError, match='字头'):
        parse_result_page(text.replace('text=元', 'text=天'), 'jinwen', '元')


def empty_html(head='一', summary='共搜尋到 0 字'):
    return (f'<form id="BasicFrom" action="/jinwen/PageResult/PageResult" method="post">'
            f'<input id="EudcFontChar" value="{head}"></form>'
            f'<div class="Information">{summary}</div>')


def test_explicit_zero_result_is_not_a_layout_failure():
    page = parse_result_page_or_empty(empty_html(), 'jinwen', '一')
    assert page['empty'] is True
    assert page['source_record_id'] is None
    assert page['expected_glyph_count'] == 0
    assert page['glyphs'] == [] and page['modern_reference'] is None


def test_zero_result_with_variant_or_source_id_is_rejected():
    with_variant = empty_html() + ('<table><tr><td class="VariantListA">'
                                   '<img src="/ImageText2/ShowImage.ashx?font=x&amp;text=x">出处</td></tr></table>')
    with pytest.raises(ValueError, match='零结果页面'):
        parse_result_page_or_empty(with_variant, 'jinwen', '一')
    with_source = empty_html().replace('</form>', '<span id="StartOrder">7</span></form>')
    with pytest.raises(ValueError, match='零结果页面'):
        parse_result_page_or_empty(with_source, 'jinwen', '一')


def test_zero_result_allows_empty_start_order_placeholder():
    text = empty_html().replace('</form>', '<span id="StartOrder"></span></form>')
    page = parse_result_page_or_empty(text, 'jinwen', '一')
    assert page['empty'] is True


def test_zero_result_requires_matching_query_head():
    with pytest.raises(ValueError, match='查询字段'):
        parse_result_page_or_empty(empty_html(head='天'), 'jinwen', '一')


def test_zero_result_does_not_hide_restricted_page():
    text = empty_html().replace('共搜尋到 0 字', 'Access Restricted 共搜尋到 0 字')
    with pytest.raises(ValueError, match='受限'):
        parse_result_page_or_empty(text, 'jinwen', '一')


def test_nonzero_result_still_uses_strict_parser():
    page = parse_result_page_or_empty(html(), 'jinwen', '一')
    assert 'empty' not in page
    assert page['source_record_id'] == '987'
    assert len(page['glyphs']) == 1
