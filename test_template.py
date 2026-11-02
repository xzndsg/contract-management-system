# 固定范本功能测试
from app import app, db
from models import Contract, Template, extract_variables

client = app.test_client()

with app.app_context():
    db.create_all()
    Template.query.delete()
    Contract.query.delete()
    db.session.commit()

SAMPLE = """采购合同

甲方：【甲方名称】
乙方：【乙方名称】

第一条 甲方向乙方采购【货物名称】，数量为【数量】。
第二条 合同总金额为【合同金额】元。
第三条 付款方式：甲方在【付款期限】内支付。

甲方（盖章）：【甲方名称】
乙方（盖章）：【乙方名称】
"""

# 1. 变量提取函数
vars_extracted = extract_variables(SAMPLE)
assert vars_extracted == ["甲方名称", "乙方名称", "货物名称", "数量", "合同金额", "付款期限"], vars_extracted
print("1. 变量提取 OK:", vars_extracted)

# 2. 新建范本（模拟从 generate 页面提交）
r = client.post("/templates/new", data={
    "title": "通用采购合同范本", "category": "purchase",
    "industry": "制造业", "content": SAMPLE,
}, follow_redirects=True)
assert r.status_code == 200
with app.app_context():
    t = Template.query.filter_by(title="通用采购合同范本").first()
    assert t and len(t.variable_list) == 6
    tid = t.id
print("2. 新建范本 OK, id =", tid)

# 3. 编辑范本：修改内容后变量自动重新提取
r = client.post(f"/templates/{tid}", data={
    "title": "通用采购合同范本V2", "category": "purchase",
    "industry": "制造业", "content": SAMPLE + "\n第四条 交货地点：【交货地点】。\n",
}, follow_redirects=True)
with app.app_context():
    t = db.session.get(Template, tid)
    assert t.title.endswith("V2") and len(t.variable_list) == 7
print("3. 编辑范本并重提取变量 OK")

# 4. 使用范本生成合同
r = client.post(f"/templates/{tid}/use", data={
    "title": "钢材采购合同",
    "var_甲方名称": "华远建筑公司", "var_乙方名称": "宏达钢材厂",
    "var_货物名称": "螺纹钢", "var_数量": "100吨",
    "var_合同金额": "500000", "var_付款期限": "30日",
    "var_交货地点": "上海市宝山区",
}, follow_redirects=True)
assert r.status_code == 200
with app.app_context():
    c = Contract.query.filter_by(title="钢材采购合同").first()
    assert c and c.status == "pending" and c.uploader == "范本拟定"
    cid = c.id
print("4. 范本生成合同 OK, id =", cid)

# 5. 生成的合同内容变量已替换
r = client.get(f"/file/{cid}")
text = r.get_data(as_text=True)
assert "华远建筑公司" in text and "【" not in text
print("5. 变量替换 OK")

# 6. 合同走审核归档流程
client.post(f"/review/{cid}", data={"action": "approve", "reviewer": "赵六"}, follow_redirects=True)
client.post(f"/archive/{cid}", follow_redirects=True)
with app.app_context():
    assert db.session.get(Contract, cid).status == "archived"
print("6. 审核归档 OK")

# 7. 范本列表/筛选
r = client.get("/templates?category=purchase&keyword=采购")
assert "通用采购合同范本V2" in r.get_data(as_text=True)
print("7. 范本列表筛选 OK")

# 8. 删除范本
client.post(f"/templates/{tid}/delete", follow_redirects=True)
with app.app_context():
    assert db.session.get(Template, tid) is None
print("8. 删除范本 OK")

print("\n固定范本测试全部通过")
