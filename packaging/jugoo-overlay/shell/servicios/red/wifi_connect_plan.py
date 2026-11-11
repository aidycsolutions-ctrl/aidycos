"""Pure helpers for planning Wi-Fi connect nmcli sequences (no GI/GTK)."""

from __future__ import annotations


def plan_wifi_connect_commands(
    *,
    ssid: str,
    interface: str,
    password: str = "",
    saved_uuids: tuple[str, ...] = (),
    current_ssid: str = "",
    currently_connected: bool = False,
) -> tuple[list[list[str]], int]:
    """Build nmcli argv lists + how many leading steps may fail.

    When switching away from another SSID, disconnect the iface first so the
    previous association (and its autoconnect race) cannot block the new join.
    """
    commands: list[list[str]] = []
    ignore_failures = 0
    current = (current_ssid or "").strip()
    if currently_connected and current and current != ssid:
        commands.append(["--wait", "15", "device", "disconnect", interface])
        ignore_failures += 1

    connect_new = [
        "--wait",
        "30",
        "device",
        "wifi",
        "connect",
        ssid,
        "ifname",
        interface,
    ]
    if password:
        if saved_uuids:
            commands.append(
                [
                    "connection",
                    "delete",
                    *(arg for uuid in saved_uuids for arg in ("uuid", uuid)),
                ]
            )
            ignore_failures += 1
        commands.append([*connect_new, "password", password])
    elif saved_uuids:
        commands.append(
            [
                "--wait",
                "30",
                "connection",
                "up",
                "uuid",
                saved_uuids[0],
                "ifname",
                interface,
            ]
        )
    else:
        commands.append(connect_new)
    return commands, ignore_failures


def access_point_counts_as_saved(
    *,
    ssid: str,
    secured: bool,
    profile_ssids: frozenset[str] | set[str],
    secrets_ssids: frozenset[str] | set[str],
) -> bool:
    """A secured AP is only 'saved' if a profile has key-mgmt (usable secrets path).

    Blank installer profiles (SSID only, no wifi-security) must not skip the
    password prompt — that was blocking joins to a different network.
    """
    if ssid not in profile_ssids:
        return False
    if secured:
        return ssid in secrets_ssids
    return True
