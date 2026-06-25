"""Domain exceptions for agentctx."""


class AgentctxError(Exception):
    """Base class for user-facing agentctx errors."""


class ProfileNotFound(AgentctxError):
    pass


class ProfileAlreadyExists(AgentctxError):
    pass


class InvalidProfileName(AgentctxError):
    pass


class UnsafeAuthFile(AgentctxError):
    pass


class InvalidAuthJson(AgentctxError):
    pass


class LockError(AgentctxError):
    pass


class NoCurrentProfile(AgentctxError):
    pass
