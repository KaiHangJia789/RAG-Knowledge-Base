"""Upload limits and ordered per-file outcomes."""
from pydantic import BaseModel

from app.models.document import DocumentResponse


class UploadLimits(BaseModel):
    max_files: int
    max_file_size_mb: int
    max_total_size_mb: int
    allowed_extensions: list[str]


class UploadResult(BaseModel):
    filename: str
    success: bool
    message: str
    document: DocumentResponse | None = None


class BatchUploadResult(BaseModel):
    items: list[UploadResult]
