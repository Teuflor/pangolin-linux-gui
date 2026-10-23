#!/usr/bin/env bash
# Installs the Pangolin GUI for the current user (menu entry + icon).
#   ./install.sh            check dependencies, create menu entry
#   ./install.sh --deps     additionally install missing packages via apt or pacman (uses sudo)
#   ./install.sh --autostart  also start Pangolin at login (tray only)
#   ./install.sh --uninstall  remove menu entry, icon and autostart entry
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/128x128/apps"
AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
read_deps() { grep -v -e '^#' -e '^[[:space:]]*$' "$REPO/deps/$1.txt"; }
mapfile -t APT_PACKAGES < <(read_deps debian)
mapfile -t PACMAN_PACKAGES < <(read_deps arch)

want_deps=0; want_autostart=0
for arg in "$@"; do
  case "$arg" in
    --deps) want_deps=1 ;;
    --autostart) want_autostart=1 ;;
    --uninstall)
      rm -f "$APPS/pangolin-gui.desktop" "$ICONS/pangolin-gui.png" "$AUTOSTART/pangolin-gui.desktop"
      echo "Removed menu entry, icon and autostart entry."
      exit 0 ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

missing=(); install_cmd=()
if command -v pacman >/dev/null; then          # Arch, Manjaro, EndeavourOS, ...
  for p in "${PACMAN_PACKAGES[@]}"; do
    pacman -Qq "$p" >/dev/null 2>&1 || missing+=("$p")
  done
  install_cmd=(pacman -S --needed)
elif command -v dpkg-query >/dev/null; then    # Debian, Ubuntu, Mint, ...
  for p in "${APT_PACKAGES[@]}"; do
    dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "install ok installed" || missing+=("$p")
  done
  install_cmd=(apt-get install -y)
else
  echo "Unknown distribution: install PyGObject, GTK 3 and libayatana-appindicator (GObject introspection) manually."
fi
if ((${#missing[@]})); then
  if ((want_deps)); then
    if command -v sudo >/dev/null; then
      sudo "${install_cmd[@]}" "${missing[@]}"
    else
      echo "sudo not found – run as root: ${install_cmd[*]} ${missing[*]}" >&2
      exit 1
    fi
  else
    echo "Missing packages: ${missing[*]}"
    echo "  sudo ${install_cmd[*]} ${missing[*]}    (or run ./install.sh --deps)"
  fi
fi

if ! command -v sudo >/dev/null; then
  echo "WARNING: sudo is not installed. Connecting needs sudo (the Pangolin CLI uses it)." >&2
fi

if ! python3 -c 'import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk' 2>/dev/null; then
  echo "WARNING: GTK 3 for Python is not available yet – the GUI will not start." >&2
fi

if ! command -v pangolin >/dev/null && [ ! -x "$HOME/.local/bin/pangolin" ] && [ ! -x /usr/local/bin/pangolin ]; then
  echo "NOTE: Pangolin CLI not found. Install it first:"
  if command -v pacman >/dev/null; then
    echo "  AUR: pangolin-bin   (e.g. yay -S pangolin-bin)"
  fi
  echo "  https://docs.pangolin.net/manage/clients/install-client"
fi

chmod +x "$REPO/bin/pangolin-gui" "$REPO/bin/pangolin-gui-askpass"
mkdir -p "$APPS" "$ICONS"
cp "$REPO/data/icons/pangolin-orange.png" "$ICONS/pangolin-gui.png"

write_desktop() {  # $1 = target file, $2 = extra args
  cat > "$1" <<EOF
[Desktop Entry]
Type=Application
Name=Pangolin
Comment=Pangolin tunnel client
Exec="$REPO/bin/pangolin-gui"$2
Icon=pangolin-gui
Categories=Network;
Terminal=false
StartupNotify=false
EOF
}

write_desktop "$APPS/pangolin-gui.desktop" ""
echo "Menu entry created: $APPS/pangolin-gui.desktop"

if ((want_autostart)); then
  mkdir -p "$AUTOSTART"
  write_desktop "$AUTOSTART/pangolin-gui.desktop" " --hidden"
  echo "Autostart enabled."
fi

command -v update-desktop-database >/dev/null && update-desktop-database -q "$APPS" || true
echo "Done. Start with: $REPO/bin/pangolin-gui"
