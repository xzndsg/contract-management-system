import json
import re
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def extract_variables(content):
    """从范本内容提取【占位符】结构化变量（去重、保持顺序）"""
    seen, result = set(), []
    for name in re.findall(r"【([^】]+)】", content or ""):
        name = name.strip()
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result

# 合同分类
CATEGORIES = {
    "purchase": "采购合同",
    "construction": "建筑合同",
    "service": "服务合同",
    "lease": "租赁合同",
    "transport": "运输合同",
}

# 行业类型（用于 AI 生成合同范本）
INDUSTRIES = [
    "信息技术", "制造业", "建筑工程", "物流运输", "零售贸易",
    "金融服务", "教育培训", "医疗健康", "餐饮服务", "房地产",
]

# 合同状态
STATUS = {
    "pending": "待审核",
    "approved": "审核通过",
    "archived": "已归档",
    "rejected": "已驳回",
}


class Contract(db.Model):
    __tablename__ = "contracts"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)          # 合同名称
    category = db.Column(db.String(50), nullable=False)        # 分类
    filename = db.Column(db.String(300), nullable=False)       # 存储文件名
    original_filename = db.Column(db.String(300))              # 原始文件名
    uploader = db.Column(db.String(50))                        # 上传人
    status = db.Column(db.String(20), default="pending")       # 状态
    review_comment = db.Column(db.String(500))                 # 审核意见
    reviewer = db.Column(db.String(50))                        # 审核人
    created_at = db.Column(db.DateTime, default=datetime.now)  # 上传时间
    reviewed_at = db.Column(db.DateTime)                       # 审核时间
    archived_at = db.Column(db.DateTime)                       # 归档时间

    @property
    def category_name(self):
        return CATEGORIES.get(self.category, self.category)

    @property
    def status_name(self):
        return STATUS.get(self.status, self.status)


class Template(db.Model):
    """固定合同范本（含结构化变量）"""
    __tablename__ = "templates"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)          # 范本名称
    category = db.Column(db.String(50), nullable=False)        # 合同分类
    industry = db.Column(db.String(100))                       # 行业类型
    content = db.Column(db.Text, nullable=False)               # 范本内容（含【变量】）
    variables = db.Column(db.Text, default="[]")               # 变量列表（JSON）
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    @property
    def category_name(self):
        return CATEGORIES.get(self.category, self.category)

    @property
    def variable_list(self):
        try:
            return json.loads(self.variables or "[]")
        except (ValueError, TypeError):
            return []

    def refresh_variables(self):
        """重新提取变量"""
        self.variables = json.dumps(extract_variables(self.content), ensure_ascii=False)


class FieldExtraction(db.Model):
    """合同智能字段提取结果"""
    __tablename__ = "field_extractions"

    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"))
    contract = db.relationship("Contract", backref=db.backref("extractions", lazy=True))
    fields = db.Column(db.Text, default="{}")          # 提取的字段 JSON
    raw_text = db.Column(db.Text)                       # 合同原始文本
    created_at = db.Column(db.DateTime, default=datetime.now)

    # 标准字段
    FIELD_KEYS = [
        "合同编号", "合同金额", "签署日期",
        "甲方名称", "乙方名称",
        "合同期限", "合同标的", "争议解决方式",
    ]

    @property
    def field_dict(self):
        try:
            return json.loads(self.fields or "{}")
        except (ValueError, TypeError):
            return {}


class Bid(db.Model):
    """投标文件（OCR + 信息提取 + 模板生成）"""
    __tablename__ = "bids"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(300), nullable=False)
    original_filename = db.Column(db.String(300))
    raw_text = db.Column(db.Text)                       # OCR 识别的原始文本
    fields = db.Column(db.Text, default="{}")          # 提取的投标字段 JSON
    generated_doc = db.Column(db.String(300))            # 生成的投标文档路径
    status = db.Column(db.String(20), default="uploaded")  # uploaded → ocred → extracted → generated
    created_at = db.Column(db.DateTime, default=datetime.now)

    STATUS = {
        "uploaded": "已上传",
        "ocred": "OCR 完成",
        "extracted": "信息提取完成",
        "generated": "投标文档已生成",
    }

    @property
    def status_name(self):
        return self.STATUS.get(self.status, self.status)

    @property
    def field_dict(self):
        try:
            return json.loads(self.fields or "{}")
        except (ValueError, TypeError):
            return {}


# ========== 内置投标文档模板（供模板生成与自动化填写） ==========
BID_TEMPLATE = """投标文件

项目编号：【项目编号】
项目名称：【项目名称】
招标单位：【招标单位】
竞标方：【竞标方】
竞标方联系人：【竞标方联系人】
竞标方联系电话：【竞标方联系电话】
投标金额：【投标金额】元
投标截止日期：【投标截止日期】

一、投标声明
本竞标方在此郑重声明，本投标文件中的内容真实、准确、完整。

二、方案概述
针对【项目名称】，我方提出以下方案……

三、报价明细
| 项目 | 单价（元） | 数量 | 小计（元） |
|------|-----------|------|-----------|
| 【明细1名称】 | 【明细1单价】 | 【明细1数量】 | 【明细1小计】 |
| 【明细2名称】 | 【明细2单价】 | 【明细2数量】 | 【明细2小计】 |
| 合计 | | | 【投标金额】 |

四、服务承诺
我方承诺服务质量达到【服务标准】要求。

五、联系方式
联系人：【竞标方联系人】
联系电话：【竞标方联系电话】
邮箱：【竞标方邮箱】

竞标方（盖章）：____________________
日期：【投标日期】
"""


def extract_contract_text(filepath):
    """从合同文件提取纯文本内容（PDF 优先用 pdfplumber，txt 直接读）"""
    ext = filepath.rsplit(".", 1)[-1].lower()
    if ext == "txt":
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            with open(filepath, "r", encoding="gbk") as f:
                return f.read()

    # PDF：优先 pdfplumber，没有就尝试 PyPDF2
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                text_parts.append(t)
        return "\n".join(text_parts)
    except Exception:
        pass

    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(filepath)
        return "\n".join(
            (page.extract_text() or "") for page in reader.pages
        )
    except Exception as e:
        return f"[PDF 提取失败：{e}，请安装 pdfplumber 或 PyPDF2]"

