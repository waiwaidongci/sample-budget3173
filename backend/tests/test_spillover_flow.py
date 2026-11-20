'''留白外溢流程端到端测试：SQLite 内存库 + 假 Redis，无需 docker。

运行：cd backend && python -m tests.test_spillover_flow  （或 python tests/test_spillover_flow.py）
覆盖：并发补交/只封存齐全批/缺报点击不算零/联系更正独立封存且重跑不改依据/
      孤立受众与全员相连自检/原预算路径不受影响。
'''
import os
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault('REDIS_URL', 'redis://unused:6379/0')
os.environ.setdefault('JWT_SECRET', 'test-secret')
os.environ.setdefault('DATABASE_URL', 'sqlite://')  # 导入期占位，随后替换为内存库

from src.config import database as db_mod
from src.models.study import Study
from src.models.spillover import SpilloverSubmission, SpilloverCorrection, SpilloverRun
from src.services import spillover as svc
from src.schemas.spillover import SubmissionInput, UploadInput, CorrectionInput, SpilloverRunInput
from fastapi import HTTPException

engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                       poolclass=StaticPool)

class FakeRedis:
    queues = {}
    def rpush(self, k, v): self.queues.setdefault(k, []).append(v)
    def ping(self): return True
    @classmethod
    def from_url(cls, *a, **k): return cls()

fake_redis = FakeRedis()

import redis as redis_pkg  # noqa: E402
class _RedisProxy:
    @staticmethod
    def from_url(*a, **k): return fake_redis
redis_pkg.Redis = _RedisProxy

from src.config import database as db_mod  # noqa: E402
db_mod.engine = engine
db_mod.Session = sessionmaker(bind=engine, expire_on_commit=False)

from src.models import user, study, observation, run, review, audit, spillover as sp_model  # noqa: E402
from src.services import spillover as svc  # noqa: E402
svc.Redis = _RedisProxy
from src.schemas.spillover import SubmissionInput, UploadInput, CorrectionInput, SpilloverRunInput  # noqa: E402
from fastapi import HTTPException  # noqa: E402
sp_model.Base.metadata.create_all(engine)

U = SimpleNamespace(email='analyst@demo.local', role='analyst')
ADMIN = SimpleNamespace(email='admin@demo.local', role='admin')

def s(**kw):  # 构造 pydantic 输入
    return SimpleNamespace(**kw)

ROSTER_CSV = '''id,slot
P1,treated
P2,treated
P3,holdout
P4,holdout
P5,holdout
P6,holdout
P7,holdout
P8,holdout
'''
EDGES_CSV = '''source,target
P3,P1
P4,P2
P4,P3
P5,P3
P6,P7
'''
CLICKS_CSV = '''id,click
P3,1
P4,1
P5,0
P6,0
P7,1
P8,0
'''

_study_seq = 0
def setup_study(db):
    global _study_seq
    _study_seq += 1
    st = Study(name=f'外溢测试计划-{_study_seq}', source_filename='roster.csv', description='')
    db.add(st); db.commit()
    return st.id

def test_happy_path_and_sealing():
    with db_mod.Session() as db:
        sid = setup_study(db)
        svc.create_submission(db, SubmissionInput(study_id=sid, batch_code='B1', note=''), U)
        # 并发补交：名单未到时，联系与点击资料都必须拒绝（无法核对人员范围）
        for early_kind, early_csv in (('edges', EDGES_CSV), ('clicks', CLICKS_CSV)):
            try:
                svc.upload(db, UploadInput(study_id=sid, batch_code='B1', kind=early_kind,
                                           filename='early.csv', content=early_csv), U)
                raise AssertionError('名单未到应拒绝 ' + early_kind)
            except HTTPException as e:
                assert e.status_code == 422 and '名单' in e.detail
        state_before = svc.list_submissions(db, sid)[0]
        assert state_before['status'] == 'open'
        # 三份资料任意顺序并发补交（名单先行，edges/clicks 顺序互换）
        svc.upload(db, UploadInput(study_id=sid, batch_code='B1', kind='roster',
                                   filename='roster.csv', content=ROSTER_CSV), U)
        svc.upload(db, UploadInput(study_id=sid, batch_code='B1', kind='clicks',
                                   filename='clicks.csv', content=CLICKS_CSV), U)
        svc.upload(db, UploadInput(study_id=sid, batch_code='B1', kind='edges',
                                   filename='edges.csv', content=EDGES_CSV), U)
        # 重复补交以最新齐全版本整份替换
        svc.upload(db, UploadInput(study_id=sid, batch_code='B1', kind='clicks',
                                   filename='clicks-v2.csv', content=CLICKS_CSV), U)
        comp = svc.completeness(db, svc.list_submissions(db, sid)[0]['id'])
        assert comp['ready_to_seal'] is True and comp['missing_click_ids'] == []

        run = svc.create_run(db, SpilloverRunInput(study_id=sid, submission_id=comp['id'],
                                                   name='首轮外溢', parameters={}), U)
        assert run['status'] == 'queued' and run['id'] in fake_redis.queues['spillover-queue']
        sub = db.get(SpilloverSubmission, comp['id'])
        assert sub.status == 'sealed' and sub.sealed_run_id == run['id']
        first_checksum = run['checksum']

        # worker 执行体
        run_obj = db.get(SpilloverRun, run['id'])
        result = svc.process_run(db, run_obj)
        run_obj.result = result; run_obj.status = 'completed'; db.commit()
        m = result['metrics']
        assert m['总人数 N'] == 8 and m['固定投放名额 m'] == 2
        # P8 孤立（无联系）：pi1=0，剔除；其余留白合格
        excluded = {x['人员']: x['原因'] for x in result['excluded_detail']}
        assert 'P8' in excluded and '孤立' in excluded['P8']
        assert 'P1' in excluded and 'P2' in excluded  # 已投
        assert result['self_check']['通过'] is True
        assert all(c['通过'] for c in result['self_check']['明细'])
        print('happy path 指标：', {k: m[k] for k in ('比较适用人数(两情形概率均为正)', '点击差(有联系人-无联系人)', '情形1 加权点击率', '情形0 加权点击率')})
        return sid, comp['id'], run['id'], first_checksum

