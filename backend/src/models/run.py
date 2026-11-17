from sqlalchemy import Column,Integer,String,JSON,Text,Float,Boolean,Index
from src.config.database import Base

class Run(Base):
 __tablename__='sla_runs'
 id=Column(Integer,primary_key=True); name=Column(String(120)); status=Column(String(20)); snapshot=Column(JSON); checksum=Column(String(64)); result=Column(JSON); error=Column(Text); created=Column(Float); approved=Column(Boolean,default=False); review=Column(Text,default='')
 # 自检与修复：health 为完整状态机，version 为当前结果版本号（原子切换时递增）
 health=Column(String(24),default='unchecked'); health_detail=Column(Text,default=''); result_version=Column(Integer,default=1)
 checked_at=Column(Float); repaired_at=Column(Float); repair_seq=Column(Integer,default=0)

class ResultVersion(Base):
 __tablename__='run_result_versions'
 id=Column(Integer,primary_key=True); run_id=Column(Integer,index=True); version=Column(Integer); kind=Column(String(20))
 result=Column(JSON); result_checksum=Column(String(64)); source_checksum=Column(String(64))
 actor=Column(String(120)); note=Column(Text,default=''); created=Column(Float)
 __table_args__=(Index('ix_result_version_run_ver','run_id','version',unique=True),)

class RepairJob(Base):
 __tablename__='run_repair_jobs'
 id=Column(Integer,primary_key=True); run_id=Column(Integer,index=True); status=Column(String(20))
 damage=Column(String(20)); reason=Column(Text,default=''); idem_key=Column(String(160),unique=True)
 actor=Column(String(120)); created=Column(Float); started_at=Column(Float); finished_at=Column(Float)
 from_version=Column(Integer); to_version=Column(Integer); attempts=Column(Integer,default=0); last_error=Column(Text,default='')

class RunEvent(Base):
 __tablename__='run_events'
 id=Column(Integer,primary_key=True); run_id=Column(Integer,index=True); seq=Column(Integer)
 actor=Column(String(120)); action=Column(String(80)); detail=Column(Text,default=''); at=Column(Float)
 __table_args__=(Index('ix_run_event_run_seq','run_id','seq',unique=True),)

class RunReview(Base):
 __tablename__='run_reviews'
 id=Column(Integer,primary_key=True); run_id=Column(Integer,index=True); version=Column(Integer)
 note=Column(Text); actor=Column(String(120)); state=Column(String(20),default='active'); created=Column(Float)
 __table_args__=(Index('ix_run_review_run_ver','run_id','version'),)

class Schedule(Base):
 __tablename__='delivery_schedules'
 id=Column(Integer,primary_key=True); name=Column(String(120)); run_id=Column(Integer); interval_seconds=Column(Integer); next_at=Column(Float); enabled=Column(Boolean,default=True)
 # auto_paused：因修复而暂停，重新复核后可自动恢复；manually_disabled：人工停用不自动恢复
 auto_paused=Column(Boolean,default=False)

class Delivery(Base):
 __tablename__='deliveries'
 id=Column(Integer,primary_key=True); schedule_id=Column(Integer); run_id=Column(Integer); due_key=Column(String(120),unique=True); created=Column(Float); payload=Column(JSON)
 result_version=Column(Integer,default=1); corrected=Column(Boolean,default=False); superseded_by_run_version=Column(Integer)
