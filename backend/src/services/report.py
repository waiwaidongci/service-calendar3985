import hashlib,json,time
from fastapi import HTTPException
from src.models.source import Source,Policy
from src.models.run import Run,ResultVersion
from src.services.audit import log
from src.services.integrity import snapshot_checksum,record_event,result_checksum
from src.services.integrity_flow import reapprove
from src.config.settings import REDIS_URL
import redis

def submit(db,user,body):
 policy=db.get(Policy,body.policy_id)
 if not policy: raise HTTPException(404,'口径版本不存在')
 sources=[x.data for x in db.query(Source).order_by(Source.id).all() if body.period=='全部' or x.data.get('period')==body.period]
 if not sources: raise HTTPException(422,'所选期间没有底稿')
 snapshot={'policy':policy.data,'sources':sources,'period':body.period}
 checksum=snapshot_checksum(snapshot)
 obj=Run(name=body.name,status='queued',snapshot=snapshot,checksum=checksum,created=time.time(),
         approved=False,result_version=1,repair_seq=0,health='unchecked',health_detail='排队中，完成后待自检')
 db.add(obj);db.flush()
 record_event(db,obj.id,user.email,'run.queue',f'冻结底稿校验和={checksum[:12]} 期间={body.period} 口径={policy.data.get("version")}')
 log(db,user.email,'run.queue',body.name);db.commit()
 redis.Redis.from_url(REDIS_URL).rpush('report-jobs',obj.id)
 return obj

def approve(db,user,id,note):
 """统一复核入口：初次复核与修复后重新复核共用同一完整性规则。"""
 return reapprove(db,user,id,note)

def register_initial_version(db,run,result):
 """worker 计算成功后登记 v1 结果版本并自检一次（历史报告也可事后补检）。"""
 db.add(ResultVersion(run_id=run.id,version=1,kind='initial',result=result,
        result_checksum=result_checksum(result),source_checksum=run.checksum,
        actor='worker',note='初次核算结果',created=time.time()))
 run.result_version=1
