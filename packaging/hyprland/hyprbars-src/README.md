# Vendored hyprbars (hyprland-plugins)

Pinned to upstream tag `v0.55.0` (matches Debian Hyprland 0.55.2 API), plus
local commit overlay `3aa21f2e0ca72412f1b434c3126f8f1fec3c716c` where identical.

Patch applied: `../hyprbars-dragend.patch` (hyprbarsdragend IPC event)

Compiled offline by `../setup-hyprbars.sh` so test laptops with flaky
GitHub/SSL still get minimize/maximize/close buttons.

If `libhyprutils-dev` from Backports is newer than the hyprutils version
recorded in Hyprland's `version.h`, the setup script automatically uses
`../compat-headers/hyprutils-<version>/` instead of the system headers.
