# 上传后检索不到

示范产品：RAG Knowledge Base
资料类型：技术支持示范资料草稿
适用范围：基础代码快照 b89d2a2；本期新增行为另有注明，不作为商业版本承诺
整理日期：2026-11-13
代码来源：app/api/v1/upload.py; scripts/build_index.py

PDF 上传后检索不到，依次核对：登录账号与文档归属、文件是否属于自动解析格式、解析是否成功、chunks 是否生成、入索引日志有无错误、CHUNK_STRATEGY 是否一致。
上传接口的入索引失败会记录错误但不回滚已上传文档，因此 HTTP 上传成功或 ready 状态不证明向量化成功。可在日志中查找“入索引失败”。
确认维护窗口和数据库连通后，可由维护人员运行 python scripts/build_index.py --skip-ingest --verify，从数据库 chunks 重建现有索引；该命令调用 embedding 服务，存在用量成本。重建后重启 backend，使内存索引重新加载。不要删除用户文档来试错。
