# 健康接口的证明范围

示范产品：RAG Knowledge Base
资料类型：技术支持示范资料草稿
适用范围：基础代码快照 b89d2a2；本期新增行为另有注明，不作为商业版本承诺
整理日期：2026-11-13
代码来源：app/api/v1/health.py

GET /api/v1/health 返回 API 基本存活信息。当前 /api/v1/health/ready 中 database 和 redis 标记为 skipped，而不是实际数据库或 Redis 连接测试。
因此 health 或 ready 返回 200，不能证明 PostgreSQL、Redis、向量索引、邮件或大模型服务全部可用。必须结合对应日志或专门功能请求验证。
不要把该接口描述成完整生产依赖巡检。反馈故障时同时提供失败功能、状态码与脱敏日志。
