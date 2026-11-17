"""自检与修复服务。

状态机（Run.health）：
 unchecked                 历史报告尚未自检
 ok                        冻结底稿完好且结果与重算一致
 result_corrupted          底稿完好但结果损坏（可修复）
 source_corrupted          冻结底稿/口径本身受损（拒绝修复，永久记录原因）
 repairing                 修复任务已排队/执行中
 repaired_pending_review   结果已原子切换，等待重新复核
 reapproved                重新复核通过（同版完整结果，可继续交付）
"""
import time
from fastapi import HTTPException
from src.models.run import Run,RepairJob,RunReview,Schedule,Delivery
from src.services.calculation import calculate
from src.services.integrity import (with_row_lock,record_event,atomic_switch_result,
        snapshot_checksum,result_checksum)
from src.services.audit import log
from src.config.settings import REDIS_URL
import redis

HEALTH_LABELS=('unchecked','ok','result_corrupted','source_corrupted','repairing','repaired_pending_review','reapproved')

def _idem_key(run_id,damaged_checksum):
 return f'run-{run_id}:damaged-{damaged_checksum}'

def _keep_pending_if_unapproved(run,health,detail):
 """修复后未重新复核前，保留待复核状态，避免自检把流程提示冲掉。"""
 if health=='ok' and not run.approved and (run.repair_seq or 0)>0:
  return 'repaired_pending_review','结果完整但尚未重新复核，复核前不得继续交付'
 return health,detail

def classify(run):
 """只做判断不写库：返回 (health, detail, recomputed_or_None)。"""
 if run.status!='completed' or not run.result:
  return run.health or 'unchecked','报告尚未完成，无需自检',None
 if run.checksum != snapshot_checksum(run.snapshot):
  return 'source_corrupted','冻结底稿/口径校验和与提交时不一致，底稿受损，拒绝自动修复（重算将以受损数据为准）',None
 try:
  recomputed=calculate(run.snapshot['sources'],run.snapshot['policy'])
 except Exception as exc:
  return 'source_corrupted',f'冻结底稿无法通过口径计算：{exc}；判定底稿受损，拒绝修复',None
 if result_checksum(recomputed)==result_checksum(run.result):
  return 'ok','自检通过：冻结底稿完好，结果与按同版口径重算一致',recomputed
 return 'result_corrupted','冻结底稿完好，但当前结果与重算不符，结果损坏，可按冻结底稿修复',recomputed

def self_check(db,user,run_id):
 run=with_row_lock(db,run_id)
 if not run: raise HTTPException(404,'报告不存在')
 if run.status!='completed': raise HTTPException(409,'仅已完成报告可自检')
 if run.health=='repairing':
  record_event(db,run_id,user.email,'selfcheck.skip','修复进行中，旧自检不得覆盖新修复状态')
  db.commit();return run
 # 重新分类时若发现已是修复后的版本，重新计算自然会一致；事件仍如实记录
 health,detail,recomputed=classify(run)
 health,detail=_keep_pending_if_unapproved(run,health,detail)
 before=run.health
 run.health=health;run.health_detail=detail;run.checked_at=time.time()
 record_event(db,run_id,user.email,'selfcheck',f'{before or "unchecked"} -> {health}；{detail}')
 log(db,user.email,'run.selfcheck',f'{run_id}:{before}->{health}')
 db.commit();db.refresh(run);return run

