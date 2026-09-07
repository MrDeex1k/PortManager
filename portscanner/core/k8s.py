"""Tagi heurystyczne bez kubectl i bez dostępu do klastra."""

from dataclasses import replace

from portscanner.core.model import PortEntry, ServiceTag


def executable_name(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".exe")


def tag_entry(entry: PortEntry) -> PortEntry:
    process = entry.process
    names: set[str] = set()
    if process is not None and process.status in ("ok", "access_denied"):
        if process.name:
            names.add(executable_name(process.name))
        if process.cmdline:
            names.add(executable_name(process.cmdline[0]))
    tags: set[ServiceTag] = set()
    if names & {
        "kube-apiserver",
        "kubelet",
        "kube-proxy",
        "kube-controller-manager",
        "kube-scheduler",
        "etcd",
    }:
        tags.add(ServiceTag("k8s", "process"))
    if names & {"k3s", "k3s-server", "k3s-agent"}:
        tags.add(ServiceTag("k3s", "process"))
    if names & {"microk8s", "kubelite", "k8s-dqlite", "dqlite"}:
        tags.add(ServiceTag("microk8s", "process"))
    if not tags:
        if entry.proto == "tcp" and entry.port in (1338, 2379, 2380, 6443, 10250):
            tags.add(ServiceTag("k8s", "port"))
        if entry.proto == "tcp" and entry.port == 19001:
            tags.add(ServiceTag("microk8s", "port"))
        if entry.proto == "udp" and entry.port == 8472:
            tags.add(ServiceTag("k3s", "port"))
    return replace(
        entry, tags=tuple(sorted(tags, key=lambda tag: (tag.name, tag.evidence)))
    )
