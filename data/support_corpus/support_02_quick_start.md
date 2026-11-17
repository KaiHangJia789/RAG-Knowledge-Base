# 本地启动顺序

示范产品：RAG Knowledge Base
资料类型：技术支持示范资料草稿
适用范围：基础代码快照 b89d2a2；本期新增行为另有注明，不作为商业版本承诺
整理日期：2026-11-13
代码来源：README.md; docker-compose.yml; .env.example

先复制 .env.example 为本机 .env，填写所需配置，再启动 PostgreSQL 和 Redis。安装 Python requirements.txt 与 web 的 npm 依赖。运行 python scripts/build_index.py --verify 后，启动 uvicorn app.main:app --reload --port 8000，前端在 web 目录运行 npm run dev。
本机 HTTP 开发把 AUTH_COOKIE_SECURE 设为 False；生产 HTTPS 保持 True。MAIL_BACKEND=log 仅用于本机，验证链接输出到后端日志，不会真的发信。
遇到启动失败先说明是本机还是 Docker、哪个进程失败以及脱敏报错，再分别检查依赖和服务；不要从一句“打不开”推断具体根因。
