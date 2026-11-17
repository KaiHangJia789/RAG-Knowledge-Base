# MCP 接入范围

示范产品：RAG Knowledge Base
资料类型：技术支持示范资料草稿
适用范围：基础代码快照 b89d2a2；本期新增行为另有注明，不作为商业版本承诺
整理日期：2026-11-13
代码来源：app/mcp_server/tools.py; app/mcp_server/resources.py; app/mcp_server/prompts.py; README.md

MCP 通过 python -m app.mcp_server 以 stdio 进程提供知识工具。search_documents 检索；get_document_by_id 分页读文档。资源含 docs://list 与 docs://stats，提示含 rag_qa 与 summarize_document。
它用于可信本机 AI 客户端调用，不是公网 HTTP 多用户入口；不能假定网页登录 cookie 会限制该进程的文档读取范围。不要直接把生产全库 MCP 暴露给不可信客户端。
stdio 的 stdout 应只保留协议输出，诊断日志使用 stderr。可用 python scripts/smoke_mcp_stdio.py 验证真实子进程连接。
