"""Small network helpers."""

from __future__ import annotations

import socket
import struct


def _iter_ipv4_ifaces() -> list[tuple[str, int, int]]:
    """Return (ifname, ip_int, mask_int) for up broadcast-capable IPv4 NICs."""
    try:
        import fcntl
    except ImportError:
        return []

    out: list[tuple[str, int, int]] = []
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
                ip = int.from_bytes(raw_addr[20:24], "big")
                mask = int.from_bytes(raw_mask[20:24], "big")
                if ip >> 24 == 127 or mask == 0:
                    continue
                out.append((name, ip, mask))
            except OSError:
                continue
    return out


def lan_broadcast_addresses() -> tuple[str, ...]:
    """Return broadcast addresses for active IPv4 interfaces.

    The limited broadcast (255.255.255.255) is routed using the system's
    preferred interface. Directed subnet broadcasts also reach peers when
    the machine has multiple LAN interfaces or a less common route setup.
    """
    addresses: set[str] = {"255.255.255.255"}
    for _, ip, mask in _iter_ipv4_ifaces():
        broadcast = (ip & mask) | (0xFFFFFFFF ^ mask)
        addresses.add(socket.inet_ntoa(broadcast.to_bytes(4, "big")))
    return tuple(sorted(addresses)) or ("255.255.255.255",)


def lan_subnet_hosts(*, exclude: str | None = None, max_hosts: int = 254) -> tuple[str, ...]:
    """Host IPs on local /24+ LAN segments for TCP presence fallback.

    Skips networks wider than /24 to avoid huge scans. ``exclude`` (usually
    this machine's LAN IP) is omitted from the result.
    """
    skip = (exclude or "").strip()
    hosts: list[str] = []
    seen: set[str] = set()
    ranked = sorted(
        _iter_ipv4_ifaces(),
        key=lambda item: _score_lan_candidate(*item),
        reverse=True,
    )
    for name, ip, mask in ranked:
        if _iface_looks_like_vpn(name):
            continue
        prefix = bin(mask).count("1")
        if prefix < 24:
            continue
        network = ip & mask
        broadcast = network | (0xFFFFFFFF ^ mask)
        for value in range(network + 1, broadcast):
            host = socket.inet_ntoa(value.to_bytes(4, "big"))
            if host == skip or host in seen:
                continue
            seen.add(host)
            hosts.append(host)
            if len(hosts) >= max_hosts:
                return tuple(hosts)
    return tuple(hosts)

# Debe coincidir con hostfwd en probar-qemu.sh (tcp::47834-:47833).
QEMU_HOSTFWD_PORT = 47834


_VPN_IFACE_MARKERS = (
    "tun",
    "tap",
    "wg",
    "tailscale",
    "nordlynx",
    "mullvad",
    "proton",
    "zt",
    "ocytun",
    "ppp",
)


def _iface_looks_like_vpn(name: str) -> bool:
    lowered = (name or "").lower()
    return any(marker in lowered for marker in _VPN_IFACE_MARKERS)


def _score_lan_candidate(name: str, ip: int, mask: int) -> tuple[int, int, int]:
    """Higher is better. Prefer real Wi‑Fi/Ethernet over VPN default routes."""
    prefix = bin(mask).count("1")
    first = ip >> 24
    second = (ip >> 16) & 0xFF
    score = 0
    if _iface_looks_like_vpn(name):
        score -= 1000
    # Typical home/LAN ranges first.
    if first == 192 and second == 168:
        score += 300
    elif first == 10 and second == 0:
        score += 220
    elif first == 172 and 16 <= second <= 31:
        score += 180
    elif first == 10:
        score += 80  # other 10/8 (often VPN overlays)
    # Prefer denser LAN prefixes (/24../22).
    if 24 <= prefix <= 24:
        score += 40
    elif 22 <= prefix <= 23:
        score += 20
    elif prefix < 20:
        score -= 40
    # Stable tie-breakers: denser mask, then lower IP.
    return (score, prefix, -ip)


def detect_lan_ip() -> str:
    """Pick a LAN IPv4 for beacons/QR, avoiding VPN tunnels when possible."""
    candidates = _iter_ipv4_ifaces()
    if candidates:
        best_name, best_ip, best_mask = max(
            candidates, key=lambda item: _score_lan_candidate(*item)
        )
        if not _iface_looks_like_vpn(best_name) or len(candidates) == 1:
            return socket.inet_ntoa(best_ip.to_bytes(4, "big"))
        # All look like VPN: still return the best scored one.
        return socket.inet_ntoa(best_ip.to_bytes(4, "big"))

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
