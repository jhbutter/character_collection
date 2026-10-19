import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import requests

from .common import PROJECT, is_stop_error, save_json
from .cross_source import attach_images, collect_result, process_reference
from http_driver import HTTPDriver, form_fields
from read_font import check_page, preflight
from hanzi_evolution.adapters import RecordInput, SourceInput
from hanzi_evolution.db import open_db
from hanzi_evolution.store import export_rows, import_records, now, report, write_directory_export
from hanzi_evolution.xiaoxue import (COLLECTION_NAMES, parse_result_page,
    parse_result_page_or_empty, select_missing_styles)

CHARACTERS = '一上旁下示彔元天吏帝'


def result_pages(driver, folder, collection, character, allow_empty=False):
    path = folder / 'pages' / collection / f'U{ord(character):04X}.json'
    if path.exists():
        pages = json.loads(path.read_text())
    else:
        old = PROJECT / 'data/batches/cross_source_mvp/records' / collection / f'U{ord(character):04X}.jsonl'
        if old.exists():
            pages = json.loads(old.read_text())['pages']
        else:
            template = PROJECT / 'data/raw/cross_source_audit' / f'{collection}.html'
            soup = BeautifulSoup(template.read_text(), 'lxml')
            form = soup.find('form', id='BasicFrom')
            if form is None or form.get('method', '').lower() != 'post':
                raise ValueError('未找到已审计的POST查询表单')
            fields = form_fields(form)
            fields['EudcFontChar'] = character
            url = urljoin(f'https://xiaoxue.iis.sinica.edu.tw/{collection}/', form['action'])
            cached_html = None
            log = folder / 'requests.jsonl'
            if log.exists():
                for line in reversed(log.read_text().splitlines()):
                    entry = json.loads(line)
                    values = entry.get('fields') or {}
                    if (entry['url'] == url and values.get('EudcFontChar') == character
                            and not values.get('PageTo') and entry['status_code'] == 200):
                        cached = Path(entry['path'])
                        if hashlib.sha256(cached.read_bytes()).hexdigest() != entry['sha256']:
                            raise ValueError('查询响应缓存哈希不一致')
                        cached_html = cached.read_text(encoding='utf-8-sig')
                        break
            if cached_html is None:
                driver.request('POST', url, fields)
                cached_html = driver.page_source
            _, _, pages = collect_result(driver, collection, character, max_pages=20,
                                         html=cached_html, allow_empty=allow_empty)
        save_json(path, pages)
    glyphs = []
    first = None
    parse = parse_result_page_or_empty if allow_empty else parse_result_page
    for i, page in enumerate(pages, 1):
        if hashlib.sha256(page['html'].encode()).hexdigest() != page['sha256']:
            raise ValueError('缓存页面哈希不一致')
        parsed = parse(page['html'], collection, character, i)
        if first is None:
            first = parsed
        elif any(parsed[k] != first[k] for k in ('source_record_id', 'expected_glyph_count', 'page_count')):
            raise ValueError('缓存分页来源或数量不一致')
        glyphs.extend(parsed['glyphs'])
    if first.get('empty'):
        return first, [], pages
    if len(pages) != first['page_count'] or len(glyphs) != first['expected_glyph_count']:
        raise ValueError('分页结果不完整')
    if len({g.local_key for g in glyphs}) != len(glyphs):
        raise ValueError('跨页重复字形')
    return first, glyphs, pages