def request_repair(db,user,run_id):
 """登记修复请求：底稿受损则拒绝并记录原因；幂等，重复执行不新增修复版本。"""
 run=with_row_lock(db,run_id)
 if not run: raise HTTPException(404,'报告不存在')
 if run.status!='completed': raise HTTPException(409,'仅已完成报告可修复')
 if run.health in ('ok',):
  raise HTTPException(409,'自检通过的报告无需修复')
 if run.health=='source_corrupted':
  record_event(db,run_id,user.email,'repair.reject',run.health_detail)
  log(db,user.email,'repair.reject',run_id);db.commit()
  raise HTTPException(422,'底稿受损，拒绝修复：'+run.health_detail)
 if run.health=='repairing':
  existing=db.query(RepairJob).filter(RepairJob.run_id==run_id,RepairJob.status.in_(['queued','running'])).order_by(RepairJob.id.desc()).first()
  if existing:
   record_event(db,run_id,user.email,'repair.duplicate',f'修复任务 {existing.id} 已在进行，重复请求不新增版本')
   db.commit();return run
 # 先现场判定，区分两类损坏
 health,detail,recomputed=classify(run)
 if health=='source_corrupted':
  run.health='source_corrupted';run.health_detail=detail;run.checked_at=time.time()
  record_event(db,run_id,user.email,'repair.reject',detail)
  log(db,user.email,'repair.reject',run_id);db.commit()
  raise HTTPException(422,'底稿受损，拒绝修复：'+detail)
 if health=='ok':
  health,detail=_keep_pending_if_unapproved(run,health,detail)
  run.health=health;run.health_detail=detail;run.checked_at=time.time()
  record_event(db,run_id,user.email,'repair.unneeded',detail)
  db.commit();return run
 damaged=result_checksum(run.result)
 key=_idem_key(run_id,damaged)
 existing=db.query(RepairJob).filter_by(idem_key=key).first()
 if existing:
  record_event(db,run_id,user.email,'repair.duplicate',f'同一损坏结果的修复任务 {existing.id} 已存在，不重复创建')
  db.commit();return run
 job=RepairJob(run_id=run_id,status='queued',damage=health,reason=detail,idem_key=key,
        actor=user.email,created=time.time(),from_version=run.result_version)
 db.add(job);db.flush()
 run.health='repairing';run.health_detail='修复任务已排队，将按冻结底稿与同版口径重算'
 record_event(db,run_id,user.email,'repair.queue',f'job={job.id} from_version={run.result_version} 损坏校验和={damaged[:12]}')
 log(db,user.email,'repair.queue',f'run={run_id} job={job.id}')
 db.commit();db.refresh(run)
 redis.Redis.from_url(REDIS_URL).rpush('repair-jobs',job.id)
 return run

def execute_repair(db,job_id,redis_client=None):
 """worker 执行；切换前后中断都可恢复，重复执行不新增修复版本。"""
 job=db.get(RepairJob,job_id)
 if not job or job.status not in ('queued','running'): return
 run=with_row_lock(db,job.run_id)
 if not run:
  job.status='failed';job.last_error='报告不存在';job.finished_at=time.time();db.commit();return
 # 恢复点1：任务已完成过（上次在提交后中断），直接收敛不重算
 done=db.query(RepairJob).filter_by(idem_key=job.idem_key,status='succeeded').first()
 if done and done.id!=job.id:
  job.status='succeeded';job.to_version=done.to_version;job.finished_at=time.time()
  record_event(db,run.id,'worker','repair.resume',f'任务 {job.id} 收敛到已完成任务 {done.id}，不新增版本')
  db.commit();return
 job.status='running';job.started_at=job.started_at or time.time();job.attempts=(job.attempts or 0)+1
 record_event(db,run.id,'worker','repair.start',f'job={job.id} attempt={job.attempts}')
 db.commit()
 try:
  # 恢复点2：重新判定，底稿受损则拒绝并终止
  health,detail,recomputed=classify(run)
  if health=='source_corrupted':
   run.health='source_corrupted';run.health_detail=detail
   job.status='rejected';job.last_error=detail;job.finished_at=time.time()
   record_event(db,run.id,'worker','repair.reject',detail)
   log(db,'worker','repair.reject',run.id);db.commit();return
  if health=='ok':
   health,detail=_keep_pending_if_unapproved(run,health,detail)
   run.health=health;run.health_detail=detail
   job.status='succeeded';job.to_version=run.result_version;job.finished_at=time.time()
   record_event(db,run.id,'worker','repair.skip','结果已完整，无需切换')
   db.commit();return
  # 原子切换（单事务）；若在 commit 前中断，任务保持 running，重试时重新计算并切换，
  # 由于新版本仅在本事务提交后才可见，中断不会产生半成品版本
  new_version=atomic_switch_result(db,run,recomputed,'worker',job.reason,kind='repair')
  _revoke_approvals(db,run,actor='worker',cause=f'修复切换 v{job.from_version}->v{new_version}，旧复核撤销')
  _pause_schedules(db,run,cause=f'报告 {run.id} 修复切换，重新复核前暂停后续交付')
  _mark_deliveries(db,run,new_version)
  job.status='succeeded';job.to_version=new_version;job.finished_at=time.time()
  record_event(db,run.id,'worker','repair.switch',f'v{job.from_version}->v{new_version} 新结果校验和={result_checksum(recomputed)[:12]}')
  log(db,'worker','repair.switch',f'run={run.id} v{job.from_version}->v{new_version}')
  db.commit()
 except Exception as exc:
  db.rollback()
  job=db.get(RepairJob,job_id);run=db.get(Run,job.run_id)
  job.last_error=str(exc);job.status='queued'  # 回到队列，等待下次重试恢复
  record_event(db,run.id,'worker','repair.retry',str(exc))
  db.commit()

