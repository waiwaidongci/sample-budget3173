import csv, io, os
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from redis import Redis
from src.models.spillover import SpilloverSubmission, SpilloverCorrection, SpilloverRun
from src.services import studies
from src.services.spillover_io import parse_roster, parse_edges, parse_clicks, validate_correction
from src.services.spillover_algorithm import calculate
from src.services.audits import log
from src.utils.serializers import record, now, checksum

KINDS = ('roster', 'edges', 'clicks')

def _require_study(db, study_id):
    studies.require(db, study_id)

def _get_open(db, study_id, batch_code):
    sub = db.scalar(select(SpilloverSubmission).where(
        SpilloverSubmission.study_id == study_id, SpilloverSubmission.batch_code == batch_code))
    if not sub:
        raise HTTPException(404, '批次不存在，请先创建留白外溢批次')
    return sub

def _recompute_missing(sub):
    '''缺报点击只统计留白人员：已投者不参与留白比较，其点击不在封存必备范围。'''
    roster = sub.data.get('roster', {}).get('parsed') if sub.data.get('roster') else None
    clicks = sub.data.get('clicks', {}).get('parsed') if sub.data.get('clicks') else None
    if not roster:
        sub.missing_click_ids = []
    else:
        known = set(clicks or {})
        sub.missing_click_ids = [pid for pid, slot in roster.items()
                                 if slot == 'holdout' and pid not in known]
    flag_modified(sub, 'missing_click_ids')

def create_submission(db, data, user):
    _require_study(db, data.study_id)
    exists = db.scalar(select(SpilloverSubmission).where(
        SpilloverSubmission.study_id == data.study_id,
        SpilloverSubmission.batch_code == data.batch_code))
    if exists:
        raise HTTPException(409, '同计划下批次编号已存在')
    sub = SpilloverSubmission(study_id=data.study_id, batch_code=data.batch_code,
                              data={}, missing_click_ids=[], note=data.note,
                              created_by=user.email, created_at=now())
    db.add(sub); db.flush(); log(db, user, 'spillover.submission.create', f'{data.study_id}/{data.batch_code}'); db.commit()
    return record(sub)

def list_submissions(db, study_id):
    _require_study(db, study_id)
    return [record(x) for x in db.scalars(select(SpilloverSubmission)
            .where(SpilloverSubmission.study_id == study_id).order_by(SpilloverSubmission.id))]

def upload(db, data, user):
    if data.kind not in KINDS:
        raise HTTPException(422, '资料类型必须为 roster/edges/clicks 之一')
    sub = _get_open(db, data.study_id, data.batch_code)
    if sub.status == 'sealed':
        raise HTTPException(409, '批次已封存，资料不可改写；更正请走联系/点击更正通道')
    roster = sub.data.get('roster', {}).get('parsed')
    try:
        if data.kind == 'roster':
            parsed = parse_roster(data.content)
        elif data.kind == 'edges':
            if not roster:
                raise ValueError('请先补交原分派名单，再上传联系资料以核对人员范围')
            parsed = parse_edges(data.content, set(roster) if roster else None)
        else:
            if not roster:
                raise ValueError('请先补交原分派名单，再上传点击资料以核对人员范围')
            parsed = parse_clicks(data.content, set(roster))
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e))
    # 整份替换：重复补交以最新齐全版本为准，旧版本不进入封存
    sub.data[data.kind] = {'filename': data.filename, 'content': data.content, 'parsed': parsed}
    flag_modified(sub, 'data')
    _recompute_missing(sub)
    log(db, user, 'spillover.upload', f'{sub.id}/{data.kind}/{data.filename}')
    db.commit()
    return completeness(db, sub.id)

def completeness(db, submission_id):
    sub = db.get(SpilloverSubmission, submission_id)
    if not sub:
        raise HTTPException(404, '批次不存在')
    present = {k: bool(sub.data.get(k)) for k in KINDS}
    ready = all(present.values()) and not sub.missing_click_ids
    out = record(sub)
    out['files_present'] = present
    out['ready_to_seal'] = ready
    out['missing_click_ids'] = sub.missing_click_ids
    return out

def submit_correction(db, data, user):
    _require_study(db, data.study_id)
    sub = db.scalar(select(SpilloverSubmission).where(
        SpilloverSubmission.study_id == data.study_id,
        SpilloverSubmission.batch_code == data.batch_code))
    roster = sub.data.get('roster', {}).get('parsed') if sub else None
    try:
        clean = validate_correction(data.payload, roster)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e))
    sealed = bool(sub and sub.status == 'sealed')
    person_known = bool(roster and data.person_id in roster)
    # 更正本身始终独立留痕、独立封存（checksum），与批次状态解耦
    corr = SpilloverCorrection(
        study_id=data.study_id, submission_id=sub.id if sub else None,
        person_id=data.person_id, payload=clean, source_filename=data.source_filename,
        status='applied', created_by=user.email, created_at=now(), checksum='')
    corr.checksum = checksum({'person_id': corr.person_id, 'payload': clean,
                              'source_filename': corr.source_filename, 'created_at': corr.created_at})
    db.add(corr); db.flush()
    if sealed:
        corr.status = 'rejected_sealed'
        log(db, user, 'spillover.correction.rejected', f'{corr.id} 批次已封存，更正不并入封存依据')
    elif not sub:
        corr.status = 'rejected_sealed'
        log(db, user, 'spillover.correction.rejected', f'{corr.id} 批次不存在，更正仅独立留痕不并入')
    elif not person_known:
        corr.status = 'rejected_sealed'
        log(db, user, 'spillover.correction.rejected', f'{corr.id} 人员不在名单内，更正仅独立留痕不并入')
    else:
        _apply_correction(sub, data.person_id, clean)
        _recompute_missing(sub)
        log(db, user, 'spillover.correction.apply', f'{corr.id} 并入开放批次 {sub.id}')
    db.commit()
    return record(corr)

