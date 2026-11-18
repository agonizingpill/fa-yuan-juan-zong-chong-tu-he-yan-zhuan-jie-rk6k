import os,redis
from fastapi import HTTPException
from sqlalchemy import select
from .models import Intake,Triage,ModelRegistry
from .common import get,reject,finish,editable
from .intake_service import authorized
queue=redis.Redis.from_url(os.getenv('REDIS_URL','redis://redis:6379/0'),decode_responses=True)
def latest(db,id):
    case=get(db,Intake,id)
    return db.scalar(select(Triage).where(Triage.intake_id==id,Triage.facts_version==case.facts_version,Triage.status=='reviewed').order_by(Triage.id.desc()))
def enqueue(db,data,user):
    case=editable(db,data.intake_id);reject(not authorized(db,case.id),'未取得授权，不能提交行政分流')
    reject(db.scalar(select(Triage).where(Triage.intake_id==case.id,Triage.facts_version==case.facts_version,Triage.status.in_(['queued','running']))) is not None,'当前版本仍在分流')
    active=db.scalar(select(ModelRegistry.active_id).where(ModelRegistry.id==1))
    reject(active is None,'模型注册表未初始化，请先完成种子导入')
    row=Triage(intake_id=case.id,facts_version=case.facts_version,model_id=active);db.add(row);db.flush();result=finish(db,user,'提交主题分流',row)
    try:queue.rpush('aid:triage',row.id)
    except redis.RedisError:
        row.status='failed';row.error='任务队列暂不可用，恢复后可重新提交';db.commit()
        raise HTTPException(503,row.error)
    return result
def review(db,id,data,user):
    initial=get(db,Triage,id);case=get(db,Intake,initial.intake_id,True);row=get(db,Triage,id,True)
    reject(row.status!='done','等待分流完成再复核')
    reject(row.facts_version!=case.facts_version,'事实已更正，请重新分流')
    reject(not authorized(db,case.id),'来访授权已撤回')
    row.approved=data.topic;row.review_note=data.note;row.status='reviewed';return finish(db,user,'专长人工复核',row)
