import json
import numpy as np
from sqlalchemy import select,func
from src.config.database import Base,engine,Session
from src.config.domain import DOMAIN
from src.models.user import User
from src.models.study import Study
from src.models.observation import Observation
from src.models import run,review,audit
from src.models.spillover import SpilloverSubmission,SpilloverCorrection,SpilloverRun
from src.services.spillover_io import parse_roster,parse_edges,parse_clicks
from src.utils.security import hash_password
from src.utils.serializers import now

def seed():
    Base.metadata.create_all(engine)
    rng=np.random.default_rng(42)
    i=DOMAIN['index']
    with Session() as db:
        for role in ('admin','analyst','viewer'):
            email=role+'@demo.local'
            if not db.scalar(select(User).where(User.email==email)): db.add(User(email=email,role=role,password_hash=hash_password('Research2026!')))
        for k,name in enumerate(DOMAIN['names']):
            study=db.scalar(select(Study).where(Study.name==name))
            if not study:
                study=Study(name=name,source_filename=DOMAIN['slug']+f'-202611-{k+1}.csv',description='独立合成业务观测 / 固定种子42 / 仅用于方法与流程演示');db.add(study);db.flush()
            rows=[]
            if i==0:
                for n in range(120): rows.append({'moisture':round(float(np.clip(rng.normal(5.2+k*.7,.7),0,100)),3),'extract':round(float(np.clip(rng.normal(34+k*2,2.4),0,100)),3)})
            elif i==1:
                rows=[{'group':'A','success':87+k*2,'failure':13-k*2},{'group':'B','success':96-k,'failure':4+k}]
            elif i==2:
                for n in range(24):
                    b=float(rng.uniform(3,6));rows.append({'before':round(b,3),'after':round(max(.1,b+rng.normal(-.45+k*.3,.5)),3)})
            elif i==3:
                for n in range(90):
                    x=round(float(rng.uniform(4,28)),1);rows.append({'porosity':x,'absorption':round(max(0,x*(.18+k*.08)+rng.normal(0,1.5)),2)})
            else: rows=[{'p0':.08+k*.02,'p1':.1+k*.025,'cost_per_contact':.12+k*.04,'budget':3000+k*500}]
            for n,values in enumerate(rows):
                key=f'DEMO-{k+1}-{n+1:04}'
                if not db.scalar(select(Observation.id).where(Observation.study_id==study.id,Observation.source_key==key)):
                    db.add(Observation(study_id=study.id,source_key=key,values=values))
        seed_spillover_demo(db)
        db.commit()
        counts={model.__tablename__:db.scalar(select(func.count()).select_from(model)) for model in (User,Study,Observation)}
        print(json.dumps(counts));return counts

def seed_spillover_demo(db):
    '''留白外溢演示批次：固定名额 3/8；含孤立点 S08 与缺报点击 S07 各一例。'''
    first=db.scalar(select(Study).order_by(Study.id))
    if not first: return
    code='SPILL-DEMO-1'
    if db.scalar(select(SpilloverSubmission.id).where(
            SpilloverSubmission.study_id==first.id,SpilloverSubmission.batch_code==code)):
        return
    roster_csv='id,slot\n'+'\n'.join(
        f'S{i:02d},'+('treated' if i<=3 else 'holdout') for i in range(1,9))+'\n'
    edges_csv='source,target\nS01,S04\nS02,S05\nS03,S06\nS04,S05\nS06,S05\n'
    # S07 故意缺报（整行省略，不算零）；S08 无任何联系（孤立受众）
    clicks_csv='id,click\nS04,1\nS05,1\nS06,0\nS08,0\n'
    roster=parse_roster(roster_csv);edges=parse_edges(edges_csv,set(roster))
    clicks=parse_clicks(clicks_csv,set(roster))
    sub=SpilloverSubmission(
        study_id=first.id,batch_code=code,status='open',
        data={'roster':{'filename':'demo-roster.csv','content':roster_csv,'parsed':roster},
              'edges':{'filename':'demo-edges.csv','content':edges_csv,'parsed':edges},
              'clicks':{'filename':'demo-clicks.csv','content':clicks_csv,'parsed':clicks}},
        missing_click_ids=[pid for pid,slot in roster.items() if slot=='holdout' and pid not in clicks],
        note='演示：S08 孤立（pi1=0 剔除）、S07 缺报点击（不算零，封存前须补交或更正）',
        created_by='seed@demo.local',created_at=now())
    db.add(sub)
if __name__=='__main__': seed()
