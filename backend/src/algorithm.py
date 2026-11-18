import hashlib
import numpy as np
from sklearn.pipeline import make_pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.metrics import f1_score,recall_score,confusion_matrix
LABELS=['labor','housing','consumer']
THRESHOLD=.68
# 训练模板按版本seed轮换措辞并带版本编号，只用于训练，不得进入考评
TRAIN_BASES={'labor':['工资拖欠 工时 劳动 合同 加班 报酬 单位 用工','公司没有发工资 劳动报酬 加班工时 拖欠薪水','用工单位 劳动合同 薪资 考勤 解除工作'],'housing':['租房 住房 房屋 租赁 押金 房东 退租 维修','租赁房屋到期 房东不退押金 租房维修','住房租约 退租 租金 房屋漏水 物业'],'consumer':['购物 消费 商品 退款 质量 订单 商家 收据','商家出售商品损坏 消费退款 订单 收据','购买电器 商品质量 保修 消费者 退款']}
# 独立考评模板：措辞与训练模板不同，不参与任何版本训练，所有版本共用同一批对比
EVAL_BASES={'labor':['试用期被辞退 工资未结清 社保欠缴 希望调解','离职经济补偿 拖欠加班费 考勤记录 调解'],'housing':['合租提前退租 押金扣除 公摊水电 争议','租约到期续租 房屋漏水报修 中介费用'],'consumer':['网购商品破损 退货被拒 七天无理由 索赔','预付卡余额 门店停业 退款登记 发票']}
def train_texts(seed):
    texts=[];ys=[]
    for label,phrases in TRAIN_BASES.items():
        for i in range(36):texts.append(phrases[(i+seed)%len(phrases)]+f' 模拟行政来访编号{seed}-{i} 请协助登记分流');ys.append(label)
    return texts,ys
def eval_texts():
    texts=[];ys=[]
    for label,phrases in EVAL_BASES.items():
        for i in range(12):texts.append(phrases[i%len(phrases)]+f' 独立考评样例{i} 请协助登记分流');ys.append(label)
    return texts,ys
EVAL_SHA256=hashlib.sha256(chr(10).join(eval_texts()[0]).encode()).hexdigest()
def evaluate(model,texts,ys):
    predicted=model.predict(texts);per=recall_score(ys,predicted,labels=LABELS,average=None,zero_division=0)
    return {'recall':{label:round(float(per[i]),4) for i,label in enumerate(LABELS)},'macro_f1':float(f1_score(ys,predicted,average='macro')),'confusion_matrix':confusion_matrix(ys,predicted,labels=LABELS).tolist(),'labels':LABELS,'eval_count':len(texts),'eval_sha256':EVAL_SHA256}
def predict(model,text):
    proba=model.predict_proba([text])[0];idx=int(np.argmax(proba));return str(model.classes_[idx]),float(proba[idx])
_cache={}
def load_model(version_id,config):
    # 训练并缓存版本模型及其独立考评指标；分流与试跑共用同一口径
    if version_id not in _cache:
        if len(_cache)>=8:_cache.pop(next(iter(_cache)))
        texts,ys=train_texts(int(config.get('seed',34)))
        model=make_pipeline(TfidfVectorizer(analyzer='char',ngram_range=(2,3)),MultinomialNB(alpha=float(config.get('alpha',.5)))).fit(texts,ys)
        eval_x,eval_y=eval_texts();_cache[version_id]=(model,evaluate(model,eval_x,eval_y))
    return _cache[version_id]
