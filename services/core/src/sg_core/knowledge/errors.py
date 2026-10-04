"""Errors raised by the knowledge pipeline."""

from typing import Any


class KnowledgeError(Exception):
    """Base class."""


class UnsupportedDocumentError(KnowledgeError):
    """The upload is not a supported type, is too large, or its bytes do not match its type."""


class ExtractionError(KnowledgeError):
    """Text could not be extracted from a stored document. `flags` are kept on the version."""

    def __init__(self, message: str, flags: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.flags = flags


class DocumentNotFound(KnowledgeError):
    """No such document (or it belongs to someone else: the two are indistinguishable)."""
