import json
import os
import uuid
from datetime import datetime

import requests
from flask import (Flask, abort, flash, redirect, render_template, request,
                   send_from_directory, url_for)
from models import (BID_TEMPLATE, CATEGORIES, INDUSTRIES, STATUS,
                    Bid, Contract, FieldExtraction, Template,
                    db, extract_contract_text)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config["SECRET_KEY"] = "contract-demo"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "contracts.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = os.path.join(BASE_DIR, "uploads")
app.config["BID_FOLDER"] = os.path.join(BASE_DIR, "bids")          # 投标文件单独目录
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB

ALLOWED_EXTENSIONS = {"doc", "docx", "pdf", "txt"}

# DeepSeek 大模型配置（必须通过环境变量 DEEPSEEK_API_KEY 注入，勿硬编码提交到仓库）
app.config["DEEPSEEK_API_KEY"] = os.environ.get("DEEPSEEK_API_KEY", "")
app.config["DEEPSEEK_API_URL"] = "https://api.deepseek.com/chat/completions"
app.config["DEEPSEEK_MODEL"] = "deepseek-chat"

db.init_app(app)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/guide")
def guide():
    """业务指引：完整业务流程说明"""
    return render_template("guide.html")


@app.route("/")
def index():
    """合同列表，支持按分类、状态、关键词筛选"""
    category = request.args.get("category", "")
    status = request.args.get("status", "")
    keyword = request.args.get("keyword", "").strip()

    query = Contract.query
    if category:
        query = query.filter_by(category=category)
    if status:
        query = query.filter_by(status=status)
    if keyword:
        query = query.filter(Contract.title.contains(keyword))

    contracts = query.order_by(Contract.created_at.desc()).all()

    # 各状态数量统计
    stats = {
        "total": Contract.query.count(),
        "pending": Contract.query.filter_by(status="pending").count(),
        "approved": Contract.query.filter_by(status="approved").count(),
        "archived": Contract.query.filter_by(status="archived").count(),
    }
    return render_template("index.html", contracts=contracts, categories=CATEGORIES,
                           status_map=STATUS, stats=stats,
                           sel_category=category, sel_status=status, keyword=keyword)


@app.route("/upload", methods=["GET", "POST"])
def upload():
    """上传合同"""
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "")
        uploader = request.form.get("uploader", "").strip()
        file = request.files.get("file")

        if not title or category not in CATEGORIES:
            flash("请填写合同名称并选择正确的分类", "error")
            return redirect(url_for("upload"))
        if not file or not file.filename:
            flash("请选择要上传的文件", "error")
            return redirect(url_for("upload"))
        if not allowed_file(file.filename):
            flash("仅支持 Word(doc/docx) 或 PDF 文件", "error")
            return redirect(url_for("upload"))

        # 按分类分目录保存，文件名加 uuid 防重名
        ext = file.filename.rsplit(".", 1)[1].lower()
        save_dir = os.path.join(app.config["UPLOAD_FOLDER"], category)
        os.makedirs(save_dir, exist_ok=True)
        save_name = f"{uuid.uuid4().hex}_{file.filename}"
        file.save(os.path.join(save_dir, save_name))

        contract = Contract(title=title, category=category, filename=save_name,
                            original_filename=file.filename, uploader=uploader)
        db.session.add(contract)
        db.session.commit()
        flash("合同上传成功，等待审核", "success")
        return redirect(url_for("index"))

    return render_template("upload.html", categories=CATEGORIES)


@app.route("/review/<int:cid>", methods=["GET", "POST"])
def review(cid):
    """业务人员审核合同"""
    contract = Contract.query.get_or_404(cid)
    if request.method == "POST":
        action = request.form.get("action")  # approve / reject
        comment = request.form.get("comment", "").strip()
        reviewer = request.form.get("reviewer", "").strip() or "业务员"

        if contract.status != "pending":
            flash("该合同已审核，请勿重复操作", "error")
            return redirect(url_for("index"))

        contract.review_comment = comment
        contract.reviewer = reviewer
        contract.reviewed_at = datetime.now()
        contract.status = "approved" if action == "approve" else "rejected"
        db.session.commit()
        flash(f"审核完成：{contract.status_name}", "success")
        return redirect(url_for("index"))

    return render_template("review.html", contract=contract)


