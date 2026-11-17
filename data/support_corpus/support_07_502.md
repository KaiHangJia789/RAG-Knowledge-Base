# 网关 502 的分层排查

示范产品：RAG Knowledge Base
资料类型：技术支持示范资料草稿
适用范围：基础代码快照 b89d2a2；本期新增行为另有注明，不作为商业版本承诺
整理日期：2026-11-13
代码来源：deploy/nginx/rag.conf; docker-compose.prod.yml; web/next.config.ts

生产请求经 nginx、web，再由 web 代理到 backend。502 只说明请求链路某处上游失败，不能只凭状态码断定数据库或模型服务故障。
先确认访问的是首页还是 /api/v1 接口、发生时间与部署方式，再用 docker compose -f docker-compose.prod.yml ps 查看服务状态，并读取 web/backend 的脱敏日志。
维护人员可在服务器本机请求 http://127.0.0.1:8000/api/v1/health 检查 API 可达性。若本机 API 可达而外部失败，再核对实际生效的 nginx 与 web 代理配置。不要直接建议关闭认证或暴露数据库端口。
