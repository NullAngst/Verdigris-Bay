#!/bin/sh
# Install Verdigris Bay for the current user: binary, icon, and menu entry.
# Nothing touches system directories; no root needed.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
bin="${HOME}/.local/bin"
apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
icons="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"

mkdir -p "$bin" "$apps" "$icons"
install -m 755 "$here/verdigris-bay" "$bin/verdigris-bay"
install -m 644 "$here/verdigris-bay.png" "$icons/verdigris-bay.png"
sed "s|^Exec=.*|Exec=$bin/verdigris-bay|" "$here/verdigris-bay.desktop" > "$apps/verdigris-bay.desktop"
chmod 644 "$apps/verdigris-bay.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$apps" || true

echo "Installed to $bin/verdigris-bay"
case ":$PATH:" in
  *":$bin:"*) ;;
  *) echo "Note: $bin is not on your PATH. The menu entry still works." ;;
esac
