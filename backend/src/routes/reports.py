from fastapi import APIRouter,Depends,HTTPException
from fastapi.responses import Response
from src.config.database import database
from src.controllers.auth import current,editor,admin
from src.models.run import Run,RepairJob,RunReview
from src.schemas.requests import RunInput,ReviewInput,TamperInput
from src.services.report import submit,approve
from src.services.integrity_flow import self_check,request_repair,versions_of,diff_versions
from src.services.integrity import events_of
from src.services.export import csv_text
from src.utils.serialize import row
router=APIRouter()
@router.get('/runs')
def runs(db=Depends(database),u=Depends(current)): return [row(x) for x in db.query(Run).order_by(Run.id.desc()).all()]
@router.post('/runs')
def create(b:RunInput,db=Depends(database),u=Depends(editor)): return row(submit(db,u,b))
@router.get('/runs/{id}')
def detail(id:int,db=Depends(database),u=Depends(current)):
 obj=db.get(Run,id)
 if not obj: raise HTTPException(404,'报告不存在')
 return row(obj)
@router.post('/runs/{id}/selfcheck')
def check(id:int,db=Depends(database),u=Depends(editor)): return row(self_check(db,u,id))
@router.post('/runs/{id}/repair')
def repair(id:int,db=Depends(database),u=Depends(admin)): return row(request_repair(db,u,id))
@router.post('/runs/{id}/approve')
def review(id:int,b:ReviewInput,db=Depends(database),u=Depends(admin)): return row(approve(db,u,id,b.note))
@router.get('/runs/{id}/versions')
def versions(id:int,db=Depends(database),u=Depends(current)):
 return [row(x) for x in versions_of(db,id)]
@router.get('/runs/{id}/events')
def events(id:int,db=Depends(database),u=Depends(current)):
 return [row(x) for x in events_of(db,id)]
@router.get('/runs/{id}/reviews')
def reviews(id:int,db=Depends(database),u=Depends(current)):
 return [row(x) for x in db.query(RunReview).filter_by(run_id=id).order_by(RunReview.id.asc()).all()]
@router.get('/runs/{id}/diff')
def diff(id:int,from_v:int=1,to_v:int=2,db=Depends(database),u=Depends(current)):
 return diff_versions(db,id,from_v,to_v)
@router.post('/runs/{id}/tamper')
def tamper(id:int,b:TamperInput,db=Depends(database),u=Depends(admin)):
 """演示用：分别模拟结果损坏与底稿受损，便于验收自检的两类判定。"""
 from src.services.integrity import record_event,result_checksum,snapshot_checksum
 obj=db.get(Run,id)
 if not obj: raise HTTPException(404,'报告不存在')
 if obj.status!='completed': raise HTTPException(409,'仅已完成报告可模拟损坏')
 if b.scope=='result':
  obj.result=dict(obj.result);obj.result['summary']=dict(obj.result.get('summary',{}));obj.result['summary']['被篡改']=True
  obj.health='unchecked';obj.health_detail='疑似结果被改动，等待自检';obj.checked_at=None
  record_event(db,id,u.email,'tamper.result','演示：结果字段被改动，冻结底稿未动')
 elif b.scope=='source':
  obj.snapshot=dict(obj.snapshot);obj.snapshot['sources']=list(obj.snapshot['sources'])
  obj.snapshot['sources'][0]=dict(obj.snapshot['sources'][0]);obj.snapshot['sources'][0]['department']='被篡改小组'
  obj.health='unchecked';obj.health_detail='疑似冻结底稿被改动，等待自检';obj.checked_at=None
  record_event(db,id,u.email,'tamper.source','演示：冻结快照被改动，原始校验和不再匹配')
 else: raise HTTPException(422,'scope 仅支持 result 或 source')
 from src.services.audit import log
 log(db,u.email,'run.tamper',f'{id}:{b.scope}');db.commit();return row(obj)
@router.get('/runs/{id}/csv')
def download(id:int,db=Depends(database),u=Depends(current)):
 obj=db.get(Run,id)
 if not obj or obj.status!='completed': raise HTTPException(409,'报告尚未完成')
 if u.role=='viewer' and not obj.approved: raise HTTPException(403,'业务阅读者仅可下载已复核报告')
 if obj.health not in ('ok','reapproved'):
  raise HTTPException(409,'结果尚未通过完整性自检或待重新复核，暂不可下载')
 return Response(csv_text(obj.result),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="report-{id}-v{obj.result_version}.csv"'})
@router.get('/repair-jobs')
def repair_jobs(db=Depends(database),u=Depends(current)):
 return [row(x) for x in db.query(RepairJob).order_by(RepairJob.id.desc()).limit(100).all()]
