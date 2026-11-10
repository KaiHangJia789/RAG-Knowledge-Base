-- ============================================================
-- 006_document_sharing.sql
-- 文档共享标记：公共语料（is_shared = TRUE）对所有用户可检索、只读；
-- 其余文档仅归属用户可见、可删除。
-- 幂等：可安全重复执行
-- ============================================================

ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_shared BOOLEAN NOT NULL DEFAULT FALSE;

-- 公共语料索引（部分索引，只覆盖共享文档）
CREATE INDEX IF NOT EXISTS idx_documents_shared
    ON documents (is_shared) WHERE is_shared;
