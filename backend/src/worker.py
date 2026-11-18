import logging,time,json,os
from pathlib import Path
from .database import Session
from .models import Triage,Intake,TrialRun,ModelVersion,now
from .triage_service import queue
from .algorithm import LABELS,THRESHOLD,EVAL_SHA256,load_model,predict,evaluate,eval_texts,train_texts
logging.basicConfig(level=logging.INFO)
ZH={'labor':'劳动','housing':'住房','consumer':'消费'}
ARTIFACTS=os.getenv('ARTIFACTS_DIR','/artifacts')
def run_triage(db,tid):
    row=db.get(Triage,tid)
    if not row or row.status!='queued':return
    row.status='running';db.commit()
    try:
        case=db.get(Intake,row.intake_id)
        if case.facts_version!=row.facts_version:raise ValueError('事实版本已更新，请重新提交')
        version=db.get(ModelVersion,row.model_id)
        if version is None:raise ValueError('入队时的模型版本不存在')
        model,metrics=load_model(version.id,version.config)
        row.predicted,row.confidence=predict(model,case.facts);row.manual_required=row.confidence<THRESHOLD
        row.metrics={**metrics,'model_code':version.code,'threshold':THRESHOLD,'source':'独立考评模板（未参与任何版本训练），仅验证内部行政分流；不是法律意见'};row.status='done'
        Path(ARTIFACTS).mkdir(exist_ok=True);Path(ARTIFACTS,f'triage-{row.id}.json').write_text(json.dumps(row.metrics,ensure_ascii=False))
    except Exception as e:row.status='failed';row.error=str(e)[:200]
    db.commit()
def run_trial(db,tid):
    trial=db.get(TrialRun,tid)
    if not trial or trial.status!='queued':return
    trial.status='running';db.commit()
    try:
        candidate=db.get(ModelVersion,trial.model_id);baseline=db.get(ModelVersion,trial.baseline_id)
        if candidate is None or baseline is None:raise ValueError('试跑关联的模型版本不存在')
        eval_x,eval_y=eval_texts()
        for version in (candidate,baseline):
            if set(train_texts(int(version.config.get('seed',34)))[0])&set(eval_x):raise ValueError('考评模板与训练模板相交，试跑无效')
        cand=evaluate(load_model(candidate.id,candidate.config)[0],eval_x,eval_y)
        base=evaluate(load_model(baseline.id,baseline.config)[0],eval_x,eval_y)
        trial.candidate_metrics=cand;trial.baseline_metrics=base;trial.eval_count=len(eval_x);trial.eval_sha256=EVAL_SHA256
        drops=[label for label in LABELS if cand['recall'][label]<base['recall'][label]-1e-9]
        if drops:
            trial.status='blocked';trial.reason='召回率低于现用模型：'+'、'.join(f"{ZH[l]} {cand['recall'][l]:.1%}<{base['recall'][l]:.1%}" for l in drops)+'，阻止发布'
        else:
            trial.status='passed';trial.reason='三主题召回率均不低于现用模型（'+'、'.join(f"{ZH[l]} {cand['recall'][l]:.1%}" for l in LABELS)+'），允许发布'
    except Exception as e:trial.status='failed';trial.reason=str(e)[:300]
    trial.finished_at=now();db.commit()
def main():
    while True:
        Path('/tmp/worker-heartbeat').touch()
        try:
            item=queue.blpop(['aid:trial','aid:triage'],timeout=2)
            if not item:continue
            with Session() as db:
                if item[0]=='aid:trial':run_trial(db,int(item[1]))
                else:run_triage(db,int(item[1]))
        except Exception:logging.exception('worker loop');time.sleep(1)
if __name__=='__main__':main()
