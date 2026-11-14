#!/usr/bin/env bash
# Secrets of the Compose stack. ./scripts/init-env.sh copies this file to lib/secrets.sh
# (gitignored) and fills in the generated values; fill in the rest there and never commit it.
# Every line is a plain export KEY="value": the scripts source the file, and the agent started on
# the host reads it too.

# Required: the static bearer token every MCP call must present, at least 32 characters. The
# engine checks it and the agent presents it, so it is defined only here. init-env.sh writes a
# generated 48-character value.
export ENGINE_BEARER_TOKEN=""

# Required: the password of POSTGRES_USER, set when the database volume is first created; changing
# it later needs --volumes on the stop (docker-helper.sh) or ALTER USER. init-env.sh writes a
# generated value.
export POSTGRES_PASSWORD=""

# Required: the agent's database in SQLAlchemy form, as the host reaches it (DB_HOST_PORT of
# stack-params.sh). Compose replaces it with the in-network address (db:<DB_PORT>). init-env.sh
# writes it with the generated POSTGRES_PASSWORD.
export DATABASE_URL=""

# Required: the provider's API key for LLM_MODEL of params.sh. Fill in by hand.
export LLM_API_KEY=""