def _revoke_approvals(db,run,actor,cause):
 for rv in db.query(RunReview).filter_by(run_id=run.id,state='active').all():
  rv.state='revoked'
 run.approved=False;run.review=''
 record_event(db,run.id,actor,'review.revoke',cause)

def _pause_schedules(db,run,cause):
 for sch in db.query(Schedule).filter_by(run_id=run.id,enabled=True,auto_paused=False).all():
  sch.enabled=False;sch.auto_paused=True
 record_event(db,run.id,'worker','schedule.pause',cause)

def _mark_deliveries(db,run,new_version):
 """已发出内容保留原样，只加更正标记。"""
 items=db.query(Delivery).filter_by(run_id=run.id,corrected=False).all()
 for d in items:
  d.corrected=True;d.superseded_by_run_version=new_version
 if items:
  record_event(db,run.id,'worker','delivery.corrected',f'{len(items)} 份已发出交付标记为已被更正，原件保留')

def reapprove(db,user,run_id,note):
 run=with_row_lock(db,run_id)
 if not run: raise HTTPException(404,'报告不存在')
 if run.status!='completed': raise HTTPException(409,'仅已完成报告可复核')
 if run.health not in ('repaired_pending_review','ok','reapproved'):
  raise HTTPException(409,'当前状态不可复核：'+(run.health_detail or run.health))
 # 同版结果完整性兜底：复核的必须是当前版本且与冻结底稿重算一致
 health,detail,_=classify(run)
 if health!='ok':
  raise HTTPException(409,'当前结果版本未通过完整性自检，不能复核：'+detail)
 rv=RunReview(run_id=run_id,version=run.result_version,note=note,actor=user.email,state='active',created=time.time())
 db.add(rv)
 run.approved=True;run.review=note;run.health='reapproved';run.health_detail=f'v{run.result_version} 已重新复核通过'
 record_event(db,run_id,user.email,'review.approve',f'version={run.result_version} note={note}')
 log(db,user.email,'run.reapprove',f'{run_id}:v{run.result_version}')
 # 重新复核通过 -> 自动恢复因修复暂停的计划（人工停用的不动）
 resumed=[]
 for sch in db.query(Schedule).filter_by(run_id=run_id,auto_paused=True).all():
  sch.enabled=True;sch.auto_paused=False
  if sch.next_at<time.time(): sch.next_at=time.time()+sch.interval_seconds
  resumed.append(sch.id)
 if resumed:
  record_event(db,run_id,user.email,'schedule.resume',f'重新复核通过，恢复计划 {resumed}')
 db.commit();db.refresh(run);return run

def versions_of(db,run_id):
 from src.models.run import ResultVersion
 return db.query(ResultVersion).filter_by(run_id=run_id).order_by(ResultVersion.version.asc()).all()

def diff_versions(db,run_id,from_v,to_v):
 from src.models.run import ResultVersion
 a=db.query(ResultVersion).filter_by(run_id=run_id,version=from_v).first()
 b=db.query(ResultVersion).filter_by(run_id=run_id,version=to_v).first()
 if not a or not b: raise HTTPException(404,'结果版本不存在')
 return _diff_result(a.result,b.result)

def _keyed_rows(result):
 rows=result.get('rows',[])
 out={}
 for r in rows:
  k=(r.get('月份'),r.get('小组'),r.get('优先级'))
  out[k]=r
 return out

def _diff_result(old,new):
 changes=[]
 ro,rn=_keyed_rows(old),_keyed_rows(new)
 for k in sorted(set(ro)|set(rn)):
  if k not in ro: changes.append({'key':k,'change':'新增','old':None,'new':rn[k]});continue
  if k not in rn: changes.append({'key':k,'change':'删除','old':ro[k],'new':None});continue
  fields={}
  for f in set(ro[k])|set(rn[k]):
   if ro[k].get(f)!=rn[k].get(f): fields[f]={'old':ro[k].get(f),'new':rn[k].get(f)}
  if fields: changes.append({'key':k,'change':'变更','fields':fields})
 return {'summary_old':old.get('summary'),'summary_new':new.get('summary'),'row_changes':changes}
