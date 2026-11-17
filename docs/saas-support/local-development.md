# Windows 本地启动

适用本工作区 `D:\RAG项目`，PowerShell。已有 Python 虚拟环境和前端依赖时可直接从第 2 步开始；以下命令不会连接 ECS。数据库密码和模型密钥只保存在本机 `.env`，不要复制生产账号资料。

## 1. 首次准备（已有环境跳过）

安装 Python 3.11+、Docker Desktop 和 Node.js 20.9+。Docker Desktop 需要启动并可使用 Linux 容器。

```powershell
Set-Location D:\RAG项目
# 只在虚拟环境不存在时创建
if (-not (Test-Path .\RAG_venv\Scripts\python.exe)) { py -3 -m venv RAG_venv }
.\RAG_venv\Scripts\python.exe -m pip install -r requirements.txt
# 不覆盖已有 .env
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
Set-Location web
npm ci
```

在 `.env` 填好 `DEEPSEEK_API_KEY`、`DASHSCOPE_API_KEY`、随机的 `AUTH_SECRET_KEY`，并核对本地数据库与 Redis 地址。仓库本地 compose 默认 PostgreSQL 为 `127.0.0.1:5432`、`ragdb`、用户 `raguser`、密码 `ragpass`；Redis 为 `127.0.0.1:6379`。这组凭据仅限本地开发，不能复制到公网环境。若 `.env` 使用的是自己的本地数据库，应保留与该库一致的设置。

## 2. 启动数据库和 Redis

```powershell
Set-Location D:\RAG项目
docker compose up -d postgres redis
docker compose ps
```

已有原生 PostgreSQL/Redis 且 `.env` 正在使用它们时，可以继续使用，不需要再启动同端口容器。端口占用时先确认现有服务，不要删除数据卷。

首次使用空 PostgreSQL 数据卷会执行 `app/db/migrations/`。已有数据卷不会自动应用新增迁移；遇到缺表/缺列时，先备份并仅执行缺失的迁移，不能靠 `docker compose down -v` 清库。当前技术支持回答修复没有新增迁移。

## 3. 启动后端（终端一）

```powershell
Set-Location D:\RAG项目
# 只影响当前终端；避免本机 HTTP 的 Secure cookie 问题
$env:AUTH_COOKIE_SECURE = "False"
$env:PUBLIC_BASE_URL = "http://localhost:3000"
$env:MAIL_BACKEND = "log"
.\RAG_venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

`log` 邮件后端只在终端日志中输出验证链接和验证码，不发送真实邮件，仅限本机开发。生产 HTTPS 保持 `AUTH_COOKIE_SECURE=True`。确认启动日志中 PostgreSQL 连接成功且服务单例已初始化；仅看到 Uvicorn 启动或健康接口 200 不能证明数据库可用。

## 4. 启动前端（终端二）

```powershell
Set-Location D:\RAG项目\web
npm run dev
```

浏览器打开 `http://localhost:3000`，API 文档为 `http://127.0.0.1:8000/docs`。前端默认将 `/api/v1` 代理到本机 8000；若改后端端口，需要在启动前端的终端设置 `BACKEND_URL`。

新库先注册账号，在后端日志中找到邮箱验证链接并完成验证。登录后上传 PDF、MD 或 TXT，再检查解析和入索引日志，然后提问并打开引用。空索引时问答会提示知识库尚未就绪，属于预期行为。

## 5. 可选：导入技术支持示范资料

这一步会写当前 `.env` 对应的数据库和默认索引、调用真实向量 API，不属于启动必需步骤。请先备份数据库与 `data/index`，并确认使用本地环境。将 `.env` 中的 `DEFAULT_USERNAME` 设置为已存在的专用语料管理账号用户名；邮箱注册用户的用户名就是注册邮箱。

```powershell
Set-Location D:\RAG项目
.\RAG_venv\Scripts\python.exe scripts/build_index.py --corpus data/support_corpus --verify
```

构建后停止并重新启动后端，使内存索引更新。该目录内容会成为所有用户可检索的公共资料；含私有信息的用户文件应通过网页上传，不能放进公共示范目录。公共资料拥有者不能直接注销，建议使用专用账号。

本次评测使用 `data/index/support-eval-20261113-eeb21208` 的独立索引；启动日常开发环境时不要将 `INDEX_DIR` 指向这个目录。

## 6. 本地回归

```powershell
Set-Location D:\RAG项目
.\RAG_venv\Scripts\python.exe -m pytest -q
.\RAG_venv\Scripts\python.exe scripts/run_support_eval.py --validate-only
.\RAG_venv\Scripts\python.exe scripts/run_support_eval.py --dataset data/eval/support_regression_v3.json --validate-only
```

这些命令不调用真实模型。真实模型评测需另设独立索引与评测账号范围，会产生 API 用量；详见行业说明和回归报告。

停止开发：两个终端分别按 `Ctrl+C`。需要停止本地容器时运行 `docker compose stop postgres redis`；数据卷保留。
