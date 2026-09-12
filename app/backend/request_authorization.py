"""Small, dependency-free request authorization rules."""

_READ_ONLY_METHODS = {"GET", "HEAD", "OPTIONS"}


def request_method_allowed(role, method: str) -> bool:
    """Return whether an organization role may use an HTTP method.

    Enum members and plain strings are both accepted so this policy remains
    independent of the ORM and can be tested by the lightweight CI job.
    """
    role_value = getattr(role, "value", role)
    return role_value != "viewer" or method.upper() in _READ_ONLY_METHODS
