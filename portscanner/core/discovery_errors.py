"""Stable, non-sensitive diagnostics shared by optional discovery sources."""

import subprocess

import psutil

from portscanner.core.command import OutputLimitError, UnsafeFileError


class DiscoveryError(ValueError):
    """Carry a safe diagnostic code rather than raw configuration or stderr."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def error_code(error: Exception) -> str:
    """Classify known failure modes without including exception text."""
    if isinstance(error, DiscoveryError):
        return error.code
    if isinstance(error, OutputLimitError):
        return "output_limit"
    if isinstance(error, UnsafeFileError):
        return "unsafe_file"
    if isinstance(error, (TimeoutError, subprocess.TimeoutExpired)):
        return "timeout"
    if isinstance(error, FileNotFoundError):
        return "not_found"
    if isinstance(error, (PermissionError, psutil.AccessDenied)):
        return "access_denied"
    if isinstance(error, psutil.NoSuchProcess):
        return "process_gone"
    if isinstance(error, subprocess.CalledProcessError):
        return "command_failed"
    if isinstance(error, OSError):
        return "io_error"
    return "invalid_data"
