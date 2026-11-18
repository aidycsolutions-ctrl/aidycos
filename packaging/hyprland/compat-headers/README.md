# Compatible development headers for Hyprbars

Debian Trixie Backports can ship `hyprland-dev` 0.55.2 together with a newer
`libhyprutils-dev` (for example 0.14.x) than the Hyprland package was built
against (0.13.1).

Hyprutils 0.14 made `CSharedPointer::operator bool()` and
`CWeakPointer::operator bool()` **explicit**. Hyprland 0.55.2 headers still do
`return SP<…>` / `return PHLLS` inside `bool` helpers, so plugin builds fail with:

```text
error: cannot convert SP<CSyncTimeline> … to ‘bool’
error: cannot convert PHLLS … to ‘bool’
note: explicit conversion function was not considered
```

`setup-hyprbars.sh` detects the Hyprland-built-against hyprutils version from
`version.h` and, when the system `-dev` package is newer/incompatible, prepends
the matching tree under this directory (currently `hyprutils-0.13.1/`) so the
plugin compiles against the same pointer API Hyprland 0.55.2 expects.

Do not replace these headers with a newer hyprutils release unless Hyprland
itself was rebuilt against that release.
