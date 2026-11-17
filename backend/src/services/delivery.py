import time
from fastapi import HTTPException
from src.models.run import Run,Schedule,Delivery
from src.services.audit import log
from src.services.integrity import record_event,result_checksum
from src.services.integrity_flow import classify

def _eligible(run):
 """交付取数门禁：仅完整、当前版本已复核且自检通过的同版结果可被引用。"""
 if not run or run.status!='completed' or not run.approved: return False,'未复核'
 if run.health not in ('ok','reapproved'): return False,'报告状态不允许交付：'+(run.health or '未自检')
 health,_,_=classify(run)
 if health!='ok': return False,'当前结果版本未通过完整性自检'
 return True,''

def add_schedule(db,user,body):
 run=db.get(Run,body.run_id)
 ok,reason=_eligible(run)
 if not ok: raise HTTPException(409,'定时交付需引用完整且已复核的同版结果：'+reason)
 obj=Schedule(name=body.name,run_id=run.id,interval_seconds=body.interval_seconds,next_at=time.time()+body.interval_seconds,enabled=True,auto_paused=False)
 db.add(obj);db.flush()
 record_event(db,run.id,user.email,'schedule.create',f'schedule={obj.id} 引用版本 v{run.result_version}')
 log(db,user.email,'schedule.create',body.name);db.commit();return obj

def toggle(db,user,sch_id):
 obj=db.get(Schedule,sch_id)
 if not obj: raise HTTPException(404,'计划不存在')
 if obj.enabled:
  obj.enabled=False;obj.auto_paused=False  # 人工停用，后续不自动恢复
 else:
  run=db.get(Run,obj.run_id);ok,reason=_eligible(run)
  if not ok: raise HTTPException(409,'报告当前不满足交付条件：'+reason)
  obj.enabled=True
 record_event(db,obj.run_id,user.email,'schedule.toggle',f'schedule={obj.id} enabled={obj.enabled}')
 db.commit();return obj

def tick(db):
 now=time.time()
 for schedule in db.query(Schedule).filter(Schedule.enabled==True,Schedule.next_at<=now).all():
  run=db.get(Run,schedule.run_id)
  ok,reason=_eligible(run)
  if not ok:
   # 门禁未过：暂停后续交付并留痕，等待修复与重新复核
   schedule.enabled=False;schedule.auto_paused=True
   record_event(db,run.id if run else -1,'worker','delivery.blocked',f'schedule={schedule.id} {reason}，暂停后续交付')
   schedule.next_at=now+schedule.interval_seconds
   continue
  key=f'{schedule.id}:{schedule.next_at}'
  if not db.query(Delivery).filter_by(due_key=key).first():
   # 每份交付固化其引用的结果版本与校验和，后续修复不会改写已发出内容
   delivery=Delivery(schedule_id=schedule.id,run_id=run.id,due_key=key,created=now,
     result_version=run.result_version,corrected=False,
     payload={'name':run.name,'checksum':run.checksum,'result':run.result,'review':run.review,
              'policy':run.snapshot['policy'],'result_version':run.result_version,
              'result_checksum':result_checksum(run.result)})
   db.add(delivery);db.flush()
   record_event(db,run.id,'worker','delivery.created',f'delivery={delivery.id} 引用 v{run.result_version} 校验和={result_checksum(run.result)[:12]}')
   log(db,'worker','delivery.created',key)
  schedule.next_at=now+schedule.interval_seconds
 db.commit()
