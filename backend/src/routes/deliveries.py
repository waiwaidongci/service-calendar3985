from fastapi import APIRouter,Depends,HTTPException
from fastapi.responses import Response
from src.config.database import database
from src.controllers.auth import current,admin
from src.models.run import Schedule,Delivery
from src.schemas.requests import ScheduleInput
from src.services.delivery import add_schedule,toggle
from src.services.export import csv_text
from src.utils.serialize import row
router=APIRouter()
@router.get('/schedules')
def schedules(db=Depends(database),u=Depends(current)): return [row(x) for x in db.query(Schedule).all()]
@router.post('/schedules')
def create(b:ScheduleInput,db=Depends(database),u=Depends(admin)): return row(add_schedule(db,u,b))
@router.post('/schedules/{id}/toggle')
def toggle_route(id:int,db=Depends(database),u=Depends(admin)): return row(toggle(db,u,id))
@router.get('/deliveries')
def deliveries(db=Depends(database),u=Depends(current)): return [row(x) for x in db.query(Delivery).order_by(Delivery.id.desc()).limit(100).all()]
@router.get('/deliveries/{id}/csv')
def download(id:int,db=Depends(database),u=Depends(current)):
 obj=db.get(Delivery,id)
 if not obj: raise HTTPException(404,'交付不存在')
 # 已发出内容保留原样：下载内容不变，仅文件名体现更正标记，页面展示更正状态
 suffix='-corrected' if obj.corrected else ''
 return Response(csv_text(obj.payload['result']),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="delivery-{id}-v{obj.result_version}{suffix}.csv"'})
