"""Windows Job Object: potomkowie są sprzątani także po wyjściu rodzica.

Kontrakt Win32: https://learn.microsoft.com/windows/win32/procthread/job-objects
"""

import ctypes
from typing import Any


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _IOCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IOCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class WindowsJob:
    """Uchwyt nie jest dziedziczony; zamknięcie kończy wszystkie procesy joba."""

    def __init__(self, pid: int) -> None:
        winapi: Any = ctypes
        self._winapi = winapi
        kernel: Any = winapi.WinDLL("kernel32", use_last_error=True)
        self._kernel = kernel
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        kernel.CreateJobObjectW.restype = ctypes.c_void_p
        kernel.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        kernel.SetInformationJobObject.restype = ctypes.c_int
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel.AssignProcessToJobObject.restype = ctypes.c_int
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.restype = ctypes.c_int
        self._handle = kernel.CreateJobObjectW(None, None)
        if not self._handle:
            raise self._winapi.WinError()
        parent = None
        try:
            limits = _ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
            if not kernel.SetInformationJobObject(
                self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            ):
                raise self._winapi.WinError()
            parent = kernel.OpenProcess(0x0101, False, pid)  # SET_QUOTA | TERMINATE
            if not parent or not kernel.AssignProcessToJobObject(self._handle, parent):
                raise self._winapi.WinError()
        except BaseException:
            self.close()
            raise
        finally:
            if parent:
                kernel.CloseHandle(parent)

    def close(self) -> None:
        if self._handle:
            handle, self._handle = self._handle, None
            if not self._kernel.CloseHandle(handle):
                raise self._winapi.WinError()
