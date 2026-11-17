"""增量迁移：在 SQLAlchemy 建表基础上补齐旧库缺失列，并回填历史数据。

- 新表由 Base.metadata.create_all 创建；
- 旧表缺列用 ADD COLUMN IF NOT EXISTS（PG）/逐列探测（SQLite）补齐；
- 历史报告回填 result_version=1 的结果版本、health 初始值与首条事件；
- 已有交付回填 result_version=1、corrected=False。
幂等，可重复执行。
"""
import time
from sqlalchemy import text,inspect
from src.config.database import Base,engine,Session
from src.models.run import Run,ResultVersion,RunEvent,Delivery,Schedule,RepairJob,RunReview
from src.services.integrity import result_checksum,snapshot_checksum,record_event
from src.services.integrity_flow import classify

RUN_NEW_COLUMNS={
 'health':"VARCHAR(24) DEFAULT 'unchecked'",
 'health_detail':"VARCHAR(2000) DEFAULT ''",
 'result_version':'INTEGER DEFAULT 1',
 'checked_at':'FLOAT',
 'repaired_at':'FLOAT',
 'repair_seq':'INTEGER DEFAULT 0',
}
SCHEDULE_NEW_COLUMNS={'auto_paused':'BOOLEAN DEFAULT FALSE'}
DELIVERY_NEW_COLUMNS={'result_version':'INTEGER DEFAULT 1','corrected':'BOOLEAN DEFAULT FALSE','superseded_by_run_version':'INTEGER'}

def _existing_columns(conn,table):
 return {c['name'] for c in inspect(conn).get_columns(table)}

def _add_columns(conn,table,columns):
 existing=_existing_columns(conn,table)
 is_pg=conn.dialect.name=='postgresql'
 for name,ddl in columns.items():
  if name in existing: continue
  if is_pg:
   conn.execute(text(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {ddl}'))
  else:
   conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))

def run_migrations():
 Base.metadata.create_all(engine)
 with engine.begin() as conn:
  _add_columns(conn,'sla_runs',RUN_NEW_COLUMNS)
  _add_columns(conn,'delivery_schedules',SCHEDULE_NEW_COLUMNS)
  _add_columns(conn,'deliveries',DELIVERY_NEW_COLUMNS)
 with Session() as db:
  # 回填历史报告的 v1 结果版本
  for run_obj in db.query(Run).all():
   if run_obj.result_version is None: run_obj.result_version=1
   if run_obj.repair_seq is None: run_obj.repair_seq=0
   if run_obj.status=='completed' and run_obj.result:
    exists=db.query(ResultVersion).filter_by(run_id=run_obj.id,version=1).first()
    if not exists:
     db.add(ResultVersion(run_id=run_obj.id,version=1,kind='initial',result=run_obj.result,
          result_checksum=result_checksum(run_obj.result),source_checksum=run_obj.checksum,
          actor='migration',note='历史报告回填的初次结果版本',created=run_obj.created or time.time()))
    # 以 checked_at 为准：从未自检过的历史完成报告补一次基线自检
    if run_obj.checked_at is None:
     health,detail,_=classify(run_obj)
     run_obj.health=health;run_obj.health_detail=detail;run_obj.checked_at=time.time()
    elif not run_obj.health:
     run_obj.health='unchecked';run_obj.health_detail='历史报告，待自检'
    if not db.query(RunEvent).filter_by(run_id=run_obj.id).first():
     record_event(db,run_obj.id,'migration','run.history','历史报告迁移：补齐版本与自检基线')
   elif not run_obj.health:
    run_obj.health='unchecked';run_obj.health_detail='历史报告，尚未完成或待自检'
  for d in db.query(Delivery).all():
   if d.result_version is None: d.result_version=1
   if d.corrected is None: d.corrected=False
  for s in db.query(Schedule).all():
   if s.auto_paused is None: s.auto_paused=False
  db.commit()
