"""Knowledge ingestion (C08): upload, extract, map to concepts, chunk, embed, activate, search.

Uploaded text is reference data. It is never executed, never treated as instructions and never
awards mastery; mastery comes only from assessed session evidence (C11).
"""

from sg_core.knowledge.chunking import TextChunk, chunk_pages
from sg_core.knowledge.errors import (
    DocumentNotFound,
    ExtractionError,
    KnowledgeError,
    UnsupportedDocumentError,
)
from sg_core.knowledge.extract import (
    SUPPORTED_MIME_TYPES,
    ExtractedDocument,
    OcrProvider,
    Page,
    detect_mime_type,
    extract_document,
)
from sg_core.knowledge.mapping import (
    CatalogConcept,
    ConceptMapper,
    KeywordConceptMapper,
    LLMConceptMapper,
    MappingProposal,
    validate_proposals,
)
from sg_core.knowledge.pipeline import IngestResult, run_ingestion, run_ingestion_job
from sg_core.knowledge.search import Passage, search_documents
from sg_core.knowledge.service import (
    DEFAULT_MAX_UPLOAD_BYTES,
    DocumentView,
    MappingView,
    UploadResult,
    VersionView,
    delete_document,
    get_document,
    list_documents,
    list_mappings,
    resolve_user_id,
    review_mapping,
    store_upload,
    version_for_user,
)

__all__ = [
    "DEFAULT_MAX_UPLOAD_BYTES",
    "SUPPORTED_MIME_TYPES",
    "CatalogConcept",
    "ConceptMapper",
    "DocumentNotFound",
    "DocumentView",
    "ExtractedDocument",
    "ExtractionError",
    "IngestResult",
    "KeywordConceptMapper",
    "KnowledgeError",
    "LLMConceptMapper",
    "MappingProposal",
    "MappingView",
    "OcrProvider",
    "Page",
    "Passage",
    "TextChunk",
    "UnsupportedDocumentError",
    "UploadResult",
    "VersionView",
    "chunk_pages",
    "delete_document",
    "detect_mime_type",
    "extract_document",
    "get_document",
    "list_documents",
    "list_mappings",
    "resolve_user_id",
    "review_mapping",
    "run_ingestion",
    "run_ingestion_job",
    "search_documents",
    "store_upload",
    "validate_proposals",
    "version_for_user",
]
