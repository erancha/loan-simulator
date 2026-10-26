#!/usr/bin/env bash
#
# Create .env from .env.example with a generated bearer token. An existing .env is kept unless
# --force.
#
#   ./scripts/init-env.sh             # create .env
#   ./scripts/init-env.sh --force     # overwrite an existing .env (and so replace its token)
#
# The token is 48 hex characters from openssl; the allowed hosts and the public URL are written
# from the ports in .env.example. If a written value fails its check, any existing .env stays as
# it was. Paste the token into MCP Inspector's bearer token field (README), then run
# ./scripts/start.sh.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --force)   FORCE=1 ;;
    -h|--help) print_help; exit 0 ;;
    *) echo "Usage: ./scripts/init-env.sh [--force]" >&2; exit 2 ;;
  esac
  shift
done

if [ -f "$ENV_FILE" ] && [ "$FORCE" -eq 0 ]; then
  echo ".env already exists; left as it is (--force overwrites it)."
  exit 0
fi

port="$(env_value "$ROOT/.env.example" ENGINE_PORT)"
host_port="$(env_value "$ROOT/.env.example" ENGINE_HOST_PORT)"
token="$(openssl rand -hex 24)"
hosts="engine:$port,127.0.0.1:$host_port,localhost:$host_port"
# The new file is built and verified beside .env and renamed over it only when complete, so a
# failure leaves no partial .env. mktemp creates it readable by the owner only, as .env holds the
# token.
draft="$(mktemp "$ENV_FILE.XXXXXX")"
trap 'rm -f "$draft"' EXIT
cp "$ROOT/.env.example" "$draft"
sed -i "s|^ENGINE_BEARER_TOKEN=.*|ENGINE_BEARER_TOKEN=$token|;
        s|^ENGINE_ALLOWED_HOSTS=.*|ENGINE_ALLOWED_HOSTS=$hosts|;
        s|^ENGINE_PUBLIC_URL=.*|ENGINE_PUBLIC_URL=http://127.0.0.1:$host_port|" "$draft"
for key in ENGINE_BEARER_TOKEN ENGINE_ALLOWED_HOSTS ENGINE_PUBLIC_URL; do
  env_value "$draft" "$key" >/dev/null
done
mv "$draft" "$ENV_FILE"
echo "Created .env with a generated bearer token. Next: ./scripts/start.sh"
