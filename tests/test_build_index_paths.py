"""自定义公开语料目录不得登记成默认 corpus 路径。"""
from pathlib import Path

from scripts.build_index import ensure_document


async def test_custom_corpus_document_records_actual_project_relative_path():
    class DB:
        def __init__(self):
            self.calls = []
        async def fetch_one(self, query, *args):
            self.calls.append((query, args))
            return None if len(self.calls) == 1 else {"id": "new-document"}

    db = DB()
    root = Path(__file__).resolve().parents[1]
    doc_id = await ensure_document(db, "owner", root / "data/support_corpus/support_01_overview.md", "正文")
    assert doc_id == "new-document"
    assert db.calls[-1][1][4] == "data/support_corpus/support_01_overview.md"
