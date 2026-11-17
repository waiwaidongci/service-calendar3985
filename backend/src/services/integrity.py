"""报告完整性内核：冻结口径校验、并发串行化、事件流水与原子切换原语。

所有自检/修复/复核/交付取数都经由本模块的 with_run_lock 串行化，
保证旧自检不能覆盖新修复，且每次状态推进都留下可追查的有序事件。
"""
import hashlib,json,time
from sqlalchemy import text
from src.models.run import RunEvent

def canonical(value):
 return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))

def sha256_of(value):
 return hashlib.sha256(canonical(value).encode()).hexdigest()

def snapshot_checksum(snapshot):
 """冻结底稿与口径的校验和；提交时的 run.checksum 必须与之保持一致。"""
 return sha256_of(snapshot)

def result_checksum(result):
 return sha256_of(result)

def dialect_name(db):
 return db.bind.dialect.name if db.bind else ''

def with_row_lock(db,run_id):
 """取出 Run 并加事务级行锁（Postgres 用 FOR UPDATE；SQLite 单写者天然串行）。

 调用方必须在同一个事务/会话内完成读取与写入后再 commit。
 """
 from src.models.run import Run
 obj=db.get(Run,run_id)
 if obj is not None and dialect_name(db)=='postgresql':
  db.execute(text('SELECT id FROM sla_runs WHERE id=:i FOR UPDATE'),{'i':run_id})
  db.refresh(obj)
 return obj

def next_seq(db,run_id):
 last=db.query(RunEvent).filter_by(run_id=run_id).order_by(RunEvent.seq.desc()).first()
 return (last.seq+1) if last else 1

def record_event(db,run_id,actor,action,detail=''):
 """事件流水：同 run 内 seq 严格递增，是自检/修复/复核/取数先后次序的唯一凭据。"""
 ev=RunEvent(run_id=run_id,seq=next_seq(db,run_id),actor=actor,action=action,detail=str(detail),at=time.time())
 db.add(ev);return ev

def events_of(db,run_id):
 return db.query(RunEvent).filter_by(run_id=run_id).order_by(RunEvent.seq.asc()).all()

def atomic_switch_result(db,run,new_result,actor,note,kind='repair'):
 """原子切换：新版本先落库，再整体替换 run 当前结果并升版本号。

 单事务提交；中断时要么旧版本仍在、新版本完整可见，不存在中间态。
 重复执行不会新增版本——调用方需先用幂等键拦截。
 """
 from src.models.run import ResultVersion
 new_version=run.result_version+1
 db.add(ResultVersion(run_id=run.id,version=new_version,kind=kind,result=new_result,
        result_checksum=result_checksum(new_result),source_checksum=run.checksum,
        actor=actor,note=note,created=time.time()))
 run.result=new_result
 run.result_version=new_version
 run.health='repaired_pending_review'
 run.health_detail='结果已按冻结底稿与口径重算并原子切换，等待负责人重新复核'
 run.repaired_at=time.time()
 run.repair_seq=(run.repair_seq or 0)+1
 return new_version
