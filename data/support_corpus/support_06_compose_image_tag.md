# Docker 镜像 tag 与 invalid reference format

示范产品：RAG Knowledge Base
资料类型：技术支持示范资料草稿
适用范围：基础代码快照 b89d2a2；本期新增行为另有注明，不作为商业版本承诺
整理日期：2026-11-13
代码来源：docker-compose.prod.yml; .github/workflows/deploy.yml

生产 compose 使用 IMAGE_PREFIX 和 IMAGE_TAG 拼接 backend/web 镜像地址。IMAGE_TAG 为空可能拼出 backend:，Docker 会报告 invalid reference format。不要把文档中的尖括号占位符原样当成 shell 命令。
维护人员可运行 docker inspect rag_project-backend-1 --format '{{.Config.Image}}' 查看实际运行镜像，再设置对应 tag。不要凭记忆使用旧 sha。
命令必须在存有 docker-compose.prod.yml 的部署目录执行，或用 -f 提供绝对文件路径。启动镜像与服务器脚本应来自相同代码版本。
