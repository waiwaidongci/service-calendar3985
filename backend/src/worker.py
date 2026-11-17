import time,traceback
from pathlib import Path
import redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import identity,source,run  # noqa: F401  确保模型注册到 metadata
from src.models.run import Run,RepairJob
from src.services.calculation import calculate
from src.services.delivery import tick
from src.services.report import register_initial_version
from src.services.integrity_flow import self_check,execute_repair,classify
from src.services.integrity import record_event,result_checksum
from src.config.migrate import run_migrations

def process_calc(db,item):
 job=db.get(Run,int(item))
 if not job or job.status!='queued': return
 job.status='running';record_event(db,job.id,'worker','run.start','');db.commit()
 try:
  result=calculate(job.snapshot['sources'],job.snapshot['policy'])
  job.result=result;job.status='completed';job.error=''
  register_initial_version(db,job,result)
  health,detail,_=classify(job)
  job.health=health;job.health_detail=detail;job.checked_at=time.time()
  record_event(db,job.id,'worker','run.complete',f'version=1 结果校验和={result_checksum(result)[:12]} 自检={health}')
 except Exception as exc:
  job.status='failed';job.error=str(exc);job.health='unchecked';job.health_detail='计算失败'
  record_event(db,job.id,'worker','run.failed',str(exc));traceback.print_exc()
 db.commit()

def process_repair(db,item):
 execute_repair(db,int(item))

def recover_stuck(client,db):
 """恢复点：worker 重启后，中断的 running 任务重新入队；滞留 queued 任务补推。

 重复入队是安全的：execute_repair 以任务状态为守卫，已完成任务再次弹出直接收敛，
 不会重复计算或新增修复版本。
 """
 queued=client.lrange('repair-jobs',0,-1)
 in_queue={int(x) for x in queued}
 changed=False
 for job in db.query(RepairJob).filter(RepairJob.status.in_(['running','queued'])).all():
  if job.status=='running':
   job.status='queued';changed=True
   record_event(db,job.run_id,'worker','repair.recover',f'任务 {job.id} 在切换前后中断，重新入队恢复')
  if job.id not in in_queue:
   client.rpush('repair-jobs',job.id)
 if changed: db.commit()

def sweep_legacy(db):
 """历史报告缺少自检：每 30 秒对已完成但 unchecked 的报告补检一次。"""
 pending=db.query(Run).filter(Run.status=='completed',Run.health.in_(['unchecked',None])).limit(20).all()
 for run_obj in pending:
  try: self_check(db,type('U',(),{'email':'worker'})(),run_obj.id)
  except Exception: traceback.print_exc()

def main():
 run_migrations()
 client=redis.Redis.from_url(REDIS_URL)
 last_sweep=0.0
 while True:
  Path('/tmp/worker-heartbeat').write_text(str(time.time()))
  try:
   item=client.lpop('report-jobs')
   if item:
    with Session() as db: process_calc(db,item)
   item=client.lpop('repair-jobs')
   if item:
    with Session() as db: process_repair(db,item)
   with Session() as db:
    recover_stuck(client,db)
    if time.time()-last_sweep>30:
     sweep_legacy(db);last_sweep=time.time()
    tick(db)
  except Exception: traceback.print_exc()
  time.sleep(1)

if __name__=='__main__':
 main()
