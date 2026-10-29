"""Domain errors. No framework imports."""


class DomainError(Exception):
    """Base class for interview domain failures."""


class InvalidPhaseTransitionError(DomainError):
    """Raised when an interview phase change is not allowed."""


class ModelCardValidationError(DomainError):
    """Raised when an agent model card violates a recorded rule."""


class ConcurrencyLimitExceededError(DomainError):
    """Raised when a tool call would exceed the configured concurrency cap."""


class TavusIntegrationError(DomainError):
    """Raised when the Tavus API rejects or omits a required response."""


class WorkspaceExecutionError(DomainError):
    """Raised when candidate code or a terminal command cannot be run."""
