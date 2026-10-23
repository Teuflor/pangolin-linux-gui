#!/usr/bin/env bash
# Installs the Pangolin GUI for the current user (menu entry + icon).
#   ./install.sh            check dependencies, create menu entry
#   ./install.sh --deps     additionally install missing packages via apt or pacman (uses sudo)
#   ./install.sh --autostart  also start Pangolin at login (tray only)
#   ./install.sh --system-service  connect without a password: systemd unit + polkit rule (uses sudo once)
#   ./install.sh --remove-system-service  remove the systemd unit and polkit rule again
#   ./install.sh --uninstall  remove menu entry, icon and autostart entry
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/128x128/apps"
AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
LIBDIR=/usr/local/lib/pangolin-gui
UNIT=/etc/systemd/system/pangolin-gui@.service
RULE=/etc/polkit-1/rules.d/50-pangolin-gui.rules
read_deps() { grep -v -e '^#' -e '^[[:space:]]*$' "$REPO/deps/$1.txt"; }
mapfile -t APT_PACKAGES < <(read_deps debian)
mapfile -t PACMAN_PACKAGES < <(read_deps arch)

check_service_user() {
  if [ "$(id -u)" -eq 0 ]; then
    echo "Run this as your normal user, not as root (it uses sudo where needed)." >&2; exit 1
  fi
  if ! [[ "$(id -un)" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]]; then
    echo "User name '$(id -un)' is not supported for the system service." >&2; exit 1
  fi
  for cmd in sudo systemctl; do
    command -v "$cmd" >/dev/null || { echo "$cmd is required for the system service." >&2; exit 1; }
  done
}

# The tunnel runs as root, so it must use a root-owned CLI binary, never one in $HOME.
install_system_service() {
  check_service_user
  [ -x /usr/bin/python3 ] || { echo "/usr/bin/python3 is required for the system service." >&2; exit 1; }
  local cli
  if [ -x /usr/bin/pangolin ] && [ "$(stat -c %u /usr/bin/pangolin)" = 0 ]; then
    cli=/usr/bin/pangolin                    # distribution package, e.g. AUR pangolin-bin
  else
    cli=/usr/local/bin/pangolin
    if [ -f "$HOME/.local/bin/pangolin" ] && [ ! -L "$HOME/.local/bin/pangolin" ]; then
      echo "Moving the Pangolin CLI from ~/.local/bin to $cli (root-owned)."
      sudo install -o root -g root -m 0755 "$HOME/.local/bin/pangolin" "$cli"
      rm -f "$HOME/.local/bin/pangolin"
    elif [ ! -x "$cli" ] || [ "$(stat -c %u "$cli")" != 0 ]; then
      echo "No root-owned Pangolin CLI found in /usr/bin or /usr/local/bin. Install it first:" >&2
      echo "  https://docs.pangolin.net/manage/clients/install-client" >&2
      exit 1
    fi
  fi

  local tmp
  tmp="$(mktemp)"
  sed "s|^PANGOLIN = .*|PANGOLIN = \"$cli\"|" "$REPO/system/pangolin-gui-client" > "$tmp"
  sudo install -d -o root -g root -m 0755 "$LIBDIR"
  sudo install -o root -g root -m 0755 "$tmp" "$LIBDIR/pangolin-gui-client"
  rm -f "$tmp"
  sudo install -o root -g root -m 0644 "$REPO/system/pangolin-gui@.service" "$UNIT"
  [ -d /etc/polkit-1/rules.d ] || sudo install -d -m 0755 /etc/polkit-1/rules.d
  sudo install -o root -g root -m 0644 "$REPO/system/50-pangolin-gui.rules" "$RULE"
  sudo systemctl daemon-reload
  echo "System service installed: pangolin-gui@$(id -un).service (CLI: $cli)."
  echo "Connecting no longer asks for a password. Run this again after updating the GUI."
  if ! command -v pkcheck >/dev/null; then
    echo "WARNING: polkit seems to be missing; without it connecting still asks for a password." >&2
  fi
}

remove_system_service() {
  check_service_user
  sudo systemctl stop "pangolin-gui@$(id -un).service" 2>/dev/null || true
  sudo rm -f "$UNIT" "$RULE" "$LIBDIR/pangolin-gui-client"
  sudo rmdir "$LIBDIR" 2>/dev/null || true
  sudo systemctl daemon-reload
  echo "System service removed. Connecting asks for the sudo password again."
}

want_deps=0; want_autostart=0; want_service=0
for arg in "$@"; do
  case "$arg" in
    --deps) want_deps=1 ;;
    --autostart) want_autostart=1 ;;
    --system-service) want_service=1 ;;
    --remove-system-service) remove_system_service; exit 0 ;;
    --uninstall)
      rm -f "$APPS/pangolin-gui.desktop" "$ICONS/pangolin-gui.png" "$AUTOSTART/pangolin-gui.desktop"
      echo "Removed menu entry, icon and autostart entry."
      [ -e "$UNIT" ] && echo "The system service is still installed: ./install.sh --remove-system-service"
      exit 0 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
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

if ((want_service)); then
  install_system_service
elif ! command -v sudo >/dev/null; then
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