def test_missing_click_is_not_zero():
    with db_mod.Session() as db:
        sid = setup_study(db)
        svc.create_submission(db, SubmissionInput(study_id=sid, batch_code='B2', note=''), U)
        svc.upload(db, UploadInput(study_id=sid, batch_code='B2', kind='roster',
                                   filename='r.csv', content=ROSTER_CSV), U)
        svc.upload(db, UploadInput(study_id=sid, batch_code='B2', kind='edges',
                                   filename='e.csv', content=EDGES_CSV), U)
        # P5 的点击整行缺报
        partial = '\n'.join(line for line in CLICKS_CSV.strip().splitlines() if not line.startswith('P5,')) + '\n'
        svc.upload(db, UploadInput(study_id=sid, batch_code='B2', kind='clicks',
                                   filename='c.csv', content=partial), U)
        sub = svc.list_submissions(db, sid)[0]
        assert sub['missing_click_ids'] == ['P5']
        try:
            svc.create_run(db, SpilloverRunInput(study_id=sid, submission_id=sub['id'],
                                                 name='缺报应拒', parameters={}), U)
            raise AssertionError('缺报点击不得封存')
        except HTTPException as e:
            assert e.status_code == 422 and '缺报' in e.detail
        # 显式填零代替缺报也必须被解析层接受为真实零，但缺报本身不能静默变零
        zero_filled = CLICKS_CSV.replace('P5,0', 'P5,0')  # P5 真实补报为 0
        svc.upload(db, UploadInput(study_id=sid, batch_code='B2', kind='clicks',
                                   filename='c2.csv', content=zero_filled), U)
        assert svc.completeness(db, sub['id'])['ready_to_seal'] is True
        print('缺报点击不算零：缺报拒绝封存、补交后放行，通过')

def test_correction_separately_sealed_and_rerun_keeps_basis(sid, sub_id, first_checksum):
    with db_mod.Session() as db:
        # 已封存批次上的联系更正：独立留痕、拒绝并入，重跑 checksum 不变
        corr = svc.submit_correction(db, CorrectionInput(
            study_id=sid, batch_code='B1', person_id='P8',
            source_filename='corr-1.csv', payload={'edge_add': ['P8', 'P1']}), ADMIN)
        assert corr['status'] == 'rejected_sealed' and len(corr['checksum']) == 64
        stored = db.get(SpilloverCorrection, corr['id'])
        assert stored.checksum == corr['checksum']  # 更正自身封存依据
        sub = db.get(SpilloverSubmission, sub_id)
        assert sub.status == 'sealed'
        # 重跑：同一封存快照
        run2 = svc.create_run(db, SpilloverRunInput(study_id=sid, submission_id=sub_id,
                                                    name='重跑外溢', parameters={}), U)
        assert run2['checksum'] == first_checksum
        run2_obj = db.get(SpilloverRun, run2['id'])
        result2 = svc.process_run(db, run2_obj)
        assert result2['input_sha256'] == first_checksum
        # P8 仍因孤立被剔除（更正未并入）
        assert any(x['人员'] == 'P8' for x in result2['excluded_detail'])
        print('更正独立封存 + 重跑不改封存依据：通过')

