# 已有数据库执行迁移

示范产品：RAG Knowledge Base
资料类型：技术支持示范资料草稿
适用范围：基础代码快照 b89d2a2；本期新增行为另有注明，不作为商业版本承诺
整理日期：2026-11-13
代码来源：README.md; docker-compose.prod.yml; app/db/migrations/

PostgreSQL 容器的 docker-entrypoint-initdb.d 仅在空数据目录初始化时运行。已有数据卷不会因为重新拉镜像就自动执行新增迁移。
维护人员需核对当前部署代码与迁移文件，按顺序执行尚未应用的 SQL，使用 psql -v ON_ERROR_STOP=1 并确认执行结果；执行前做好数据库备份。
若提示某迁移文件不存在，应检查服务器代码是否同步到含该文件的 commit，而不是创建空文件绕过。不要删除数据卷来强制初始化现有生产数据库。
