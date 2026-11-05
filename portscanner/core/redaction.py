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
    """Mask secret flag values while recognizing consecutive sensitive flags."""
    result: list[str] = []
    secret_value = False
    for arg in args:
        flag, separator, _ = arg.partition("=")
        is_secret_flag = flag.casefold().replace("_", "-") in _SECRET_FLAGS
        if secret_value:
            # A value can itself look like a flag. Hide it, but keep masking
            # when it is also a known option expecting its own secret value.
            result.append("***")
            secret_value = is_secret_flag and not separator
            continue
        if is_secret_flag:
            result.append(flag + "=***" if separator else arg)
            secret_value = not separator
        else:
            result.append(arg)
    return tuple(result)
