@dataclass(frozen=True)
class BatterySnapshot:
    """Aggregated battery view for the bar (UPower DisplayDevice or sysfs).

    Extra fields (time/rate/health) are reserved for a future popup and may be
    ``None`` when the backend does not provide them.
    """

    available: bool
    percentage: int = 0
    status: str = "unknown"  # charging | discharging | full | empty | unknown
    plugged: bool = False
    charging: bool = False
    full: bool = False
    low: bool = False
    critical: bool = False
    icon_name: str = "battery-missing-symbolic"
    time_to_empty_sec: int | None = None
    time_to_full_sec: int | None = None
    energy_rate_w: float | None = None
    device_count: int = 0
    source: str = ""  # "upower" | "sysfs" | ""

    @staticmethod
    def unavailable() -> "BatterySnapshot":
        return BatterySnapshot(available=False)

    @property
    def percent_label(self) -> str:
        if not self.available:
            return ""
        return f"{max(0, min(100, int(self.percentage)))}%"
