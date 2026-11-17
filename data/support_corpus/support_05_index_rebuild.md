# 索引重建与进程内存

示范产品：RAG Knowledge Base
资料类型：技术支持示范资料草稿
适用范围：基础代码快照 b89d2a2；本期新增行为另有注明，不作为商业版本承诺
整理日期：2026-11-13
代码来源：scripts/build_index.py; app/services/index_service.py

scripts/build_index.py 默认先导入 data/corpus，再从数据库 chunks 重建指定策略的 FAISS 索引。--skip-ingest 跳过语料解析，仍从 chunks 表重建；不依赖原上传文件重新解析。
--verify 比较数据库已索引块数量与索引向量数量，是一致性自检，不是问答准确率评测。--strategy 指定切分策略，--all 构建所有策略。
索引在 backend 进程启动时加载进内存。外部脚本更新磁盘索引后，需要重启 backend。索引实现按单 worker 设计，多个进程不会自动同步内存索引。
