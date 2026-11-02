## 一、 智能合同管理与投标系统

基于 Flask + DeepSeek 大模型的企业级智能合同管理系统，覆盖合同上传、智能字段提取、AI 范本生成、固定范本变量化、快速拟定、审核归档，以及投标文件 OCR 识别、投标信息结构化提取、投标文档模板自动填写两大业务模块。

---

## 二、技术栈

| 类别 | 技术 | 说明 |
|------|------|------|
| 后端框架 | Python 3.11 + Flask | Web 框架 |
| 数据库 | SQLite + Flask-SQLAlchemy | 轻量关系型数据库 |
| 大模型 | DeepSeek Chat | 合同范本生成、字段提取、投标信息提取 |
| 文本提取 | pdfplumber（兜底 PyPDF2） | PDF 合同/投标文件 OCR |
| 前端 | HTML / Jinja2 / CSS | Ant Design 风格 |
| HTTP | requests | DeepSeek API 调用 |

## 三、目录结构

```
test1/
├── app.py                    # 后端路由与业务逻辑
├── models.py                 # 数据模型 + 工具函数
├── requirements.txt          # 依赖清单
├── contracts.db              # SQLite 数据库（运行自动生成）
│
├── templates/                # 前端页面（Jinja2）
│   ├── base.html             # 布局与全局样式（侧边栏 + 设计令牌）
│   ├── guide.html            # 业务流程指引页
│   ├── index.html            # 合同列表
│   ├── upload.html           # 合同上传
│   ├── review.html           # 合同审核
│   ├── field_extract.html    # 合同字段提取结果
│   ├── generate.html         # AI 生成合同范本
│   ├── templates.html        # 固定范本列表
│   ├── template_edit.html    # 范本编辑（变量输入框插入）
│   ├── template_use.html     # 使用范本填写变量
│   ├── bid_list.html         # 投标文件列表
│   ├── bid_upload.html       # 投标文件上传
│   ├── bid_template.html     # 投标模板填写与生成
│
├── uploads/                  # 上传合同文件（按分类分目录）
│   ├── purchase/
│   ├── construction/
│   ├── service/
│   ├── lease/
│   └── transport/
│
├── bids/                     # 投标文件与生成的投标文档
│
├── test_smoke.py             # 冒烟测试（核心回归）
├── test_template.py          # 固定范本功能测试
├── test_ai.py                # AI 生成功能测试
├── test_new.py               # 字段提取 + 投标系统测试
```

## 四、数据模型

### 4.1 Contract（合同）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 主键 |
| title | String(200) | 合同名称 |
| category | String(50) | 分类（purchase/construction/service/lease/transport） |
| filename | String(300) | 存储文件名 |
| original_filename | String(300) | 原始文件名 |
| uploader | String(50) | 上传人 |
| status | String(20) | 状态：pending/approved/archived/rejected |
| review_comment | String(500) | 审核意见 |
| reviewer | String(50) | 审核人 |
| created_at | DateTime | 上传时间 |
| reviewed_at | DateTime | 审核时间 |
| archived_at | DateTime | 归档时间 |

### 4.2 FieldExtraction（合同字段提取）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 主键 |
| contract_id | Integer FK | 关联合同 |
| fields | Text | 提取字段 JSON（含合同编号/金额/签署日期/甲乙双方/期限/标的/争议解决） |
| raw_text | Text | 合同原始提取文本 |
| created_at | DateTime | 提取时间 |

### 4.3 Template（固定范本）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 主键 |
| title | String(200) | 范本名称 |
| category | String(50) | 合同分类 |
| industry | String(100) | 行业类型 |
| content | Text | 范本内容（含【变量】） |
| variables | Text | 变量列表 JSON（自动提取） |
| created_at / updated_at | DateTime | 时间戳 |

### 4.4 Bid（投标文件）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 主键 |
| title | String(200) | 投标文件标题 |
| filename | String(300) | 存储文件名 |
| raw_text | Text | OCR 识别文本 |
| fields | Text | 投标字段 JSON（项目编号/名称/金额/竞标方/明细报价…20 项） |
| generated_doc | String(300) | 生成的投标文档文件名 |
| status | String(20) | uploaded → ocred → extracted → generated |

## 五、业务流程

### 5.1 合同管理系统（4 步）

```
┌────────────┐  ┌──────────────┐  ┌──────────────────────────────────┐  ┌───────────┐
│ 1. 上传合同 │→ │ 2. 智能字段提取│→ │ 3. AI 生成 / 固定范本 / 快速拟定  │→ │ 4. 审核归档 │
└────────────┘  └──────────────┘  └──────────────────────────────────┘  └───────────┘
                    │                               │
                    ▼                               ▼
           DeepSeek 提取 8 项         按分类+行业生成 → 编辑修改 → 保存范本
           关键字段（金额/日期/       （自动提取【】变量）→ 填变量快速生成合同
           双方/期限/标的等）
```

### 5.2 投标系统（4 步）

```
┌──────────────┐  ┌───────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ 1. 上传投标文件│→ │ 2. OCR 优化与识别   │→ │ 3. 投标信息提取   │→ │ 4. 模板生成与填写  │
└──────────────┘  └───────────────────┘  └──────────────────┘  └──────────────────┘
                    │                            │                    │
                    ▼                            ▼                    ▼
           pdfplumber 本地 OCR           DeepSeek 提取 20 项      内置模板 + 变量替换
           提取 PDF/Word 文本            投标关键字段               → 一键生成规范化投标文档
```

