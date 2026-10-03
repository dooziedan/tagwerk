#!/bin/sh
# Start Tagwerk as the user/group given by PUID/PGID (Unraid default: 99/100 = nobody:users),
# so files it creates or modifies in /music and /config keep the owner Unraid expects.
set -e

umask "${UMASK:-022}"

if [ "$(id -u)" != "0" ]; then
    # Started with an explicit --user: nothing to switch.
    exec "$@"
fi

PUID="${PUID:-99}"
PGID="${PGID:-100}"

# Only the app data folder is chowned. The music library is never chowned automatically.
mkdir -p "$CONFIG_DIR"
chown "$PUID:$PGID" "$CONFIG_DIR"

echo "Starting Tagwerk as UID=$PUID GID=$PGID UMASK=$(umask)"
export HOME="$CONFIG_DIR"
exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups -- "$@"
