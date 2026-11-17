# 上传格式与可检索范围

示范产品：RAG Knowledge Base
资料类型：技术支持示范资料草稿
适用范围：基础代码快照 b89d2a2；本期新增行为另有注明，不作为商业版本承诺
整理日期：2026-11-13
代码来源：app/api/v1/upload.py; app/config.py

默认文件上限 MAX_UPLOAD_SIZE_MB=50。后端上传扩展名允许 PDF、TXT、MD、DOCX、CSV、JSON、XML，但自动解析与入索引仅对 PDF/MD/TXT 执行。因此上传成功不代表每种格式都能参与问答。
文档状态包括 uploaded、parsing、chunking、ready、failed。应检查上传返回状态、解析日志与索引日志；ready 也不能单独证明向量已写入。
上传内容应是允许存储的产品资料，排障日志需脱敏。当前没有 OCR 处理保证；图片扫描件缺少可提取文本时，先提供有文本层的 PDF 或转为 MD/TXT。
