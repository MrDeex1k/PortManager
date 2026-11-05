"""Read one explicit Kubernetes context with bounded, projected CLI output."""

import json
import os
import subprocess
import time
from pathlib import Path

from portscanner.core.command import run_command

OUTPUT_LIMIT = 4 * 1024 * 1024

# Names and addresses come from Kubernetes-validated string fields. printf %q
# quotes them; no annotations, credentials, node images or managedFields leave kubectl.
_PROJECTION = """{"items":[{{range $i, $v := .items}}{{if $i}},{{end}}
{"kind":{{printf "%q" .kind}},"metadata":{"name":{{printf "%q" .metadata.name}}
{{if eq .kind "Service"}},"namespace":{{printf "%q" .metadata.namespace}}{{end}}}
{{if eq .kind "Service"}},"spec":{"type":{{printf "%q" .spec.type}},"ports":[
{{range $j, $p := .spec.ports}}{{if $j}},{{end}}{"port":{{.port}},
"nodePort":{{if .nodePort}}{{.nodePort}}{{else}}0{{end}},
"protocol":{{printf "%q" .protocol}}}{{end}}]}
{{else}},"status":{"addresses":[{{range $j, $a := .status.addresses}}
{{if $j}},{{end}}{"type":{{printf "%q" .type}},"address":{{printf "%q" .address}}}
{{end}}]}{{end}}}{{end}}]}"""


class ConfigChangedError(ValueError):
    """The selected kubeconfig changed while a read was in progress."""


def config_fingerprint(env: dict[str, str] | None = None) -> tuple:
    """Identify config revisions by path and file metadata without reading secrets."""
    environment = os.environ if env is None else env
    paths = environment.get("KUBECONFIG") or str(Path.home() / ".kube/config")
    result = []
    for raw in paths.split(os.pathsep):
        if not raw:
            continue
        path = Path(raw).absolute()
        try:
            stat = path.stat()
            stamp = (
                stat.st_dev,
                stat.st_ino,
                stat.st_size,
                stat.st_mtime_ns,
                stat.st_ctime_ns,
            )
        except OSError as error:
            stamp = ("unreadable", error.errno)
        result.append((str(path), stamp))
    return tuple(result)


def run_kubectl(resource: str, timeout: float) -> str:
    """Pin a context and reject results if any kubeconfig file changed mid-read."""
    env = os.environ.copy()
    fingerprint = config_fingerprint(env)
    deadline = time.monotonic() + timeout

    def invoke(args: list[str], limit: int) -> str:
        """Consume the shared deadline and suppress stderr and command arguments."""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired("kubectl", timeout)
        result = run_command(["kubectl", *args], remaining, limit=limit, env=env)
        if result.returncode:
            raise subprocess.CalledProcessError(result.returncode, "kubectl")
        return result.stdout.decode("utf-8")

    context = invoke(["config", "current-context"], 65536).strip()
    if not context or "\n" in context or "\x00" in context:
        raise ValueError("Nieprawidłowy kontekst Kubernetes")
    if config_fingerprint(env) != fingerprint:
        raise ConfigChangedError()
    remaining = deadline - time.monotonic()
    output = invoke(
        [
            "--context",
            context,
            "get",
            resource,
            "--all-namespaces",
            "-o",
            "go-template=" + _PROJECTION,
            f"--request-timeout={max(0, remaining):.3f}s",
        ],
        OUTPUT_LIMIT,
    )
    if config_fingerprint(env) != fingerprint:
        raise ConfigChangedError()
    payload = json.loads(output)
    if not isinstance(payload, dict):
        raise ValueError("Nieprawidłowa odpowiedź Kubernetes")
    payload["context"] = context
    return json.dumps(payload)
