# AI 生成功能测试（真实调用 DeepSeek API）
from app import app, db
from models import Contract

client = app.test_client()

# 1. GET 生成页面
r = client.get("/generate")
assert r.status_code == 200
assert "DeepSeek" in r.get_data(as_text=True)
print("1. 生成页面 OK")

# 2. POST 真实生成（调用 DeepSeek）
r = client.post("/generate", data={
    "category": "purchase", "industry": "信息技术",
    "title": "", "extra": "合同期限一年",
})
html = r.get_data(as_text=True)
assert r.status_code == 200
assert "生成结果" in html, "未出现结果区域：" + html[:500]
assert "保存为合同" in html
print("2. AI 生成 OK")

# 3. 保存生成结果为合同（直接用文本内容，不重复调用 API）
content = "采购合同\n\n甲方：【甲方名称】\n乙方：【乙方名称】\n\n第一条 采购物资……"
r = client.post("/save_generated", data={
    "title": "AI测试合同", "category": "purchase", "content": content,
}, follow_redirects=True)
assert r.status_code == 200
with app.app_context():
    c = Contract.query.filter_by(title="AI测试合同").first()
    assert c and c.status == "pending" and c.uploader == "AI生成"
    cid = c.id
print("3. 保存为合同 OK, id =", cid)

# 4. 保存的 txt 可在线查看
r = client.get(f"/file/{cid}")
assert r.status_code == 200
assert "第一条" in r.get_data(as_text=True)
print("4. 范本文件查看 OK")

# 5. 走完整审核归档流程
client.post(f"/review/{cid}", data={"action": "approve", "reviewer": "王五"}, follow_redirects=True)
client.post(f"/archive/{cid}", follow_redirects=True)
with app.app_context():
    assert db.session.get(Contract, cid).status == "archived"
print("5. AI 范本审核归档 OK")

print("\nAI 功能测试全部通过")