## 六、API 路由

### 6.1 合同管理

| 方法 | 路由 | 功能 |
|------|------|------|
| GET | `/` | 合同列表（支持分类/状态/关键词筛选） |
| GET/POST | `/upload` | 上传合同文件 |
| GET/POST | `/contract/<id>/extract` | 对合同执行 AI 字段提取 |
| GET/POST | `/review/<id>` | 业务人员审核（通过/驳回） |
| POST | `/archive/<id>` | 审核通过后归档 |
| GET | `/file/<id>` | 在线查看合同文件 |
| POST | `/delete/<id>` | 删除合同 |

### 6.2 AI 范本生成与固定范本

| 方法 | 路由 | 功能 |
|------|------|------|
| GET/POST | `/generate` | AI 生成合同范本 |
| POST | `/save_generated` | 将 AI 结果保存为待审核合同 |
| GET | `/templates` | 固定范本列表 |
| GET/POST | `/templates/new` | 新建固定范本（含变量输入框插入） |
| GET/POST | `/templates/<id>` | 编辑固定范本（变量自动重提取） |
| GET/POST | `/templates/<id>/use` | 使用范本填变量生成合同 |
| POST | `/templates/<id>/delete` | 删除范本 |

### 6.3 投标系统

| 方法 | 路由 | 功能 |
|------|------|------|
| GET | `/bids` | 投标文件列表 |
| GET/POST | `/bids/upload` | 上传投标文件 |
| POST | `/bids/<id>/extract` | OCR + 投标信息提取 |
| GET/POST | `/bids/<id>/template` | 模板填写与生成投标文档 |
| GET | `/bids/<id>/view` | 查看/下载生成的投标文档 |
| POST | `/bids/<id>/delete` | 删除投标文件 |

### 6.4 指引

| 方法 | 路由 | 功能 |
|------|------|------|
| GET | `/guide` | 完整业务流程指引页 |

## 七、核心功能详解

### 7.1 智能字段提取

**流程**：
1. 用 pdfplumber 从 PDF 提取纯文本（无 pdfplumber 则 PyPDF2 兜底，txt 直接读取）
2. 调用 DeepSeek Chat 让 LLM 从文本中识别：合同编号、合同金额、签署日期、甲方名称、乙方名称、合同期限、合同标的、争议解决方式
3. LLM 失败时自动降级为正则兜底提取（9 个正则 pattern）

### 7.2 固定范本变量化

**变量插入**：范本编辑页的变量输入框，输入后在光标处插入 `【变量名】`（支持回车快捷）

**变量提取**：后端 `extract_variables()` 正则匹配 `【([^】]+)】`，去重保序

**使用**：`/templates/<id>/use` 自动渲染已提取的变量为输入框，用户填值后一键生成合同

### 7.3 投标 OCR 与信息提取

**OCR 优化**：pdfplumber 本地部署（纯 Python、无需 GPU），支持多页文本提取；失败降级 PyPDF2

**信息提取**：DeepSeek 从 OCR 文本提取 20 项投标字段（项目编号、项目名称、招标单位、竞标方、联系人/电话/邮箱、投标金额、截止日期、明细报价等）

**模板生成**：内置规范化投标文档模板，20 个 `【变量】` 占位符，填值后一键输出 txt 投标文档

### 7.4 LLM 降级机制

所有依赖 DeepSeek 的调用均带**正则兜底**：
- `call_deepseek` 失败 → 返回内置合同模板
- `extract_contract_fields_with_llm` 失败 → 正则提取合同字段
- `extract_bid_fields_with_llm` 失败 → 正则提取投标字段

保证即使 API Key 失效也能跑通完整演示流程。

## 八、测试

```powershell
# 冒烟测试（核心回归）
python test_smoke.py        # 8 项：上传/校验/审核/归档/查看/驳回/删除

# 固定范本测试
python test_template.py     # 8 项：变量提取/新建/编辑重提取/生成/归档/筛选/删除

# AI 生成测试
python test_ai.py           # 5 项：真实 API 生成/保存/查看/归档

# 新功能测试（字段提取 + 投标系统）
python test_new.py          # 7 项：真实 API 提取/投标 OCR/字段提取/模板生成/文档查看
```

## 九、运行

```powershell
# 安装依赖
pip install flask flask-sqlalchemy pdfplumber requests

# 启动（debug 模式，自动重载）
python app.py

# 访问
# http://127.0.0.1:5000/guide    ← 业务指引（推荐入口）
# http://127.0.0.1:5000/          ← 合同列表
# http://127.0.0.1:5000/generate  ← AI 生成范本
# http://127.0.0.1:5000/templates ← 固定范本
# http://127.0.0.1:5000/bids     ← 投标系统
```

## 十、核心配置（app.py 中）

```python
# DeepSeek API Key（生产环境改用环境变量）
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "your-key-here")
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

# 文件上传
UPLOAD_FOLDER = "./uploads"     # 合同文件
BID_FOLDER = "./bids"           # 投标文件
MAX_CONTENT_LENGTH = 50MB

ALLOWED_EXTENSIONS = {doc, docx, pdf, txt}
```
