import redis
from fastapi import HTTPException
from sqlalchemy import select
from .models import ModelVersion,ModelRegistry,TrialRun
from .common import get,reject,finish,dump
from .triage_service import queue

def active_id(db):
    row=db.scalar(select(ModelRegistry.active_id).where(ModelRegistry.id==1))
    if row is None:raise HTTPException(409,'模型注册表未初始化，请先完成种子导入')
    return row
def register(db,data,user):
    reject(db.scalar(select(ModelVersion).where(ModelVersion.code==data.code)) is not None,'模型编号重复')
    row=ModelVersion(code=data.code,note=data.note,config={'seed':data.seed,'alpha':data.alpha},status='candidate');db.add(row);db.flush()
    return finish(db,user,'登记候选模型版本',row)
def start_trial(db,id,user):
    candidate=get(db,ModelVersion,id,True)
    reject(candidate.status!='candidate','仅候选版本可发起试跑')
    reject(db.scalar(select(TrialRun).where(TrialRun.model_id==id,TrialRun.status.in_(['queued','running']))) is not None,'该候选已有在途试跑')
    trial=TrialRun(model_id=candidate.id,baseline_id=active_id(db));db.add(trial);db.flush()
    result=finish(db,user,'发起候选模型试跑',trial)
    try:queue.rpush('aid:trial',trial.id)
    except redis.RedisError:
        trial.status='failed';trial.reason='任务队列暂不可用，恢复后可重新发起';db.commit()
        raise HTTPException(503,trial.reason)
    return result
def publish(db,id,user):
    registry=db.scalar(select(ModelRegistry).where(ModelRegistry.id==1).with_for_update())
    if registry is None:raise HTTPException(409,'模型注册表未初始化，请先完成种子导入')
    candidate=get(db,ModelVersion,id,True)
    if registry.active_id==candidate.id:return dump(candidate)  # 发布重试不重复启用
    reject(candidate.status!='candidate','仅候选版本可发布')
    current=get(db,ModelVersion,registry.active_id,True)
    trial=db.scalar(select(TrialRun).where(TrialRun.model_id==candidate.id,TrialRun.status.in_(['passed','blocked'])).order_by(TrialRun.id.desc()))
    reject(trial is None or trial.status!='passed','候选模型尚未通过试跑，不能发布')
    reject(trial.baseline_id!=current.id,'试跑基线已被更新候选覆盖，请重新试跑')
    # 同一事务内切换；任何失败回滚后旧版继续在用
    current.status='retired';candidate.status='active';registry.active_id=candidate.id
    return finish(db,user,'发布候选模型版本',candidate)
