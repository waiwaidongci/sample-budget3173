import os,json,logging
from pathlib import Path
from redis import Redis
from sqlalchemy import select
from src.config.database import Session
from src.models.run import Run
from src.models.spillover import SpilloverRun
from src.models import user,study,observation,review,audit
from src.services.algorithm import calculate
from src.services.spillover import process_run
from src.utils.serializers import checksum
redis=Redis.from_url(os.environ['REDIS_URL'])
ARTIFACT_DIR=Path(os.environ.get('ARTIFACT_DIR','/app/artifacts'))
ARTIFACT_DIR.mkdir(parents=True,exist_ok=True)
# Recover jobs interrupted after dequeue. A project runs exactly one worker.
with Session() as db:
    for queue_name,model in (('analysis-queue',Run),('spillover-queue',SpilloverRun)):
        try:
            pending=list(db.scalars(select(model).where(model.status.in_(['queued','running']))))
        except Exception:
            logging.exception('recovery scan skipped for %s',queue_name);pending=[]
        for job in pending: redis.rpush(queue_name,job.id)

def _handle_analysis(db,run):
    if checksum(run.snapshot)!=run.checksum: raise ValueError('输入快照校验失败')
    result=calculate(run.snapshot,run.parameters)
    result['input_sha256']=run.checksum
    run.result=result;run.status='completed'
    (ARTIFACT_DIR/f'run-{run.id}.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False))

def _handle_spillover(db,run):
    result=process_run(db,run)
    run.result=result;run.status='completed'
    (ARTIFACT_DIR/f'spillover-run-{run.id}.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False))

QUEUES=(('analysis-queue',Run,_handle_analysis),('spillover-queue',SpilloverRun,_handle_spillover))
while True:
    Path('/tmp/worker-heartbeat').touch()
    job=redis.blpop([name for name,_,_ in QUEUES],timeout=2)
    if not job: continue
    queue_name,raw=job
    handler=next(h for name,_,h in QUEUES if name==queue_name.encode() or name==queue_name)
    model=next(m for name,m,_ in QUEUES if name==queue_name.encode() or name==queue_name)
    id=int(raw)
    with Session() as db:
        run=db.get(model,id)
        if not run or run.status in ('completed','failed'): continue
        run.status='running';db.commit()
        try:
            handler(db,run)
        except Exception as e:
            logging.exception('analysis failed');run.status='failed';run.error=str(e)
        db.commit()