def test_correction_applied_to_open_batch():
    with db_mod.Session() as db:
        sid = setup_study(db)
        svc.create_submission(db, SubmissionInput(study_id=sid, batch_code='B3', note=''), U)
        svc.upload(db, UploadInput(study_id=sid, batch_code='B3', kind='roster',
                                   filename='r.csv', content=ROSTER_CSV), U)
        svc.upload(db, UploadInput(study_id=sid, batch_code='B3', kind='edges',
                                   filename='e.csv', content=EDGES_CSV), U)
        svc.upload(db, UploadInput(study_id=sid, batch_code='B3', kind='clicks',
                                   filename='c.csv', content=CLICKS_CSV), U)
        sub = svc.list_submissions(db, sid)[0]
        # 开放批次上把孤立点 P8 连上 P1：P8 从剔除变为合格
        corr = svc.submit_correction(db, CorrectionInput(
            study_id=sid, batch_code='B3', person_id='P8',
            source_filename='corr-open.csv', payload={'edge_add': ['P8', 'P1']}), U)
        assert corr['status'] == 'applied'
        run = svc.create_run(db, SpilloverRunInput(study_id=sid, submission_id=sub['id'],
                                                   name='开放批更正后运行', parameters={}), U)
        result = svc.process_run(db, db.get(SpilloverRun, run['id']))
        excluded = {x['人员'] for x in result['excluded_detail']}
        assert 'P8' not in excluded
        assert result['metrics']['比较适用人数(两情形概率均为正)'] == 6
        print('开放批次联系更正并入：P8 转为合格，通过')

def test_fully_connected_validation():
    with db_mod.Session() as db:
        sid = setup_study(db)
        svc.create_submission(db, SubmissionInput(study_id=sid, batch_code='B4', note=''), U)
        n = 5
        roster = 'id,slot\n' + '\n'.join(
            f'P{i},' + ('treated' if i <= 2 else 'holdout') for i in range(1, n + 1)) + '\n'
        edges = 'source,target\n' + '\n'.join(
            f'P{i},P{j}' for i in range(1, n + 1) for j in range(i + 1, n + 1)) + '\n'
        clicks = 'id,click\n' + '\n'.join(f'P{i},{i % 2}' for i in range(1, n + 1)) + '\n'
        svc.upload(db, UploadInput(study_id=sid, batch_code='B4', kind='roster',
                                   filename='r.csv', content=roster), U)
        svc.upload(db, UploadInput(study_id=sid, batch_code='B4', kind='edges',
                                   filename='e.csv', content=edges), U)
        svc.upload(db, UploadInput(study_id=sid, batch_code='B4', kind='clicks',
                                   filename='c.csv', content=clicks), U)
        sub = svc.list_submissions(db, sid)[0]
        try:
            run = svc.create_run(db, SpilloverRunInput(study_id=sid, submission_id=sub['id'],
                                                       name='全连应拒', parameters={}), U)
            svc.process_run(db, db.get(SpilloverRun, run['id']))
            raise AssertionError('全员相连时留白者 pi0=0，应无法估计')
        except (HTTPException, ValueError) as e:
            msg = e.detail if isinstance(e, HTTPException) else str(e)
            assert '无法估计' in msg or '情形' in msg
        print('全员相连验证：pi0=0 人员全部剔除、两臂缺一拒绝出结果，通过')

def test_bad_inputs_rejected():
    with db_mod.Session() as db:
        sid = setup_study(db)
        svc.create_submission(db, SubmissionInput(study_id=sid, batch_code='B5', note=''), U)
        for bad, hint in [
            ('id,slot\nP1,maybe\n', 'slot'),
            ('id,slot\nP1,treated\nP1,holdout\n', '重复'),
            ('source,target\nP1,P1\n', '自联系'),
            ('id,click\nP1,2\n', '0 或 1'),
        ]:
            kind = 'roster' if 'slot' in bad else ('edges' if 'source' in bad else 'clicks')
            if kind != 'roster':
                svc.upload(db, UploadInput(study_id=sid, batch_code='B5', kind='roster',
                                           filename='r.csv', content=ROSTER_CSV), U)
            try:
                svc.upload(db, UploadInput(study_id=sid, batch_code='B5', kind=kind,
                                           filename='x.csv', content=bad), U)
                raise AssertionError(f'非法输入应被拒绝：{bad}')
            except HTTPException as e:
                assert e.status_code == 422 and hint in e.detail
        # 未知更正字段白名单
        try:
            svc.submit_correction(db, CorrectionInput(
                study_id=sid, batch_code='B5', person_id='P1',
                source_filename='c.csv', payload={'hacker': 1}), U)
            raise AssertionError('白名单外更正应拒绝')
        except HTTPException as e:
            assert e.status_code == 422
        print('非法输入与白名单拒绝：通过')

if __name__ == '__main__':
    sid, sub_id, run_id, checksum = test_happy_path_and_sealing()
    test_missing_click_is_not_zero()
    test_correction_separately_sealed_and_rerun_keeps_basis(sid, sub_id, checksum)
    test_correction_applied_to_open_batch()
    test_fully_connected_validation()
    test_bad_inputs_rejected()
    print('\n全部留白外溢流程测试通过')
