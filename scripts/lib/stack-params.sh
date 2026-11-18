#!/usr/bin/env bash
# Settings of the Compose stack that are neither secret nor private, committed so every checkout
# runs the same stack. Sourced by scripts/common.sh, never executed; the agent started on the host
# reads it too (backend/src/loan_agent/platform/config.py), so every setting is one plain export
# line with a quoted value, which may name a key set above it as ${KEY}. Secrets are in secrets.sh
# and this deployment's own settings in params.sh, both gitignored.
#
# Compose hands each container only the keys it reads, listed per service in docker-compose.yml.
# Engine keys use the ENGINE_ prefix, except ENGINE_URL, the agent's address for the engine. A
# commented-out line shows an optional key at its default; uncomment it to set the key.

# ── Ports ────────────────────────────────────────────────────────────────────────
# The port the engine listens on inside its container.
export ENGINE_PORT="8020"
# Read by docker-compose.yml only: the port published on this machine's loopback interface, where
# MCP Inspector connects; it must be free on the host.
export ENGINE_HOST_PORT="8100"
# Read by docker-compose.yml only: the port the agent listens on inside its container; compose
# passes it to the agent image's start command, not to the agent's settings.
export AGENT_PORT="8000"
# Read by docker-compose.yml only: the loopback port the agent's API is published on; the page and
# sign-in use it. It must be free on the host.
export AGENT_HOST_PORT="8101"
# Read by docker-compose.yml only: the loopback port Postgres is published on, for an agent started
# on the host (DATABASE_URL of secrets.sh names it) or a psql on this machine. It must be free on
# the host.
export DB_HOST_PORT="8102"

# ── EC2 ──────────────────────────────────────────────────────────────────────────
# Read by scripts/lib/ec2.sh only, for deploy.sh --ec2. The stack's name on main; any other
# branch deploys EC2_STACK-fb.
export EC2_STACK="loan-simulator"
# Used only when the stack is a host (EC2_HOST_STACK of params.sh blank): the instance's ARM
# type, sized for every stack it runs; a change stops and starts the same instance.
export EC2_INSTANCE_TYPE="t4g.small"

# ── Preview ──────────────────────────────────────────────────────────────────────
# DEPLOY_PREVIEW=1, which the scripts export for --ec2 --preview and clear otherwise, selects the
# preview: the working tree run beside production on the same EC2 instance, as a guest stack
# (load_settings of common.sh names its host) with its own CloudFront address, Compose project
# (so its own database), image names and ports. It comes before every value derived from the
# ports, so those follow.
if [[ "${DEPLOY_PREVIEW:-}" == 1 ]]; then
  export ENGINE_HOST_PORT="8110"
  export AGENT_HOST_PORT="8111"
  export DB_HOST_PORT="8112"
  export STACK_NAME="$EC2_STACK-preview"
  export COMPOSE_PROJECT_NAME="$EC2_STACK-preview"
  # Read by docker-compose.ec2.yml: appended to each built image's name.
  export EC2_IMAGE_SUFFIX="-preview"
else
  export EC2_IMAGE_SUFFIX=""
fi

# The port CloudFront reaches this stack at on the instance; every stack on the instance has its
# own.
export EC2_ORIGIN_PORT="${AGENT_HOST_PORT}"

# ── Engine access ────────────────────────────────────────────────────────────────
# The Host header values the engine answers, comma separated, none empty: the address inside the
# Compose network, plus localhost and 127.0.0.1 at ENGINE_HOST_PORT, for MCP Inspector on this
# machine.
export ENGINE_ALLOWED_HOSTS="engine:${ENGINE_PORT},localhost:${ENGINE_HOST_PORT},127.0.0.1:${ENGINE_HOST_PORT}"
# The base URL callers reach the engine at: http or https, no /mcp, no trailing slash.
export ENGINE_PUBLIC_URL="http://localhost:${ENGINE_HOST_PORT}"
# The engine's MCP endpoint as the agent reaches it, path included. Compose replaces it with the
# in-network address (http://engine:<ENGINE_PORT>/mcp); the value here serves an agent started on
# the host.
export ENGINE_URL="${ENGINE_PUBLIC_URL}/mcp"

# ── Database ─────────────────────────────────────────────────────────────────────
# Read by docker-compose.yml only: the port Postgres listens on inside its container.
export DB_PORT="5432"
# Read by docker-compose.yml only: the Postgres user and database the agent's tables live in; also
# read by init-env.sh and tools/sql-helper.sh, and set when the database volume is first created.
export POSTGRES_USER="loan"
export POSTGRES_DB="loan"

# ── Sign-in ──────────────────────────────────────────────────────────────────────
# The issuer every ID token must name.
# export AUTH_ISSUER="https://accounts.google.com"
# Where the issuer publishes the keys that sign its tokens.
# export AUTH_JWKS_URL="https://www.googleapis.com/oauth2/v3/certs"
# Tests only: a PEM public key file that verifies tokens instead of the published keys, so a test
# signs its own tokens and never reaches Google.
# export AUTH_PUBLIC_KEY_FILE=""

# ── Turn cap ─────────────────────────────────────────────────────────────────────
# Messages one person may send, across all their checks, in any rolling window; each message costs
# model calls. AGENT_TURN_LIMIT_OVERRIDES of params.sh replaces it per person.
# export AGENT_TURN_LIMIT="20"
# The length of that rolling window, in hours.
# export AGENT_TURN_WINDOW_HOURS="24"

# ── Sign-in cookie ───────────────────────────────────────────────────────────────
# True where people reach the agent only over HTTPS that ends before it, so the sign-in cookie is
# marked Secure; docker-compose.ec2.yml sets it for the EC2 instance behind CloudFront.
# export AGENT_HTTPS_ONLY="false"

# ── Logging ──────────────────────────────────────────────────────────────────────
# The agent's log level: DEBUG, INFO, WARNING, ERROR or CRITICAL.
# export AGENT_LOG_LEVEL="WARNING"

# ── Page ─────────────────────────────────────────────────────────────────────────
# The built page's folder. The agent image sets it to its own copy and compose does not pass this
# key. An agent started on the host sets it to frontend/dist, or leaves it unset to serve the API
# only.
# export AGENT_FRONTEND_DIST=""

# ── Storage ──────────────────────────────────────────────────────────────────────
# Folder holding the engine's stored market data (market.json); compose mounts the engine-data
# volume at /data, the default.
# export ENGINE_DATA_DIR="/data"
