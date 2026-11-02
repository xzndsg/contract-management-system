# 冒烟测试：上传 -> 审核 -> 归档 全流程
import io
from app import app, db
from models import Contract

client = app.test_client()

with app.app_context():
    Contract.query.delete()
    db.session.commit()

# 1. 首页
r = client.get("/")
assert r.status_code == 200, r.status_code
print("1. 首页 OK")

# 2. 上传 PDF 合同
r = client.post("/upload", data={
    "title": "测试采购合同",
    "category": "purchase",
    "uploader": "张三",
    "file": (io.BytesIO(b"%PDF-1.4 fake content"), "test.pdf"),
}, content_type="multipart/form-data", follow_redirects=True)
assert r.status_code == 200
with app.app_context():
    c = Contract.query.filter_by(title="测试采购合同").first()
    assert c and c.status == "pending"
    cid = c.id
print("2. 上传 OK, id=", cid)

# 3. 不允许的文件类型
r = client.post("/upload", data={
    "title": "非法文件", "category": "service",
    "file": (io.BytesIO(b"x"), "bad.exe"),
}, content_type="multipart/form-data", follow_redirects=True)
assert "仅支持" in r.get_data(as_text=True)
print("3. 文件类型校验 OK")

# 4. 审核通过
r = client.post(f"/review/{cid}", data={
    "action": "approve", "comment": "同意", "reviewer": "李四",
}, follow_redirects=True)
with app.app_context():
    assert db.session.get(Contract, cid).status == "approved"
print("4. 审核通过 OK")

# 5. 归档
r = client.post(f"/archive/{cid}", follow_redirects=True)
with app.app_context():
    c = db.session.get(Contract, cid)
    assert c.status == "archived" and c.archived_at
print("5. 归档 OK")

# 6. 查看文件
r = client.get(f"/file/{cid}")
assert r.status_code == 200
print("6. 文件查看 OK")

# 7. 驳回流程
r = client.post("/upload", data={
    "title": "被驳回合同", "category": "lease",
    "file": (io.BytesIO(b"doc"), "a.docx"),
}, content_type="multipart/form-data", follow_redirects=True)
with app.app_context():
    cid2 = Contract.query.filter_by(title="被驳回合同").first().id
client.post(f"/review/{cid2}", data={"action": "reject", "comment": "信息不全"}, follow_redirects=True)
with app.app_context():
    assert db.session.get(Contract, cid2).status == "rejected"
# 驳回的合同不能归档
client.post(f"/archive/{cid2}", follow_redirects=True)
with app.app_context():
    assert db.session.get(Contract, cid2).status == "rejected"
print("7. 驳回流程 OK")

# 8. 删除
client.post(f"/delete/{cid2}", follow_redirects=True)
with app.app_context():
    assert db.session.get(Contract, cid2) is None
print("8. 删除 OK")

print("\n全部测试通过")