def run(args):
    folder = args.folder.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    engine = open_db(PROJECT / 'data/hanzi.sqlite')
    state = {'started_at': now(), 'status': 'running', 'downloaded_this_run': 0, 'records': []}
    driver = None
    try:
        query_args = SimpleNamespace(interval=7, start_idx=1,
            user_agent='HanziResearchMVP/0.1 (+https://github.com/EvaWang/xiaoxue_crawler)',
            target_url='https://xiaoxue.iis.sinica.edu.tw/jinwen/?kaiOrder=%d')
        preflight(query_args, folder)
        driver = HTTPDriver(query_args, folder, check_page)
        known_images = {r['original_url']: r['image_path'] for r in export_rows(engine, True) if r['image_path']}
        for character in CHARACTERS:
            for collection in COLLECTION_NAMES:
                item = {'character': character, 'source': collection}
                try:
                    first, glyphs, pages = result_pages(driver, folder, collection, character)
                    record_path = folder / 'records' / collection / f'U{ord(character):04X}.jsonl'
                    source = SourceInput.model_validate_json((PROJECT / f'config/xiaoxue_{collection}.json').read_text())
                    if record_path.exists():
                        raw = record_path.read_bytes()
                        packet = json.loads(raw)
                        record = RecordInput.model_validate(packet['normalized'])
                    else:
                        selected = select_missing_styles(glyphs, export_rows(engine, True))
                        selected = attach_images(selected, driver, folder, known_images, state, args)
                        record = RecordInput(local_id=first['source_record_id'] + ':fill5-v1',
                            raw_head=first['source_record_id'],
                            source_url=f'https://xiaoxue.iis.sinica.edu.tw/{collection}/', glyphs=selected)
                        packet = {'source': collection, 'query_character': character,
                            'source_record_id': first['source_record_id'],
                            'sampling': {'policy': 'global_character_style_max5', 'available': len(glyphs),
                                         'selected': len(selected)},
                            'pages': pages, 'normalized': record.model_dump()}
                        raw = (json.dumps(packet, ensure_ascii=False, sort_keys=True) + '\n').encode()
                        record_path.parent.mkdir(parents=True, exist_ok=True)
                        record_path.write_bytes(raw)
                    result = import_records(engine, PROJECT / 'data', source, [record], raw,
                                            'xiaoxue-fill5-v1', PROJECT / 'data')
                    if first['modern_reference']:
                        links = {character: {'yanbian': f'https://xiaoxue.iis.sinica.edu.tw/{collection}/'}}
                        process_reference(engine, driver, character, first, packet, links, folder, known_images, state, args)
                    item.update(status='complete', available=packet['sampling']['available'],
                        selected=len(record.glyphs), styles=dict(Counter(g.script_style for g in record.glyphs)), **result)
                except (RuntimeError, ValueError, OSError, requests.RequestException) as error:
                    item.update(status='failed', error=str(error), error_type=type(error).__name__)
                    if is_stop_error(error):
                        state['status'] = 'blocked'
                    elif '达到MVP图片预算' in str(error):
                        state['status'] = 'budget_reached'
                state['records'].append(item)
                save_json(folder / 'status.json', state)
                print(json.dumps(item, ensure_ascii=False), flush=True)
                if state['status'] != 'running':
                    break
            if state['status'] != 'running':
                break
        if state['status'] == 'running':
            state['status'] = 'partial' if any(r['status'] == 'failed' for r in state['records']) else 'finished'
    except (RuntimeError, ValueError, OSError, requests.RequestException) as error:
        state.update(status='blocked' if is_stop_error(error) else 'failed', error=str(error))
    finally:
        if driver:
            driver.quit()
        state['finished_at'] = now()
        state['quality'] = report(engine, PROJECT / 'data')
        save_json(folder / 'status.json', state)
        save_json(PROJECT / 'reports/complete_ten.json', state)
        if state['status'] in {'finished', 'partial', 'budget_reached'}:
            state['export'] = write_directory_export(export_rows(engine, True), PROJECT / 'data', args.output, True)
            save_json(folder / 'status.json', state)
        engine.dispose()
    print(json.dumps({'status': state['status'], 'downloaded': state['downloaded_this_run']}, ensure_ascii=False), flush=True)
    return 0 if state['status'] == 'finished' else 2


def main():
    parser = argparse.ArgumentParser(description='补齐当前10字的已接通来源，每字每字体最多5张')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--max-images', type=int, default=100)
    parser.add_argument('--folder', type=Path, default=PROJECT / 'data/batches/complete_ten')
    parser.add_argument('--output', type=Path, default=PROJECT / 'data/dataset')
    args = parser.parse_args()
    if not 1 <= args.max_images <= 100:
        parser.error('每批最多100张新图')
    if not args.execute:
        print(json.dumps({'status': 'dry_run', 'characters': CHARACTERS}, ensure_ascii=False))
        return 0
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
