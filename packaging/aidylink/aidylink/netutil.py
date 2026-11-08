"""Small network helpers."""

from __future__ import annotations

import socket

# Debe coincidir con hostfwd en probar-qemu.sh (tcp::47834-:47833).
QEMU_HOSTFWD_PORT = 47834


def detect_lan_ip() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def is_qemu_slirp_ip(host: str) -> bool:
    return (host or "").startswith("10.0.2.")


def resolve_lan_endpoint(host: str, port: int, *, local_ip: str) -> tuple[str, int]:
    """Reescribe destinos QEMU-NAT inalcanzables desde el host.

    El guest se anuncia como 10.0.2.15, pero desde el PC real esa IP no existe.
    Hay que usar el hostfwd: 127.0.0.1:47834 → guest:47833.
    """
    host = (host or "").strip()
    local = (local_ip or "").strip()
    try:
        port_i = int(port)
    except (TypeError, ValueError):
        port_i = 47833
    if is_qemu_slirp_ip(host) and not is_qemu_slirp_ip(local):
        return "127.0.0.1", QEMU_HOSTFWD_PORT
    return host, port_i
