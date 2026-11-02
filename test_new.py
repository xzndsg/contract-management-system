# 新功能测试：字段提取 + 投标系统（真实 DeepSeek API）
import io
from app import app, db
from models import Bid, Contract, FieldExtraction

client = app.test_client()

with app.app_context():
    db.create_all()
    Contract.query.delete()
    Bid.query.delete()
    FieldExtraction.query.delete()
    db.session.commit()

# ========== 第一部分：合同智能字段提取 ==========

SAMPLE_CONTRACT = """采购合同

合同编号：CG-2026-001
甲方：华远建筑工程有限公司
乙方：宏达钢铁材料厂
签署日期：2026年8月15日

第一条 采购标的
甲方向乙方采购螺纹钢 1000 吨。

第二条 合同金额
合同总金额为人民币 5800000 元整（大写：伍佰捌拾万元整）。

第三条 合同期限
合同有效期自 2026年9月1日 起至 2027年8月31日 止。

第四条 争议解决
因本合同产生的争议，双方协商解决；协商不成的，提交合同签订地人民法院诉讼解决。

甲方（盖章）：华远建筑工程有限公司
乙方（盖章）：宏达钢铁材料厂
"""

# 上传合同
r = client.post("/upload", data={
    "title": "螺纹钢采购合同", "category": "purchase", "uploader": "测试",
    "file": (io.BytesIO(SAMPLE_CONTRACT.encode("utf-8")), "采购合同.txt"),
}, content_type="multipart/form-data", follow_redirects=True)
assert r.status_code == 200
with app.app_context():
    cid = Contract.query.first().id
print(f"1. 合同上传 OK, id={cid}")

# 真实 AI 字段提取
r = client.get(f"/contract/{cid}/extract")
html = r.get_data(as_text=True)
assert r.status_code == 200
with app.app_context():
    ex = FieldExtraction.query.filter_by(contract_id=cid).first()
    assert ex and len(ex.field_dict) >= 4, ex.field_dict
print(f"2. 合同字段提取 OK: {ex.field_dict}")

# ========== 第二部分：投标系统 ==========

SAMPLE_BID = """投标文件

项目编号：ZC-2026-智慧城市-007
项目名称：2026年智慧城市建设项目（一期）
招标单位：广东省发展和改革委员会
竞标方：深圳智能科技股份有限公司
竞标方联系人：李明
竞标方联系电话：13800138000
竞标方邮箱：liming@szsmart.com
投标金额：人民币 28000000 元整
投标截止日期：2026年11月20日
投标日期：2026年11月15日

三、报价明细
智慧城市平台开发：20000000元（1项）
数据采集系统：5000000元（1项）
运维服务：3000000元（3年）
合计：28000000元

四、服务承诺
我方承诺服务质量达到国家信息安全等级保护三级标准。
"""

# 上传投标文件
r = client.post("/bids/upload", data={
    "title": "智慧城市项目投标文件", "uploader": "测试",
    "file": (io.BytesIO(SAMPLE_BID.encode("utf-8")), "投标文件.txt"),
}, content_type="multipart/form-data", follow_redirects=True)
assert r.status_code == 200
with app.app_context():
    bid_id = Bid.query.first().id
print(f"3. 投标文件上传 OK, id={bid_id}")

# OCR + 字段提取
r = client.post(f"/bids/{bid_id}/extract", follow_redirects=True)
assert r.status_code == 200
with app.app_context():
    bid = db.session.get(Bid, bid_id)
    assert bid.status in ("extracted", "ocred"), f"unexpected status: {bid.status}"
    print(f"4. 投标 OCR + 提取 OK, status={bid.status}")
    if bid.field_dict:
        print(f"   提取字段: {bid.field_dict}")

# 模板生成（GET 进入填写页）
r = client.get(f"/bids/{bid_id}/template")
html = r.get_data(as_text=True)
assert r.status_code == 200
print("5. 模板生成页 OK")

# 模板生成（POST 提交，用提取的字段）
with app.app_context():
    bid = db.session.get(Bid, bid_id)
    field_values = {f"var_{k}": v for k, v in bid.field_dict.items() if v}
    field_values["var_明细1名称"] = "智慧城市平台开发"
    field_values["var_明细1单价"] = "20000000"
    field_values["var_明细1数量"] = "1"
    field_values["var_明细1小计"] = "20000000"
    field_values["var_明细2名称"] = "数据采集系统"
    field_values["var_明细2单价"] = "5000000"
    field_values["var_明细2数量"] = "1"
    field_values["var_明细2小计"] = "5000000"
    field_values["var_服务标准"] = "国家等保三级"

r = client.post(f"/bids/{bid_id}/template", data=field_values, follow_redirects=True)
assert r.status_code == 200
with app.app_context():
    bid = db.session.get(Bid, bid_id)
    assert bid.status == "generated" and bid.generated_doc
print("6. 投标文档生成 OK, status=generated")

# 查看生成的文档
r = client.get(f"/bids/{bid_id}/view")
text = r.get_data(as_text=True)
assert "智慧城市" in text and "竞标方" in text
print("7. 投标文档查看 OK（已模板化生成）")

print("\n新功能测试全部通过 ✓")
