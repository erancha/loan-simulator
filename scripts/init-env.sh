#!/usr/bin/env bash
#
# Create .env from .env.example with the generated values. An existing .env is kept unless
# --force.
#
#   ./scripts/init-env.sh             # create .env
#   ./scripts/init-env.sh --force     # replace an existing .env, hand-filled keys included
#
# The bearer token is 48 hex characters and the database password 32, both from openssl; the
# allowed hosts, the engine's public URL, the agent's engine URL and database URL are written from
# the ports and database names in .env.example. LLM_MODEL, LLM_API_KEY and GOOGLE_CLIENT_ID stay
# blank for you to fill in (docs/sign-in.md for the last). If a written value fails its check, any
# existing .env stays as it was. Then run ./scripts/start.sh; MCP Inspector's bearer token field
# takes the token (README).
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
db_host_port="$(env_value "$ROOT/.env.example" DB_HOST_PORT)"
db_user="$(env_value "$ROOT/.env.example" POSTGRES_USER)"
db_name="$(env_value "$ROOT/.env.example" POSTGRES_DB)"
token="$(openssl rand -hex 24)"
db_password="$(openssl rand -hex 16)"
hosts="engine:$port,localhost:$host_port,127.0.0.1:$host_port"
public_url="http://localhost:$host_port"
database_url="postgresql+psycopg://$db_user:$db_password@127.0.0.1:$db_host_port/$db_name"
# The new file is built and verified beside .env and renamed over it only when complete, so a
# failure leaves no partial .env. mktemp creates it readable by the owner only, as .env holds
# secrets.
draft="$(mktemp "$ENV_FILE.XXXXXX")"
trap 'rm -f "$draft"' EXIT
cp "$ROOT/.env.example" "$draft"
sed -i "s|^ENGINE_BEARER_TOKEN=.*|ENGINE_BEARER_TOKEN=$token|;
        s|^ENGINE_ALLOWED_HOSTS=.*|ENGINE_ALLOWED_HOSTS=$hosts|;
        s|^ENGINE_PUBLIC_URL=.*|ENGINE_PUBLIC_URL=$public_url|;
        s|^ENGINE_URL=.*|ENGINE_URL=$public_url/mcp|;
        s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$db_password|;
        s|^DATABASE_URL=.*|DATABASE_URL=$database_url|" "$draft"
for key in ENGINE_BEARER_TOKEN ENGINE_ALLOWED_HOSTS ENGINE_PUBLIC_URL ENGINE_URL POSTGRES_PASSWORD \
           DATABASE_URL; do
  env_value "$draft" "$key" >/dev/null
done
mv "$draft" "$ENV_FILE"
echo "Created .env with a generated bearer token and database password."
echo "Fill in LLM_MODEL, LLM_API_KEY and GOOGLE_CLIENT_ID (docs/sign-in.md), then run" \
     "./scripts/start.sh"
