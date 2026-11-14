#!/usr/bin/env bash
#
# Deploy the loan simulator: build the images and start Postgres, the engine and the agent in
# Docker Compose, then return once the agent answers.
#
#   ./scripts/deploy.sh          on this machine's Docker
#   ./scripts/deploy.sh --ec2    on an EC2 instance deployed by the stack (created on the first
#                                run, reused afterwards), behind CloudFront
#   -h, --help                   show this help
#
# Before the agent starts, a one-shot container (the migrate service) brings the agent's Postgres
# tables up to the current schema with Alembic, then exits. The engine fetches the market data
# before it listens, so every start takes a few seconds; when a fetch fails it serves the data
# stored by an earlier start. The agent refuses to start when LLM_MODEL, LLM_API_KEY or
# GOOGLE_CLIENT_ID is blank, so the script checks them first, with the other keys the agent
# needs, and names every one that is blank with its settings file. Every run starts with
# ./scripts/init-env.sh, which creates a missing settings file and keeps the existing ones, so a
# first run creates them all and then stops on the settings left to fill in.
# Stop or inspect the stack with ./scripts/docker-helper.sh (--stop / --logs / --ps), which takes
# --ec2 too.
#
# On this machine the services are published on the loopback interface: the agent at
# localhost:AGENT_HOST_PORT (/health, /ready, /api; localhost is the origin Google sign-in is
# registered for), the engine at ENGINE_URL (MCP Inspector, with the bearer token of secrets.sh)
# and Postgres at 127.0.0.1:DB_HOST_PORT.
#
# --ec2 also needs the access key pair and region in scripts/lib/aws-config.sh, and deploys to
# the account its credentials belong to.
# It creates or updates the CloudFormation stack of scripts/template-ec2.yaml (the git branch
# selects it: loan-simulator on main, loan-simulator-fb on any other branch): one ARM instance
# with Docker, a fixed address, and a CloudFront distribution whose https address is the only way
# in. It then builds the images here for ARM, loads them into the instance's Docker daemon over
# SSH, and runs Compose against that daemon. The settings files stay on this machine; each
# container's own settings, secrets included, reach the instance as part of the container's
# configuration, which Docker keeps on the instance's encrypted disk. The instance type is
# t4g.small unless EC2_INSTANCE_TYPE names another; a change stops and starts the same instance.
# Register the printed address with Google once (docs/sign-in.md).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

TARGET=local
case "${1:-}" in
  -h|--help) print_help; exit 0 ;;
  --ec2)     TARGET=ec2 ;;
  "")        ;;
  *)         print_help >&2; exit 2 ;;
esac

"$SCRIPT_DIR/init-env.sh"
load_settings
collect_missing_settings stack-params.sh ENGINE_URL
collect_missing_settings secrets.sh DATABASE_URL ENGINE_BEARER_TOKEN LLM_API_KEY
collect_missing_settings params.sh LLM_MODEL GOOGLE_CLIENT_ID
require_collected_settings
require_docker

deploy_local() {
  local agent_url="http://localhost:$AGENT_HOST_PORT"
  echo "Building and starting the database, the engine and the agent..."
  compose up -d --build
  wait_for_http "$ENGINE_URL" \
    || { echo "the engine did not answer on $ENGINE_URL; see ./scripts/docker-helper.sh --logs" >&2
         exit 1; }
  wait_for_http "$agent_url/health" \
    || { echo "the agent did not answer on $agent_url; see ./scripts/docker-helper.sh --logs" >&2
         exit 1; }
  echo "The agent answers at $agent_url (health: /health, ready: /ready)."
  echo "The engine answers at $ENGINE_URL (bearer token: ENGINE_BEARER_TOKEN of secrets.sh)."
  echo "  stop it or tail logs:  ./scripts/docker-helper.sh --stop | --logs"
}

deploy_ec2() {
  load_aws_config
  resolve_ec2_stack
  deploy_ec2_stack
  resolve_ec2_host
  COMPOSE_FILES+=("$EC2_COMPOSE_FILE")

  echo "Building the images for linux/arm64 on this machine..."
  compose build
  wait_for_ec2_docker
  echo "Loading the images into the instance's Docker daemon..."
  docker save "${EC2_IMAGES[@]}" | gzip | ssh_ec2 "$EC2_HOST_USER@$EC2_HOST" 'gunzip | docker load'

  open_ec2_docker
  echo "Starting the database, the engine and the agent on the instance..."
  compose up -d --no-build --remove-orphans
  # A deploy leaves the previous build's layers behind; the instance's disk is small.
  docker image prune -f >/dev/null
  wait_for_http "$EC2_URL/health" \
    || { echo "the agent did not answer on $EC2_URL/health;" \
              "see ./scripts/docker-helper.sh --ec2 --logs" >&2
         exit 1; }
  echo "The agent answers at $EC2_URL (health: /health, ready: /ready)."
  echo "  Register it with Google once: $EC2_URL as an authorized JavaScript origin and"
  echo "  $EC2_URL/ as an authorized redirect URI of the OAuth client (docs/sign-in.md)."
  echo "  stop it or tail logs:  ./scripts/docker-helper.sh --ec2 --stop | --logs"
}

"deploy_$TARGET"
