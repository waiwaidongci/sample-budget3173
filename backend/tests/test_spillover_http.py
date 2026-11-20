'''HTTP 层端到端：FastAPI TestClient + SQLite 内存库 + 假 Redis，无需 docker。

运行：cd backend && PYTHONPATH=. python -m tests.test_spillover_http
'''
import os
os.environ.setdefault('REDIS_URL', 'redis://unused:6379/0')
os.environ.setdefault('JWT_SECRET', 'test-secret')
os.environ.setdefault('DATABASE_URL', 'sqlite://')

import redis as redis_pkg
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

class FakeRedis:
    store = {}
    def rpush(self, k, v): self.store.setdefault(k, []).append(v)
    def incr(self, k): self.store[k] = self.store.get(k, 0) + 1; return self.store[k]
    def expire(self, k, s): return True
    def ping(self): return True
    @classmethod
    def from_url(cls, *a, **k): return cls()
redis_pkg.Redis = FakeRedis

from fastapi.testclient import TestClient  # noqa: E402
from src.config import database as db_mod  # noqa: E402
engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
db_mod.engine = engine
db_mod.Session = sessionmaker(bind=engine, expire_on_commit=False)

from src.services import spillover as svc  # noqa: E402
svc.Redis = FakeRedis
from src.main import app  # noqa: E402
from src.models.user import User  # noqa: E402
from src.models import spillover as sp_model  # noqa: E402
from src.utils.security import hash_password  # noqa: E402

sp_model.Base.metadata.create_all(engine)
with db_mod.Session() as db:
    for role in ('admin', 'analyst', 'viewer'):
        db.add(User(email=f'{role}@demo.local', role=role, password_hash=hash_password('Research2026!')))
    db.commit()

client = TestClient(app)

def login(role):
    r = client.post('/auth/login', json={'email': f'{role}@demo.local', 'password': 'Research2026!'})
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['token']}

ROSTER = 'id,slot\nP1,treated\nP2,treated\nP3,holdout\nP4,holdout\nP5,holdout\nP6,holdout\n'
EDGES = 'source,target\nP3,P1\nP4,P2\nP4,P3\nP6,P5\n'
CLICKS = 'id,click\nP3,1\nP4,0\nP5,0\nP6,1\n'

def main():
    admin = login('admin'); analyst = login('analyst'); viewer = login('viewer')
    # 未认证拒绝
    assert client.get('/spillover/runs').status_code == 401
    # viewer 只读：写操作 403
    r = client.post('/spillover/submissions', headers=viewer,
                    json={'study_id': 1, 'batch_code': 'X'})
    assert r.status_code == 403
    # 需要先有触达计划
    r = client.post('/studies', headers=analyst,
                    json={'name': '外溢HTTP计划', 'source_filename': 'roster.csv', 'description': ''})
    assert r.status_code == 200, r.text
    sid = r.json()['id']
    # 创建批次
    r = client.post('/spillover/submissions', headers=analyst,
                    json={'study_id': sid, 'batch_code': 'HB1', 'note': ''})
    assert r.status_code == 200, r.text
    sub_id = r.json()['id']
    # 重复批次 409
    r = client.post('/spillover/submissions', headers=analyst,
                    json={'study_id': sid, 'batch_code': 'HB1'})
    assert r.status_code == 409
    # 三份资料并发补交
    for kind, content in (('roster', ROSTER), ('edges', EDGES), ('clicks', CLICKS)):
        r = client.post('/spillover/uploads', headers=analyst,
                        json={'study_id': sid, 'batch_code': 'HB1', 'kind': kind,
                              'filename': f'{kind}.csv', 'content': content})
        assert r.status_code == 200, (kind, r.text)
    state = client.get(f'/spillover/submissions/{sub_id}/completeness', headers=analyst).json()
    assert state['ready_to_seal'] is True
    # 非法资料 422
    r = client.post('/spillover/uploads', headers=analyst,
                    json={'study_id': sid, 'batch_code': 'HB1', 'kind': 'clicks',
                          'filename': 'bad.csv', 'content': 'id,click\nP3,9\n'})
    assert r.status_code == 422
    # 封存并运行
    r = client.post('/spillover/runs', headers=analyst,
                    json={'study_id': sid, 'submission_id': sub_id, 'name': 'HTTP外溢运行', 'parameters': {}})
    assert r.status_code == 200, r.text
    run_id = r.json()['id']; checksum = r.json()['checksum']
    # 同步执行（worker 队列在假 Redis 中，直接调用服务执行体模拟 worker）
    with db_mod.Session() as db:
        run_obj = svc.get_run(db, run_id)
        run_obj = db.get(sp_model.SpilloverRun, run_id)
        result = svc.process_run(db, run_obj)
        run_obj.result = result; run_obj.status = 'completed'; db.commit()
    r = client.get(f'/spillover/runs/{run_id}', headers=viewer)
    assert r.status_code == 200 and r.json()['status'] == 'completed'
    body = r.json()['result']
    assert body['self_check']['通过'] is True
    assert '适用' in body['applicability'] and body['metrics']['比较适用人数(两情形概率均为正)'] == 4
    # 已封存后上传被拒
    r = client.post('/spillover/uploads', headers=analyst,
                    json={'study_id': sid, 'batch_code': 'HB1', 'kind': 'edges',
                          'filename': 'e2.csv', 'content': EDGES})
    assert r.status_code == 409
    # 更正独立封存：admin 提交，状态 rejected_sealed，但留痕可查
    r = client.post('/spillover/corrections', headers=admin,
                    json={'study_id': sid, 'batch_code': 'HB1', 'person_id': 'P5',
                          'source_filename': 'c.csv', 'payload': {'edge_add': ['P5', 'P1']}})
    assert r.status_code == 200 and r.json()['status'] == 'rejected_sealed'
    corrs = client.get(f'/spillover/studies/{sid}/corrections', headers=viewer).json()
    assert len(corrs) == 1 and len(corrs[0]['checksum']) == 64
    # 重跑 checksum 不变
    r = client.post('/spillover/runs', headers=analyst,
                    json={'study_id': sid, 'submission_id': sub_id, 'name': 'HTTP重跑', 'parameters': {}})
    assert r.status_code == 200 and r.json()['checksum'] == checksum
    # CSV 导出（viewer 也可，已完成即可）
    r = client.get(f'/spillover/runs/{run_id}/export', headers=viewer)
    assert r.status_code == 200 and 'text/csv' in r.headers['content-type']
    assert '封存SHA256' in r.text and '适用范围' in r.text
    # 审计留痕包含外溢动作
    audits = client.get('/audits', headers=admin).json()
    actions = {a['action'] for a in audits}
    assert {'spillover.submission.create', 'spillover.upload', 'spillover.seal',
            'spillover.run.queue', 'spillover.correction.rejected'} <= actions
    print('HTTP 端到端全部通过：认证/权限/并发补交/封存/更正/重跑/导出/审计')

if __name__ == '__main__':
    main()
