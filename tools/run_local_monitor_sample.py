"""Collect a saved monitoring request with the local browser adapters.

Uses existing session copies, reuses verified first-question evidence, and
persists progress in the unified report store for the running web console.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import importlib.util
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--session-dir', required=True)
    parser.add_argument('--gap', type=float, default=10)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--resume-job')
    parser.add_argument('--only', nargs='+')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    input_path = Path(args.input).resolve()
    output = input_path.parent
    request = json.loads(input_path.read_text(encoding='utf-8-sig'))
    engine_ids = request['engines']
    actual_ids = {engine: 'qwen' if engine == 'qwen_browser' else engine for engine in engine_ids}
    selected = args.only or engine_ids
    if any(engine not in engine_ids for engine in selected):
        raise ValueError('Selected engine is not in the saved request')
    os.environ.update({
        'BROWSER_SESSION_DIR': str(Path(args.session_dir).resolve()),
        'ENGINE_LIST': ','.join(actual_ids[e] for e in selected),
        'MAX_CONCURRENT_QUERIES': str(len(engine_ids)),
        'ENGINE_SEARCH_TIMEOUT': str(args.timeout),
        'PLAYWRIGHT_HEADLESS': '1',
        'GEO_BROWSER_BACKGROUND': '1',
        'DOUBAO_HEADED': '1',
    })
    sys.path.insert(0, str(root / 'backend'))
    sys.path.insert(0, str(root / 'services' / 'browser-service'))
    # Load the report module directly; collection does not need web auth/DB setup.
    spec = importlib.util.spec_from_file_location('geo_unified_local_sample', root / 'backend/geo/api/unified.py')
    unified = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = unified
    spec.loader.exec_module(unified)
    from app import main as service
    from app.models import SearchRequest
    from app.browser import close_browser

    if args.resume_job and not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', args.resume_job):
        raise ValueError('Invalid job id')
    job_id = args.resume_job or ('dugen-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6])
    total = len(request['queries']) * len(engine_ids)
    created = datetime.now(timezone.utc).isoformat()
    job = dict(request, id=job_id, status='running', progress=0, results=[], summary={},
               created_at=created, started_at=created, analysis_status='pending',
               expected_results=total, execution='local browser service adapters')
    report_path = root / 'reports' / 'unified' / (job_id + '.json')
    report_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path = output / 'collection-progress.json'
    engine_progress = {e: {'completed': 0, 'successful': 0, 'blocked': None} for e in engine_ids}
    if args.resume_job:
        job = json.loads(report_path.read_text(encoding='utf-8-sig'))
        if job['brand'] != request['brand'] or job['queries'] != request['queries']:
            raise ValueError('Resume request does not match saved job')
        previous = json.loads(progress_path.read_text(encoding='utf-8')) if progress_path.exists() else {}
        for engine in engine_ids:
            existing = [r for r in job['results'] if r['engine'] == engine]
            engine_progress[engine] = {'completed':len(existing),
                'successful':sum(bool(r.get('answer')) and not r.get('error') for r in existing),
                'blocked':None if engine in selected else previous.get('engines',{}).get(engine,{}).get('blocked')}
        for engine in selected:
            if any(r['engine']==engine and re.search(r'captcha|验证码|安全验证',str(r.get('error') or ''),re.I) for r in job['results']):
                raise RuntimeError('Manual verification is required before resuming '+engine)
        job.update(status='running', analysis_status='pending', resume_started_at=created)

    def persist() -> None:
        job['progress'] = int(len(job['results']) / total * 100)
        job['summary'] = unified._summarise(job)
        temporary = report_path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, report_path)
        state = {'job_id': job_id, 'status': job['status'], 'completed': len(job['results']),
                 'total': total, 'report_path': str(report_path), 'engines': engine_progress,
                 'updated_at': datetime.now(timezone.utc).isoformat()}
        progress_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

    def add_result(engine: str, number: int, raw: dict) -> None:
        result = dict(raw)
        result.update(engine=engine, query=request['queries'][number-1],
                      provider_name=unified.BROWSER_ENGINES[engine][0], transport='browser',
                      question_number=number, analysis_status='pending')
        answer = result.get('answer') or ''
        result['target_mentioned'] = request['brand'].casefold() in answer.casefold()
        # Ranking requires entity extraction; do not assign rank 1 just because
        # no competitor list was supplied.
        result['target_rank'] = None
        result['mentioned_names'] = []
        lookup = {unified._canonical_url(u): u for u in request['article_urls']}
        result['cited_articles'] = [
            {'article_url': lookup[unified._canonical_url(c.get('url', ''))], 'citation': c}
            for c in result.get('citations', [])
            if isinstance(c, dict) and unified._canonical_url(c.get('url', '')) in lookup
        ]
        state = engine_progress[engine]
        previous = next((r for r in job['results'] if r['engine']==engine and r['question_number']==number),None)
        if previous is not None:
            history = output / 'attempt-history'
            history.mkdir(exist_ok=True)
            historical_path = history / f'{actual_ids[engine]}-q{number:02d}-{time.time_ns()}.json'
            historical_path.write_text(json.dumps(previous,ensure_ascii=False,indent=2),encoding='utf-8')
            result['previous_attempt_file'] = str(historical_path)
            state['completed'] -= 1
            state['successful'] -= bool(previous.get('answer')) and not previous.get('error')
            job['results'].remove(previous)
        job['results'].append(result)
        job['results'].sort(key=lambda x: (x['question_number'], engine_ids.index(x['engine'])))
        state['completed'] += 1
        state['successful'] += bool(answer.strip()) and not result.get('error')
        persist()
        print(json.dumps({'engine':engine,'question':number,'answer_length':len(answer),
                          'error':result.get('error'),'progress':job['progress']},ensure_ascii=False),flush=True)

    async def collect_engine(engine: str) -> None:
        actual = actual_ids[engine]
        blocked = None
        failures = 0
        for number, query in enumerate(request['queries'], 1):
            if blocked:
                add_result(engine, number, {'answer':'','citations':[],
                    'error':'not_attempted_after_platform_block: ' + blocked,
                    'not_attempted':True})
                continue
            cache = output / f'{actual}-q{number:02d}.json'
            if args.resume_job:
                previous=next((r for r in job['results'] if r['engine']==engine and r['question_number']==number),None)
                if previous and previous.get('answer') and not previous.get('error'):
                    continue
                if cache.is_file():
                    history=output/'attempt-history'
                    history.mkdir(exist_ok=True)
                    cache.rename(history/f'{actual}-q{number:02d}-raw-{time.time_ns()}.json')
            if cache.is_file():
                raw = json.loads(cache.read_text(encoding='utf-8-sig'))
                if raw.get('query') != query:
                    raise RuntimeError('Cached query differs from requested question')
                add_result(engine, number, raw)
                continue
            if number > 1 and args.gap:
                await asyncio.sleep(args.gap)
            started = time.monotonic()
            try:
                response = await service.search(SearchRequest(engine=actual, query=query))
                raw = response.model_dump(mode='json')
            except Exception as exc:
                raw = {'engine':actual,'query':query,'answer':'','citations':[],
                       'error':type(exc).__name__ + ': ' + str(exc)[:1200]}
            raw['collected_at'] = datetime.now(timezone.utc).isoformat()
            raw['sample_elapsed_seconds'] = round(time.monotonic()-started, 1)
            cache.write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf-8')
            error = str(raw.get('error') or '')
            failures = failures + 1 if error or not (raw.get('answer') or '').strip() else 0
            if re.search(r'captcha|login_lost|challenge|forbidden|\b403\b|验证码|安全验证|账号异常|请先登录|登录失效',error,re.I) or failures >= 2:
                blocked = error or 'two_consecutive_empty_answers'
                engine_progress[engine]['blocked'] = blocked
            add_result(engine, number, raw)
            if args.resume_job and error:
                engine_progress[engine]['blocked']=error
                break

    async def run() -> None:
        service._load_adapters()
        persist()
        try:
            await asyncio.gather(*(collect_engine(engine) for engine in selected))
            job['status'] = 'partial' if any(r.get('error') for r in job['results']) else 'completed'
            job['finished_at'] = datetime.now(timezone.utc).isoformat()
        except BaseException as exc:
            job['status'] = 'interrupted'
            job['execution_error'] = type(exc).__name__
            raise
        finally:
            await close_browser()
            persist()
        print('COLLECTION_FINISHED', str(report_path), flush=True)

    asyncio.run(run())


if __name__ == '__main__':
    main()