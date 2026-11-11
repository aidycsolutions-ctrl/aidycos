"""Snippets used to patch older Jugoo ``shell/models.py`` for Wi-Fi share/forget.

Fresh AidyCOS installs clone ``feature/atajos-aidyc-escritorio``, which has
``WifiAccessPointSnapshot`` without ``saved`` and no ``WifiCredentials``.
``install_network_wifi`` reads this file and inserts only these pieces —
not a full models.py dump.
"""

# Insert after ``active: bool = False`` inside WifiAccessPointSnapshot when missing.
WIFI_ACCESS_POINT_SAVED_FIELD = "    saved: bool = False\n"

# Insert after WifiAccessPointSnapshot (before HotspotClientSnapshot) when missing.
WIFI_CREDENTIALS_SNIPPET = '''@dataclass(frozen=True)
class WifiCredentials:
    """Credentials of a saved Wi-Fi profile, read on demand for sharing."""

    ssid: str
    password: str = ""
    security: str = "WPA"
    hidden: bool = False
'''
