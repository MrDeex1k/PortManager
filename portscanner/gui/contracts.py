"""JSON response contracts shared with the generated TypeScript interfaces."""

from typing import Literal, TypedDict

from portscanner.gui.core_payloads import (
    LocalIPPayload,
    PortEntryPayload,
    SourceReportPayload,
    TunnelInfoPayload,
)


class AppInfo(TypedDict):
    name: str
    version: str
    mode: Literal["desktop", "browser"]
    stage: Literal["preview", "live"]
    kube_enabled: bool
    termination_mode: Literal["graceful", "hard"]


class SnapshotSuccess(TypedDict):
    ok: Literal[True]
    busy: Literal[False]
    request_id: int
    generation: int
    kube_enabled: bool
    collected_at: str
    ports: list[PortEntryPayload]
    local_ips: list[LocalIPPayload]
    tunnels: list[TunnelInfoPayload]
    reports: list[SourceReportPayload]


class KillTargetView(TypedDict):
    pid: int
    name: str
    executable: str
    cmdline: list[str]


class PrepareSuccess(TypedDict):
    ok: Literal[True]
    token: str
    target: KillTargetView
    escalation: bool


class _FailureOptional(TypedDict, total=False):
    busy: bool
    request_id: int
    generation: int
    continuation: PrepareSuccess


ErrorCode = Literal[
    "invalid_request",
    "busy",
    "collection_failed",
    "stale_snapshot",
    "invalid_filter",
    "invalid_selection",
    "desktop_required",
    "export_failed",
    "process_rejected",
    "consent_expired",
    "termination_pending",
]


class BridgeFailure(_FailureOptional):
    ok: Literal[False]
    code: ErrorCode
    message: str


class FilterSuccess(TypedDict):
    ok: Literal[True]
    generation: int
    ids: list[str]


class KubernetesSuccess(TypedDict):
    ok: Literal[True]
    kube_enabled: bool


class ActionSuccess(TypedDict):
    ok: Literal[True]
    status: Literal["terminated", "already_exited"]
    pid: int


class ExportSaved(TypedDict):
    ok: Literal[True]
    status: Literal["saved"]
    path: str


class Cancelled(TypedDict):
    ok: Literal[True]
    status: Literal["cancelled"]


RESPONSES = [
    AppInfo,
    SnapshotSuccess,
    KillTargetView,
    PrepareSuccess,
    BridgeFailure,
    FilterSuccess,
    KubernetesSuccess,
    ActionSuccess,
    ExportSaved,
    Cancelled,
]
