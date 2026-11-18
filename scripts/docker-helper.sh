#!/usr/bin/env bash
#
# Docker Compose helper for the stack: teardown, logs, status. Bringing it up is deploy.sh's job.
# With --ec2 as the first argument it acts on the stack's EC2 instance instead of this machine;
# --ec2 --preview acts on the preview beside it (deploy.sh --ec2 --preview).
#
#   ./scripts/docker-helper.sh --stop [--volumes] [--images]
#       Stop and remove the stack's containers and network. The engine-data volume (market data)
#       and the db-data volume (checks, conversations) are KEPT by default so they
#       survive a restart; --volumes (alias -v) also removes both. --images, with --ec2 only,
#       also removes the images this repo built for the instance (Postgres's is shared, so it
#       stays).
#   ./scripts/docker-helper.sh --logs [-e|--errors]
#       Follow the stack's logs live (last 200 lines). -e filters to ERROR/EXCEPTION/FATAL lines.
#   ./scripts/docker-helper.sh --ps
#       Show the containers' status.
#   ./scripts/docker-helper.sh --ec2 --delete-stack
#       Delete the EC2 stack of the git branch: the instance, its address, the security group
#       and the CloudFront distribution, after asking to type the stack's name. The instance's
#       disk, which holds the database, stays in the account; the command prints its volume id
#       and how to delete it. With --ec2 --preview it deletes everything the preview owns, after
#       one confirmation: its containers, database, market data and images on the instance, then
#       its stack (port rule and CloudFront distribution); production is not touched.
#   -h, --help
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

do_stop() {
  local -a down=(down --remove-orphans)
  local images=""
  while [ $# -gt 0 ]; do
    case "$1" in
      -v|--volumes) down+=(-v) ;;
      --images)
        [ "$TARGET" = ec2 ] || { echo "--images needs --ec2 before it" >&2; exit 2; }
        images=1 ;;
      *) echo "Unknown --stop option '$1'" >&2; exit 1 ;;
    esac
    shift
  done
  compose "${down[@]}"
  # shellcheck disable=SC2046  # one image name per word, none with spaces
  if [ -n "$images" ]; then docker image rm $(ec2_built_images); fi
}

# Removes everything the preview owns after one typed confirmation: its containers, volumes and
# images on the instance, then its stack (port rule and CloudFront distribution). Production's
# containers, images and volumes have other names, so none of them is touched. The instance is
# reached through the host stack alone, so a preview stack whose creation failed, which has no
# outputs, is removed the same way.
delete_preview() {
  local answer image url
  load_aws_config
  resolve_ec2_stack
  require_ec2_host_stack
  EC2_INSTANCE_ID="$(ec2_stack_output "$HOST_STACK_NAME" InstanceId)"
  EC2_HOST="$(ec2_stack_output "$HOST_STACK_NAME" PublicAddress)"
  url="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='CloudFrontUrl'].OutputValue" --output text \
    2>/dev/null)" || url=""
  echo "This deletes the preview $STACK_NAME: its containers, database, market data and images on"
  echo "the instance, and its stack with its port rule and CloudFront distribution."
  read -r -p "Type the stack's name to continue: " answer
  [ "$answer" = "$STACK_NAME" ] || die "Not deleted."
  COMPOSE_FILES+=("$EC2_COMPOSE_FILE")
  open_ec2_docker
  compose down --remove-orphans -v
  for image in $(ec2_built_images); do
    if docker image inspect "$image" >/dev/null 2>&1; then docker image rm "$image"; fi
  done
  if ec2_stack_exists; then
    aws cloudformation delete-stack --stack-name "$STACK_NAME"
    echo "Waiting for the stack to be deleted (a distribution takes several minutes)..."
    aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME"
  fi
  echo "The preview is deleted."
  if [ -n "$url" ] && [ "$url" != None ]; then
    echo "Remove $url from the Google OAuth client's origins and redirect URIs."
  fi
}

do_logs() {
  case "${1:-}" in
    "")           compose logs -f --tail=200 ;;
    -e|--errors)  compose logs -f --tail=200 | grep -Eai '(error|exception|fatal)' ;;
    *) echo "Unknown --logs option '$1'" >&2; exit 1 ;;
  esac
}

TARGET=local
if [ "${1:-}" = --ec2 ]; then TARGET=ec2; shift; fi
# Only --preview selects the preview, never a value left in the calling shell.
unset DEPLOY_PREVIEW
if [ "${1:-}" = --preview ]; then
  [ "$TARGET" = ec2 ] || { echo "--preview needs --ec2 before it" >&2; exit 2; }
  export DEPLOY_PREVIEW=1
  shift
fi
mode="${1:-}"
case "$mode" in
  -h|--help) print_help; exit 0 ;;
  "")        print_help; exit 1 ;;
esac
shift

load_settings
if [ "$mode" = --delete-stack ]; then
  [ "$TARGET" = ec2 ] || { echo "--delete-stack needs --ec2 before it" >&2; exit 2; }
  if [ "${DEPLOY_PREVIEW:-}" = 1 ]; then delete_preview; else delete_ec2_stack; fi
  exit 0
fi
if [ "$TARGET" = ec2 ]; then use_ec2; fi
require_docker
case "$mode" in
  --stop) do_stop "$@" ;;
  --logs) do_logs "$@" ;;
  --ps)   compose ps "$@" ;;
  *) echo "Unknown command: $mode (expected --stop | --logs | --ps | --delete-stack; see -h)" >&2
     exit 1 ;;
esac
