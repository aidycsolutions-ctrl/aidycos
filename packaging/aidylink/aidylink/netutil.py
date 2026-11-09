"""Small network helpers."""

from __future__ import annotations

import socket
import struct


def lan_broadcast_addresses() -> tuple[str, ...]:
    """Return broadcast addresses for active IPv4 interfaces.

    The limited broadcast (255.255.255.255) is routed using the system's
    preferred interface. Directed subnet broadcasts also reach peers when
    the machine has multiple LAN interfaces or a less common route setup.
    """
    try:
        import fcntl
    except ImportError:
        return ("255.255.255.255",)

    addresses: set[str] = {"255.255.255.255"}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for _, name in socket.if_nameindex():
            ifname = name.encode("utf-8")[:15]
            request = struct.pack("256s", ifname)
            try:
                raw_flags = fcntl.ioctl(sock.fileno(), 0x8913, request)  # SIOCGIFFLAGS
                flags = struct.unpack("H", raw_flags[16:18])[0]
                if not flags & 0x1 or not flags & 0x2:  # IFF_UP and IFF_BROADCAST
                    continue
                raw_addr = fcntl.ioctl(sock.fileno(), 0x8915, request)  # SIOCGIFADDR
                raw_mask = fcntl.ioctl(sock.fileno(), 0x891B, request)  # SIOCGIFNETMASK
                ip_bytes = raw_addr[20:24]
                mask_bytes = raw_mask[20:24]
                ip = int.from_bytes(ip_bytes, "big")
                mask = int.from_bytes(mask_bytes, "big")
                if ip >> 24 == 127 or mask == 0:
                    continue
                broadcast = (ip & mask) | (0xFFFFFFFF ^ mask)
                addresses.add(socket.inet_ntoa(broadcast.to_bytes(4, "big")))
            except OSError:
                continue
    return tuple(sorted(addresses)) or ("255.255.255.255",)

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
