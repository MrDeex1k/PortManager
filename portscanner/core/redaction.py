"""Maskowanie znanych argumentów uwierzytelniających na granicy prezentacji."""

_SECRET_FLAGS = frozenset(
    (
        "--token",
        "--token-file",
        "--access-token",
        "--auth-token",
        "--password",
        "--passwd",
        "--api-key",
        "--secret",
        "--client-secret",
    )
)


def redact_cmdline(args: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    secret_value = False
    for arg in args:
        if secret_value:
            result.append("***")
            secret_value = False
            continue
        flag, separator, _ = arg.partition("=")
        if flag.casefold().replace("_", "-") in _SECRET_FLAGS:
            result.append(flag + "=***" if separator else arg)
            secret_value = not separator
        else:
            result.append(arg)
    return tuple(result)