@app.route("/archive/<int:cid>", methods=["POST"])
def archive(cid):
    """审核通过后归档"""
    contract = Contract.query.get_or_404(cid)
    if contract.status != "approved":
        flash("仅审核通过的合同可以归档", "error")
        return redirect(url_for("index"))
    contract.status = "archived"
    contract.archived_at = datetime.now()
    db.session.commit()
    flash("合同已归档", "success")
    return redirect(url_for("index"))


@app.route("/file/<int:cid>")
def view_file(cid):
    """在线查看/下载合同文件"""
    contract = Contract.query.get_or_404(cid)
    return send_from_directory(os.path.join(app.config["UPLOAD_FOLDER"], contract.category),
                               contract.filename, as_attachment=False,
                               download_name=contract.original_filename)


def call_llm(messages, temperature=0.3, timeout=120, response_json=False):
    """通用 LLM 调用底层函数"""
    payload = {
        "model": app.config["DEEPSEEK_MODEL"],
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if response_json:
        payload["response_format"] = {"type": "json_object"}
    resp = requests.post(
        app.config["DEEPSEEK_API_URL"],
        headers={"Authorization": f"Bearer {app.config['DEEPSEEK_API_KEY']}"},
        json=payload, timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def call_deepseek(category_name, industry, extra=""):
    """调用 DeepSeek 生成合同范本（纯文本）。LLM 失败则返回内置模板。"""
    try:
        prompt = (
            f"你是一名专业的合同法律顾问。请生成一份适用于「{industry}」行业的"
            f"「{category_name}」合同范本。\n"
            "要求：\n"
            "1. 使用纯文本格式（不要用 Markdown 符号），条款用中文数字编号（第一条、第二条…）\n"
            "2. 结构完整：合同编号、甲方乙方信息（用占位符如【甲方名称】）、"
            "鉴于条款、8~12 条核心条款、违约责任、争议解决、签署栏\n"
            "3. 条款内容需贴合该行业的业务特点，符合《中华人民共和国民法典》相关规定\n"
            "4. 只输出合同正文，不要额外解释说明\n"
        )
        if extra:
            prompt += f"5. 额外要求：{extra}\n"

        return call_llm([
            {"role": "system", "content": "你是专业的合同起草律师，输出格式规范的合同范本。"},
            {"role": "user", "content": prompt},
        ], temperature=0.7)
    except Exception as e:
        print(f"[AI 生成降级：{e}] 使用内置模板")
        return (
            f"{category_name}\n\n"
            "合同编号：【合同编号】\n"
            "甲方：【甲方名称】\n"
            "乙方：【乙方名称】\n"
            f"鉴于：甲乙双方就{industry}领域合作事宜，达成以下协议：\n\n"
            "第一条 合同标的：【合同标的】\n"
            "第二条 合同金额：【合同金额】元\n"
            "第三条 合同期限：【合同期限】\n"
            "第四条 付款方式：【付款方式】\n"
            "第五条 权利义务：【权利义务条款】\n"
            "第六条 违约责任：【违约责任条款】\n"
            "第七条 争议解决：【争议解决方式】\n"
            "第八条 其他约定：【其他约定】\n\n"
            "甲方（盖章）：____________________\n"
            "乙方（盖章）：____________________\n"
            "签署日期：【签署日期】"
        )


def regex_extract_fields(text):
    """正则兜底：从合同文本提取常用字段（LLM 不可用时降级）"""
    import re
    fields = {}
    patterns = [
        ("合同编号", r"(?:合同编号|协议编号)[：:\s]*([^\s，。\n]+)"),
        ("合同金额", r"(?:合同金额|总金额|价款)[：:\s]*人民币?\s*([\d,.\s]+)元"),
        ("签署日期", r"(?:签署日期|签订日期|订立日期)[：:\s]*(\d{4}年\d{1,2}月\d{1,2}日|\d{4}[/-]\d{1,2}[/-]\d{1,2})"),
        ("甲方名称", r"(?:甲方)[：:\s]*([^\s，。\n（(]+)"),
        ("乙方名称", r"(?:乙方)[：:\s]*([^\s，。\n（(]+)"),
        ("合同期限", r"(?:合同期限|合同有效期)[：:\s]*([^\n]+)"),
        ("合同标的", r"(?:合同标的|采购标的|标的)[：:\s]*([^\n]+)"),
        ("争议解决方式", r"(?:争议解决|解决方式)[：:\s]*([^\n]+)"),
    ]
    for key, pat in patterns:
        m = re.search(pat, text)
        if m:
            fields[key] = m.group(1).strip()
    return fields


def extract_contract_fields_with_llm(raw_text):
    """用 DeepSeek 从合同文本提取关键字段，返回 dict。LLM 失败则降级为正则提取。"""
    import json as _json

    fields = regex_extract_fields(raw_text)

    keys = FieldExtraction.FIELD_KEYS

    # 先尝试 LLM 增强
    try:
        prompt_keys = ", ".join(keys)
        prompt = (
            "请从下面的合同文本中提取以下字段的值。"
            f"字段列表：{prompt_keys}\n"
            "如果某个字段未找到，值填空字符串。只输出 JSON，不要解释。\n\n"
            f"合同文本：\n{(raw_text[:7000] + '...') if len(raw_text) > 7000 else raw_text}"
        )
        raw = call_llm([
            {"role": "system", "content": "你是合同信息提取专家，只输出 JSON。"},
            {"role": "user", "content": prompt},
        ], temperature=0.1, response_json=True, timeout=30)

        try:
            llm_data = _json.loads(raw)
        except _json.JSONDecodeError:
            import re as _re
            m = _re.search(r"\{.*\}", raw, _re.S)
            llm_data = _json.loads(m.group(0)) if m else {}

        # LLM 结果合并（非空值覆盖正则）
        for k in keys:
            v = str(llm_data.get(k, "")).strip()
            if v:
                fields[k] = v
    except Exception as e:
        print(f"[LLM 降级：{e}] 使用正则兜底提取")

    return {k: fields.get(k, "") for k in keys}


def regex_extract_bid_fields(text):
    """正则兜底：从投标文档提取关键字段"""
    import re
    keys = [
        "项目编号", "项目名称", "招标单位", "竞标方",
        "竞标方联系人", "竞标方联系电话", "竞标方邮箱",
        "投标金额", "投标截止日期", "投标日期",
    ]
    patterns = {
        "项目编号": r"(?:项目编号|招标编号)[：:\s]*([^\s，。\n]+)",
        "项目名称": r"(?:项目名称|工程名称)[：:\s]*([^\n]+)",
        "招标单位": r"(?:招标单位|采购人|招标人)[：:\s]*([^\s，。\n]+)",
        "竞标方": r"(?:竞标方|投标方|供应商|投标人)[：:\s]*([^\s，。\n（(]+)",
        "竞标方联系人": r"(?:联系人|投标联系人)[：:\s]*([^\s，。\n]+)",
        "竞标方联系电话": r"(?:联系电话|电话)[：:\s]*(1[3-9]\d{9}|[0-9\-]+)",
        "竞标方邮箱": r"(?:邮箱|E-mail)[：:\s]*([\w.+-]+@[\w-]+\.[\w.-]+)",
        "投标金额": r"(?:投标金额|报价|总价|合计)[：:\s]*人民币?\s*([\d,.\s]+)元",
        "投标截止日期": r"(?:投标截止|截止日期|开标时间)[：:\s]*(\d{4}年\d{1,2}月\d{1,2}日)",
        "投标日期": r"(?:投标日期|递交日期)[：:\s]*(\d{4}年\d{1,2}月\d{1,2}日)",
    }
    fields = {}
    for k in keys:
        pat = patterns.get(k, r"")
        if pat:
            m = re.search(pat, text)
            if m:
                fields[k] = m.group(1).strip()
    return fields


def extract_bid_fields_with_llm(raw_text):
    """从投标文档 OCR 文本提取投标字段。LLM 失败则降级正则。"""
    import json as _json

    fields = regex_extract_bid_fields(raw_text)

    keys = [
        "项目编号", "项目名称", "招标单位", "竞标方",
        "竞标方联系人", "竞标方联系电话", "竞标方邮箱",
        "投标金额", "投标截止日期", "投标日期",
        "服务标准", "明细1名称", "明细1单价", "明细1数量",
        "明细1小计", "明细2名称", "明细2单价", "明细2数量", "明细2小计",
    ]

    try:
        prompt = (
            "请从下面的投标文档中提取以下字段的值。"
            f"字段列表：{', '.join(keys)}\n"
            "如果某个字段未找到，值填空字符串。只输出 JSON，不要解释。\n\n"
            f"投标文档：\n{(raw_text[:7000] + '...') if len(raw_text) > 7000 else raw_text}"
        )
        raw = call_llm([
            {"role": "system", "content": "你是投标文档信息提取专家，只输出 JSON。"},
            {"role": "user", "content": prompt},
        ], temperature=0.1, response_json=True, timeout=30)

        try:
            llm_data = _json.loads(raw)
        except _json.JSONDecodeError:
            import re as _re
            m = _re.search(r"\{.*\}", raw, _re.S)
            llm_data = _json.loads(m.group(0)) if m else {}

        for k in keys:
            v = str(llm_data.get(k, "")).strip()
            if v:
                fields[k] = v
    except Exception as e:
        print(f"[投标 LLM 降级：{e}] 使用正则兜底提取")

    return {k: fields.get(k, "") for k in keys}


@app.route("/generate", methods=["GET", "POST"])
def generate():
    """AI 生成合同范本"""
    generated = None
    form = {"category": "", "industry": "", "title": "", "extra": ""}

    if request.method == "POST":
        form["category"] = request.form.get("category", "")
        form["industry"] = request.form.get("industry", "").strip()
        form["title"] = request.form.get("title", "").strip()
        form["extra"] = request.form.get("extra", "").strip()

        if form["category"] not in CATEGORIES or not form["industry"]:
            flash("请选择合同分类并填写行业类型", "error")
        else:
            try:
                content = call_deepseek(CATEGORIES[form["category"]],
                                        form["industry"], form["extra"])
                generated = {
                    "title": form["title"] or f"{form['industry']}行业{CATEGORIES[form['category']]}范本",
                    "content": content,
                }
                flash("合同范本生成成功，可保存为合同进入审核流程", "success")
            except Exception as e:
                flash(f"AI 生成失败：{e}", "error")

    return render_template("generate.html", categories=CATEGORIES,
                           industries=INDUSTRIES, generated=generated, form=form)


@app.route("/save_generated", methods=["POST"])
def save_generated():
    """将 AI 生成的文本范本保存为合同（.txt 文件），进入待审核状态"""
    title = request.form.get("title", "").strip()
    category = request.form.get("category", "")
    content = request.form.get("content", "")

    if not title or category not in CATEGORIES or not content.strip():
        flash("范本信息不完整，无法保存", "error")
        return redirect(url_for("generate"))

    save_dir = os.path.join(app.config["UPLOAD_FOLDER"], category)
    os.makedirs(save_dir, exist_ok=True)
    save_name = f"{uuid.uuid4().hex}_AI范本.txt"
    with open(os.path.join(save_dir, save_name), "w", encoding="utf-8") as f:
        f.write(content)

    contract = Contract(title=title, category=category, filename=save_name,
                        original_filename=f"{title}.txt", uploader="AI生成")
    db.session.add(contract)
    db.session.commit()
    flash("范本已保存为合同，等待审核", "success")
    return redirect(url_for("index"))


# ========== 固定范本管理 ==========

@app.route("/templates")
def template_list():
    """固定范本列表"""
    category = request.args.get("category", "")
    keyword = request.args.get("keyword", "").strip()
    query = Template.query
    if category:
        query = query.filter_by(category=category)
    if keyword:
        query = query.filter(Template.title.contains(keyword))
    templates = query.order_by(Template.updated_at.desc()).all()
    stats = {
        "total": Template.query.count(),
    }
    return render_template("templates.html", templates=templates, categories=CATEGORIES,
                           stats=stats, sel_category=category, keyword=keyword)


@app.route("/templates/new", methods=["GET", "POST"])
def template_new():
    """新建固定范本（直接撰写或基于 AI 生成结果）"""
    form = {"title": "", "category": "", "industry": "", "content": ""}
    if request.method == "POST":
        form["title"] = request.form.get("title", "").strip()
        form["category"] = request.form.get("category", "")
        form["industry"] = request.form.get("industry", "").strip()
        form["content"] = request.form.get("content", "")

        if not form["title"] or form["category"] not in CATEGORIES or not form["content"].strip():
            flash("请填写完整范本信息", "error")
            return render_template("template_edit.html", form=form, categories=CATEGORIES,
                                   industries=INDUSTRIES, mode="new")

        tmpl = Template(title=form["title"], category=form["category"],
                        industry=form["industry"], content=form["content"])
        tmpl.refresh_variables()
        db.session.add(tmpl)
        db.session.commit()
        flash("固定范本已创建", "success")
        return redirect(url_for("template_list"))

    return render_template("template_edit.html", form=form, categories=CATEGORIES,
                           industries=INDUSTRIES, mode="new")


@app.route("/templates/<int:tid>", methods=["GET", "POST"])
def template_edit(tid):
    """编辑固定范本（可修改内容，变量自动重新提取）"""
    tmpl = Template.query.get_or_404(tid)
    if request.method == "POST":
        tmpl.title = request.form.get("title", "").strip()
        tmpl.category = request.form.get("category", "")
        tmpl.industry = request.form.get("industry", "").strip()
        tmpl.content = request.form.get("content", "")
        tmpl.refresh_variables()
        db.session.commit()
        flash("范本已更新，变量已重新提取", "success")
        return redirect(url_for("template_list"))

    form = {
        "title": tmpl.title, "category": tmpl.category,
        "industry": tmpl.industry or "", "content": tmpl.content,
    }
    return render_template("template_edit.html", form=form, categories=CATEGORIES,
                           industries=INDUSTRIES, mode="edit", tid=tid,
                           variables=tmpl.variable_list)


@app.route("/templates/<int:tid>/use", methods=["GET", "POST"])
def template_use(tid):
    """使用固定范本：填写变量，一键生成合同"""
    tmpl = Template.query.get_or_404(tid)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("请填写合同名称", "error")
            return redirect(url_for("template_use", tid=tid))

        # 替换所有【变量】
        content = tmpl.content
        for var_name in tmpl.variable_list:
            val = request.form.get(f"var_{var_name}", "")
            content = content.replace(f"【{var_name}】", val)

        # 保存为合同 .txt
        save_dir = os.path.join(app.config["UPLOAD_FOLDER"], tmpl.category)
        os.makedirs(save_dir, exist_ok=True)
        save_name = f"{uuid.uuid4().hex}_范本合同.txt"
        with open(os.path.join(save_dir, save_name), "w", encoding="utf-8") as f:
            f.write(content)

        contract = Contract(title=title, category=tmpl.category,
                            filename=save_name,
                            original_filename=f"{title}.txt",
                            uploader="范本拟定")
        db.session.add(contract)
        db.session.commit()
        flash("合同已根据范本生成，等待审核", "success")
        return redirect(url_for("index"))

    return render_template("template_use.html", tmpl=tmpl, categories=CATEGORIES)


@app.route("/templates/<int:tid>/delete", methods=["POST"])
def template_delete(tid):
    """删除固定范本"""
    tmpl = Template.query.get_or_404(tid)
    db.session.delete(tmpl)
    db.session.commit()
    flash("范本已删除", "success")
    return redirect(url_for("template_list"))


# ========== 合同智能字段提取 ==========

@app.route("/contract/<int:cid>/extract", methods=["GET", "POST"])
def contract_extract(cid):
    """对某份合同执行字段提取（首次自动创建记录，后续可查看/更新）"""
    contract = Contract.query.get_or_404(cid)
    save_dir = os.path.join(app.config["UPLOAD_FOLDER"], contract.category)
    filepath = os.path.join(save_dir, contract.filename)

    extraction = FieldExtraction.query.filter_by(contract_id=cid).first()

    if request.method == "POST" or extraction is None:
        # 1. 提取文本
        if not os.path.exists(filepath):
            abort(404, description="合同文件不存在")
        raw_text = extract_contract_text(filepath)

        # 2. 调 DeepSeek 提取字段
        try:
            fields = extract_contract_fields_with_llm(raw_text)
        except Exception as e:
            flash(f"AI 提取失败：{e}", "error")
            fields = {}

        if extraction is None:
            extraction = FieldExtraction(contract_id=cid, raw_text=raw_text,
                                         fields=json.dumps(fields, ensure_ascii=False))
            db.session.add(extraction)
        else:
            extraction.raw_text = raw_text
            extraction.fields = json.dumps(fields, ensure_ascii=False)
        db.session.commit()
        flash("字段提取完成", "success")

    return render_template("field_extract.html", contract=contract, extraction=extraction)


# ========== 投标系统 ==========

@app.route("/bids")
def bid_list():
    """投标文件列表"""
    keyword = request.args.get("keyword", "").strip()
    query = Bid.query
    if keyword:
        query = query.filter(Bid.title.contains(keyword))
    bids = query.order_by(Bid.created_at.desc()).all()
    return render_template("bid_list.html", bids=bids, keyword=keyword)


@app.route("/bids/upload", methods=["GET", "POST"])
def bid_upload():
    """上传投标 PDF"""
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        uploader = request.form.get("uploader", "").strip()
        file = request.files.get("file")

        if not title or not file or not file.filename:
            flash("请填写标题并选择文件", "error")
            return redirect(url_for("bid_upload"))
        if not allowed_file(file.filename):
            flash("仅支持 PDF / Word 文件", "error")
            return redirect(url_for("bid_upload"))

        os.makedirs(app.config["BID_FOLDER"], exist_ok=True)
        save_name = f"{uuid.uuid4().hex}_{file.filename}"
        file.save(os.path.join(app.config["BID_FOLDER"], save_name))

        bid = Bid(title=title, filename=save_name, original_filename=file.filename)
        db.session.add(bid)
        db.session.commit()
        flash("投标文件上传成功", "success")
        return redirect(url_for("bid_list"))

    return render_template("bid_upload.html")


@app.route("/bids/<int:bid_id>/extract", methods=["POST"])
def bid_extract(bid_id):
    """OCR + 信息提取（一步完成）"""
    bid = Bid.query.get_or_404(bid_id)
    filepath = os.path.join(app.config["BID_FOLDER"], bid.filename)
    if not os.path.exists(filepath):
        abort(404)

    flash("正在 OCR 识别…", "success")
    bid.raw_text = extract_contract_text(filepath)
    bid.status = "ocred"
    db.session.commit()

    try:
        flash("正在提取投标字段…", "success")
        fields = extract_bid_fields_with_llm(bid.raw_text)
        bid.fields = json.dumps(fields, ensure_ascii=False)
        bid.status = "extracted"
        db.session.commit()
        flash("投标信息提取完成", "success")
    except Exception as e:
        flash(f"提取失败：{e}", "error")

    return redirect(url_for("bid_list"))


@app.route("/bids/<int:bid_id>/template", methods=["GET", "POST"])
def bid_template(bid_id):
    """模板生成 + 自动化填写"""
    bid = Bid.query.get_or_404(bid_id)
    fields = bid.field_dict

    if request.method == "POST":
        # 合并用户修改后的值
        for key in fields:
            val = request.form.get(f"var_{key}", "").strip()
            if val:
                fields[key] = val

        content = BID_TEMPLATE
        for key, val in fields.items():
            content = content.replace(f"【{key}】", val)

        os.makedirs(app.config["BID_FOLDER"], exist_ok=True)
        doc_name = f"{uuid.uuid4().hex}_投标文档.txt"
        doc_path = os.path.join(app.config["BID_FOLDER"], doc_name)
        with open(doc_path, "w", encoding="utf-8") as f:
            f.write(content)

        bid.fields = json.dumps(fields, ensure_ascii=False)
        bid.generated_doc = doc_name
        bid.status = "generated"
        db.session.commit()
        flash("投标文档已生成，可查看/下载", "success")
        return redirect(url_for("bid_list"))

    return render_template("bid_template.html", bid=bid, fields=fields,
                           template_text=BID_TEMPLATE)


@app.route("/bids/<int:bid_id>/view")
def bid_view(bid_id):
    """查看/下载生成的投标文档"""
    bid = Bid.query.get_or_404(bid_id)
    if not bid.generated_doc:
        abort(404)
    return send_from_directory(app.config["BID_FOLDER"], bid.generated_doc,
                               as_attachment=False, download_name=f"{bid.title}_投标文档.txt")


@app.route("/bids/<int:bid_id>/delete", methods=["POST"])
def bid_delete(bid_id):
    bid = Bid.query.get_or_404(bid_id)
    for fname in [bid.filename, bid.generated_doc]:
        if fname:
            p = os.path.join(app.config["BID_FOLDER"], fname)
            if os.path.exists(p):
                os.remove(p)
    db.session.delete(bid)
    db.session.commit()
    flash("投标文件已删除", "success")
    return redirect(url_for("bid_list"))


@app.route("/delete/<int:cid>", methods=["POST"])
def delete(cid):
    """删除合同（含文件）"""
    contract = Contract.query.get_or_404(cid)
    path = os.path.join(app.config["UPLOAD_FOLDER"], contract.category, contract.filename)
    if os.path.exists(path):
        os.remove(path)
    db.session.delete(contract)
    db.session.commit()
    flash("合同已删除", "success")
    return redirect(url_for("index"))


if __name__ == "__main__":
    with app.app_context():
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
        db.create_all()
    app.run(debug=True, port=5000)
