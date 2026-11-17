"""Support evaluation contracts: validate data before any external calls."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.support import load_support_dataset, score_support_result
from app.rag.models import RagAnswer


def dataset_file(tmp_path, *, sources=None, cases=None):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "manual.md").write_text("Product manual", encoding="utf-8")
    case = {"id": "s1", "input": {"question": "How to upload?", "history": []},
            "expected_output": {"statuses": ["answered"], "reference_docs": sources or ["manual.md"],
                                "citation_required": True, "review_criteria": ["Explain supported formats"]},
            "metadata": {"category": "usage", "review_required": True}}
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"version": "support-draft-v1", "corpus_dir": str(corpus),
                                "items": cases if cases is not None else [case]}), encoding="utf-8")
    return path


def test_dataset_rejects_missing_source(tmp_path):
    path = dataset_file(tmp_path, sources=["missing.md"])
    with pytest.raises(ValueError, match="missing.md"):
        load_support_dataset(path)


def test_dataset_rejects_duplicate_ids(tmp_path):
    path = dataset_file(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["items"] *= 2
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_support_dataset(path)


def test_dataset_rejects_empty_items(tmp_path):
    with pytest.raises(ValidationError):
        load_support_dataset(dataset_file(tmp_path, cases=[]))


def test_structural_checks_do_not_claim_semantic_correctness(tmp_path):
    item = load_support_dataset(dataset_file(tmp_path)).items[0]
    result = RagAnswer(question="How to upload?", answer="unfounded claim", answer_status="answered")
    scores = score_support_result(item, result)
    assert scores["status_match"] is True
    assert scores["citation_present"] is False
    assert scores["reference_retrieval_hit"] is False
    assert scores["semantic_review"] == "pending"
    assert scores["structural_pass"] is False


def test_clarification_requires_actual_questions(tmp_path):
    path = dataset_file(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["items"][0]["expected_output"].update(statuses=["needs_clarification"], citation_required=False)
    path.write_text(json.dumps(data), encoding="utf-8")
    item = load_support_dataset(path).items[0]
    result = RagAnswer(question="How?", answer="Need environment", answer_status="needs_clarification")
    assert score_support_result(item, result)["structural_pass"] is False


@pytest.mark.parametrize("name", ["support_eval_draft.json", "support_regression_v2.json", "support_regression_v3.json"])
def test_committed_support_dataset_is_valid_and_marked_for_review(name):
    dataset = load_support_dataset(Path("data/eval") / name)
    assert dataset.items
    assert all(item.metadata.review_required for item in dataset.items)


@pytest.mark.parametrize("prompt", ["support_answer_v1", "support_answer_v2", "support_answer_v3", "rag_context_cited"])
def test_eval_records_effective_generation_budget_and_sampling(prompt):
    from types import SimpleNamespace
    from app.rag.models import RetrievalConfig
    from scripts.run_support_eval import generation_parameters
    cfg = RetrievalConfig(prompt_name=prompt, temperature=.25)
    settings = SimpleNamespace(LLM_MAX_TOKENS=128, LLM_REASONING_EFFORT="high", EVAL_GEN_THINKING_ENABLED=True)
    first = generation_parameters(prompt, cfg, settings)
    settings.LLM_MAX_TOKENS = 4096
    second = generation_parameters(prompt, cfg, settings)
    assert first["max_tokens"] == 128 and second["max_tokens"] == 4096
    assert first != second
    support = prompt != "rag_context_cited"
    assert first["thinking_enabled"] is (not support)
    assert first["temperature"] == .25
    assert first["json_mode"] is support
    assert first["reasoning_effort"] == "high"
