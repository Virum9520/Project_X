class MemoryEngineError(Exception):
    """Base class for Memory Persistence Engine errors."""


class MemoryNotFound(MemoryEngineError):
    """No such memory for this learner (also raised for another learner's memory)."""


class MemoryRuleViolation(MemoryEngineError):
    """A write that would break an engine rule (evidence, append-only, visibility)."""
