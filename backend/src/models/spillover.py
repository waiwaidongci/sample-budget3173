from sqlalchemy import Column,Integer,String,JSON,Text,ForeignKey,UniqueConstraint
from src.config.database import Base

class SpilloverSubmission(Base):
    '''三份资料并发补交的同一批次容器；齐全后随运行封存，之后不可改写。'''
    __tablename__='spillover_submissions'
    __table_args__=(UniqueConstraint('study_id','batch_code'),)
    id=Column(Integer,primary_key=True)
    study_id=Column(Integer,ForeignKey('studies.id'),nullable=False)
    batch_code=Column(String(100),nullable=False)
    status=Column(String(20),default='open',nullable=False)  # open / sealed
    data=Column(JSON,nullable=False,default=dict)             # roster/edges/clicks 三份文件
    missing_click_ids=Column(JSON,nullable=False,default=list)
    sealed_at=Column(String(40),default='')
    sealed_run_id=Column(Integer,nullable=True)
    note=Column(Text,default='')
    created_by=Column(String(120),nullable=False)
    created_at=Column(String(40),nullable=False)

class SpilloverCorrection(Base):
    '''联系/点击更正独立封存、只追加不改写；能否并入开放批次由服务层判定。'''
    __tablename__='spillover_corrections'
    id=Column(Integer,primary_key=True)
    study_id=Column(Integer,ForeignKey('studies.id'),nullable=False)
    submission_id=Column(Integer,ForeignKey('spillover_submissions.id'),nullable=True)
    person_id=Column(String(64),nullable=False)
    payload=Column(JSON,nullable=False)
    source_filename=Column(String(120),nullable=False)
    status=Column(String(30),nullable=False)  # applied / rejected_sealed（含已封存、批次不存在、人员未知等一切不并入情形）
    checksum=Column(String(64),nullable=False)
    created_by=Column(String(120),nullable=False)
    created_at=Column(String(40),nullable=False)

class SpilloverRun(Base):
    __tablename__='spillover_runs'
    id=Column(Integer,primary_key=True)
    study_id=Column(Integer,ForeignKey('studies.id'),nullable=False)
    submission_id=Column(Integer,ForeignKey('spillover_submissions.id'),nullable=False)
    name=Column(String(120),nullable=False)
    status=Column(String(20),default='queued',nullable=False)
    parameters=Column(JSON,nullable=False,default=dict)
    snapshot=Column(JSON,nullable=False)
    checksum=Column(String(64),nullable=False)
    result=Column(JSON,nullable=True)
    error=Column(Text,default='')
    created_at=Column(String(40),nullable=False)
