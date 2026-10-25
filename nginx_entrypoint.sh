#!/bin/sh
set -eu

# Named volumes and new bind mounts must be writable by the backend user.
mkdir -p "$DATA_DIR"
chown goodnight:goodnight "$DATA_DIR"
chmod 700 "$DATA_DIR"
nginx -t
exec "$@"
