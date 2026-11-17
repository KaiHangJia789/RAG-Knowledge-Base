"""Local draft support dataset and deterministic checks; not a semantic judge."""
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.rag.models import AnswerStatus, RagAnswer

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class HistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class SupportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=10)


class SupportExpected(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statuses: list[AnswerStatus] = Field(min_length=1)
    reference_docs: list[str] = Field(default_factory=list)
    citation_required: bool = False
    review_criteria: list[str] = Field(min_length=1)


class SupportMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str
    review_required: bool = True


class SupportCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    input: SupportInput
    expected_output: SupportExpected
    metadata: SupportMetadata


class SupportDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    corpus_dir: str
    items: list[SupportCase] = Field(min_length=1)


def load_support_dataset(path: Path) -> SupportDataset:
    dataset = SupportDataset.model_validate_json(path.read_text(encoding="utf-8"))
    corpus = Path(dataset.corpus_dir)
    if not corpus.is_absolute():
        corpus = PROJECT_ROOT / corpus
    if not corpus.is_dir():
        raise ValueError(f"Corpus directory does not exist: {dataset.corpus_dir}")
    seen = set()
    for item in dataset.items:
        if item.id in seen:
            raise ValueError(f"duplicate case id: {item.id}")
        seen.add(item.id)
        for name in item.expected_output.reference_docs:
            # Sources are filename references, never arbitrary paths.
            if Path(name).name != name or not (corpus / name).is_file():
                raise ValueError(f"Missing or invalid reference document: {name}")
    return dataset


def score_support_result(item: SupportCase, result: RagAnswer) -> dict:
    expected = item.expected_output
    status = result.answer_status or ("insufficient_evidence" if result.refused else "answered")
    status_match = status in expected.statuses
    citation_present = bool(result.citations)
    references = set(expected.reference_docs)
    retrieval_hit = bool(references.intersection(result.retrieved_docs)) if references else None
    clarification_valid = status != "needs_clarification" or 1 <= len(result.clarifying_questions) <= 2
    output_valid = not result.output_validation_failed
    structural_pass = (output_valid and status_match and clarification_valid and
                       (not expected.citation_required or citation_present) and not result.invalid_citations)
    return {"output_valid": output_valid, "status_match": status_match, "citation_present": citation_present,
            "reference_retrieval_hit": retrieval_hit, "clarification_valid": clarification_valid,
            "structural_pass": structural_pass, "semantic_review": "pending"}