def _apply_correction(sub, person_id, clean):
    edge_bag = {tuple(e) for e in sub.data['edges']['parsed']} if sub.data.get('edges') else set()
    if 'edge_add' in clean:
        edge_bag.add(tuple(clean['edge_add']))
    if 'edge_remove' in clean:
        edge_bag.discard(tuple(clean['edge_remove']))
    if edge_bag or sub.data.get('edges'):
        sub.data.setdefault('edges', {'filename': '__corrections__', 'content': '', 'parsed': []})
        sub.data['edges']['parsed'] = sorted(edge_bag)
        sub.data['edges']['filename'] = sub.data['edges'].get('filename') or '__corrections__'
    if 'click' in clean:
        sub.data.setdefault('clicks', {'filename': '__corrections__', 'content': '', 'parsed': {}})
        sub.data['clicks']['parsed'][person_id] = clean['click']
    flag_modified(sub, 'data')

def list_corrections(db, study_id):
    _require_study(db, study_id)
    return [record(x) for x in db.scalars(select(SpilloverCorrection)
            .where(SpilloverCorrection.study_id == study_id).order_by(SpilloverCorrection.id))]

def _snapshot(sub):
    return {
        'batch_code': sub.batch_code,
        'roster': dict(sub.data['roster']['parsed']),
        'edges': [list(e) for e in sub.data['edges']['parsed']],
        'clicks': dict(sub.data['clicks']['parsed']),
        'sources': {k: sub.data[k]['filename'] for k in KINDS},
    }

def create_run(db, data, user):
    _require_study(db, data.study_id)
    sub = db.get(SpilloverSubmission, data.submission_id)
    if not sub or sub.study_id != data.study_id:
        raise HTTPException(404, '批次不存在')
    if data.parameters:
        raise HTTPException(422, '本方法为固定名额等概率分派，暂无可调节参数')
    state = completeness(db, sub.id)
    if not state['ready_to_seal']:
        missing = state['missing_click_ids']
        raise HTTPException(422, '三份资料未齐全（缺报点击不算零），拒绝封存：'
                                + ('缺报人员 ' + ','.join(missing[:10]) if missing else
                                   '缺少 ' + ','.join(k for k, v in state['files_present'].items() if not v)))
    snapshot = _snapshot(sub)
    digest = checksum(snapshot)
    run = SpilloverRun(study_id=data.study_id, submission_id=sub.id, name=data.name,
                       parameters={}, snapshot=snapshot, checksum=digest,
                       status='queued', created_at=now())
    db.add(run); db.flush()
    # 封存依据在首次运行时冻结；后续重跑读取同一快照，checksum 不变
    if sub.status != 'sealed':
        sub.status = 'sealed'; sub.sealed_at = now(); sub.sealed_run_id = run.id
        log(db, user, 'spillover.seal', f'{sub.id} -> run {run.id} sha256 {digest[:12]}')
    else:
        log(db, user, 'spillover.rerun', f'{sub.id} 重跑 run {run.id}，封存依据不变 {digest[:12]}')
    log(db, user, 'spillover.run.queue', str(run.id)); db.commit()
    Redis.from_url(os.environ['REDIS_URL']).rpush('spillover-queue', run.id)
    return record(run)

def process_run(db, run):
    '''worker 与测试共用的执行体；异常由调用方落库为 failed。'''
    if checksum(run.snapshot) != run.checksum:
        raise ValueError('输入快照校验失败')
    result = calculate(run.snapshot, run.parameters)
    result['input_sha256'] = run.checksum
    return result

def get_run(db, run_id):
    run = db.get(SpilloverRun, run_id)
    if not run:
        raise HTTPException(404, '运行不存在')
    return record(run)

def list_runs(db, study_id=None):
    stmt = select(SpilloverRun).order_by(SpilloverRun.id.desc())
    if study_id:
        stmt = stmt.where(SpilloverRun.study_id == study_id)
    return [record(x) for x in db.scalars(stmt)]

def export_run(db, run_id, user):
    r = get_run(db, run_id)
    if r['status'] != 'completed':
        raise HTTPException(409, '尚无完成结果')
    stream = io.StringIO(); w = csv.writer(stream)
    w.writerow(['运行编号', '封存SHA256', '指标', '值'])
    for k, v in r['result']['metrics'].items():
        w.writerow([run_id, r['checksum'], k, v])
    w.writerow([run_id, r['checksum'], '适用范围', r['result']['applicability']])
    w.writerow([run_id, r['checksum'], '方法边界', r['result']['caveat']])
    w.writerow([run_id, r['checksum'], '解释', r['result']['interpretation']])
    log(db, user, 'spillover.run.export', run_id); db.commit()
    return '\ufeff' + stream.getvalue()
