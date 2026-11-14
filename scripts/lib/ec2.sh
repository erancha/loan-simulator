#!/usr/bin/env bash
# The stack's EC2 target: the CloudFormation stack of scripts/template-ec2.yaml, and the instance's
# Docker daemon reached over SSH. Sourced by scripts/common.sh, never executed.
#
# Core responsibilities:
# - load_aws_config: the deploying user's credentials and region, from the gitignored
#   lib/aws-config.sh
# - resolve_ec2_stack / deploy_ec2_stack / resolve_ec2_host: the stack the git branch selects, its
#   deploy, and its instance and addresses
# - ssh_ec2 / use_ec2: a command on the instance, and Compose pointed at the instance's daemon
# - delete_ec2_stack: the stack's deletion, which leaves the instance's disk
#
# The instance accepts SSH as ec2-user with an EC2 Instance Connect key, valid for 60 seconds after
# each push and only for starting a connection, so every connection pushes the key first. One
# throwaway key pair stays on this machine, gitignored; nothing permanent is written to the
# instance.

EC2_TEMPLATE_FILE="$ROOT/scripts/template-ec2.yaml"
EC2_COMPOSE_FILE="$ROOT/docker-compose.ec2.yml"
EC2_HOST_USER='ec2-user'
EC2_SSH_DIR="$ROOT/scripts/lib/.ssh"
EC2_SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -o LogLevel=ERROR)
# The images docker-compose.ec2.yml names, built here and loaded into the instance's daemon.
EC2_IMAGES=(loan-engine:ec2 loan-agent:ec2)
# The latest Amazon Linux 2023 image for ARM, which AWS publishes under this SSM parameter.
EC2_IMAGE_PARAMETER='/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64'
EC2_INSTANCE_TYPE="${EC2_INSTANCE_TYPE:-t4g.small}"

# The settings of aws-config.sh every AWS call needs.
AWS_SETTINGS=(AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION)

load_aws_config() {
  command -v aws >/dev/null || die "Required tool not found: aws"
  source_checked_file "$AWS_CONFIG_FILE" assert_secrets_untracked
  collect_missing_settings aws-config.sh "${AWS_SETTINGS[@]}"
  require_collected_settings
}

# Sets STACK_NAME from the git branch: main deploys loan-simulator, any other branch
# loan-simulator-fb; an exported STACK_NAME wins.
resolve_ec2_stack() {
  local branch
  branch="$(git -C "$ROOT" branch --show-current)"
  if [[ -z "${STACK_NAME:-}" ]]; then
    STACK_NAME='loan-simulator'
    [[ "$branch" == main ]] || STACK_NAME+='-fb'
  fi
}

ec2_stack_exists() {
  aws cloudformation describe-stacks --stack-name "$STACK_NAME" >/dev/null 2>&1
}

# A stack whose first creation failed is left in ROLLBACK_COMPLETE, holding no resources, and
# CloudFormation only allows deleting it; it is deleted so this deploy creates it again.
delete_failed_ec2_stack() {
  local status
  status="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query 'Stacks[0].StackStatus' --output text 2>/dev/null)" || return 0
  [[ "$status" == ROLLBACK_COMPLETE ]] || return 0
  echo "Stack $STACK_NAME failed its first creation and holds nothing; deleting it first..."
  aws cloudformation delete-stack --stack-name "$STACK_NAME"
  aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME"
}

# Prints the value of one output of the stack; fails when the stack lacks it.
ec2_stack_output() {  # key
  local value
  value="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text)"
  [[ -n "$value" && "$value" != None ]] || die "Stack $STACK_NAME has no output $1"
  printf '%s' "$value"
}

# Prints the parameters only a new stack takes: the image, and a default subnet in an
# availability zone that offers the instance type. An existing stack keeps its own, since a
# change of either replaces the instance.
ec2_creation_parameters() {
  local image vpc zones subnet
  image="$(aws ssm get-parameter --name "$EC2_IMAGE_PARAMETER" \
    --query Parameter.Value --output text)"
  vpc="$(aws ec2 describe-vpcs --filters Name=is-default,Values=true \
    --query 'Vpcs[0].VpcId' --output text)"
  [[ "$vpc" != None ]] ||
    die "The region has no default VPC; create one first: aws ec2 create-default-vpc"
  zones="$(aws ec2 describe-instance-type-offerings --location-type availability-zone \
    --filters "Name=instance-type,Values=$EC2_INSTANCE_TYPE" \
    --query 'InstanceTypeOfferings[].Location' --output text | tr '\t' ',')"
  [[ -n "$zones" ]] || die "No availability zone of the region offers $EC2_INSTANCE_TYPE"
  subnet="$(aws ec2 describe-subnets \
    --filters "Name=vpc-id,Values=$vpc" Name=default-for-az,Values=true \
              "Name=availability-zone,Values=$zones" \
    --query 'sort_by(Subnets, &AvailabilityZone)[0].SubnetId' --output text)"
  [[ "$subnet" != None ]] || die "The default VPC has no default subnet in: $zones"
  printf 'ImageId=%s VpcId=%s SubnetId=%s' "$image" "$vpc" "$subnet"
}

# Creates or updates the stack. Port 22 follows this machine's current public address on every
# run.
deploy_ec2_stack() {
  local prefix_list my_address
  local -a parameters
  prefix_list="$(aws ec2 describe-managed-prefix-lists \
    --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing \
    --query 'PrefixLists[0].PrefixListId' --output text)"
  [[ "$prefix_list" != None ]] || die "The region has no CloudFront origin-facing prefix list"
  my_address="$(curl -fsS --max-time 10 https://checkip.amazonaws.com)" ||
    die "Could not read this machine's public address from checkip.amazonaws.com"
  delete_failed_ec2_stack
  parameters=(
    "InstanceType=$EC2_INSTANCE_TYPE"
    "AgentPort=$AGENT_HOST_PORT"
    "SshCidr=$my_address/32"
    "CloudFrontPrefixListId=$prefix_list"
  )
  if ! ec2_stack_exists; then
    local creation
    creation="$(ec2_creation_parameters)"
    # shellcheck disable=SC2206  # three Key=Value words, none with spaces
    parameters+=($creation)
  fi
  echo "Deploying stack $STACK_NAME (a new CloudFront distribution takes several minutes)..."
  aws cloudformation deploy --stack-name "$STACK_NAME" --template-file "$EC2_TEMPLATE_FILE" \
    --no-fail-on-empty-changeset --parameter-overrides "${parameters[@]}"
}

# Sets EC2_INSTANCE_ID, EC2_HOST (the fixed public address) and EC2_URL (the CloudFront address).
resolve_ec2_host() {
  ec2_stack_exists || die "Stack $STACK_NAME is not deployed; run ./scripts/deploy.sh --ec2"
  EC2_INSTANCE_ID="$(ec2_stack_output InstanceId)"
  EC2_HOST="$(ec2_stack_output PublicAddress)"
  EC2_URL="$(ec2_stack_output CloudFrontUrl)"
}

push_ec2_ssh_key() {
  mkdir -p "$EC2_SSH_DIR" && chmod 700 "$EC2_SSH_DIR"
  [[ -f "$EC2_SSH_DIR/key" ]] || ssh-keygen -q -t ed25519 -N '' -f "$EC2_SSH_DIR/key"
  aws ec2-instance-connect send-ssh-public-key --instance-id "$EC2_INSTANCE_ID" \
    --instance-os-user "$EC2_HOST_USER" --ssh-public-key "file://$EC2_SSH_DIR/key.pub" \
    --query Success --output text >/dev/null
}

# Runs ssh to the instance with the given options and command; stdin and stdout pass through.
ssh_ec2() {
  push_ec2_ssh_key
  ssh -i "$EC2_SSH_DIR/key" -o "UserKnownHostsFile=$EC2_SSH_DIR/known_hosts" \
    "${EC2_SSH_OPTS[@]}" "$@"
}

# Waits up to about five minutes until the instance's Docker daemon answers ec2-user: a new
# instance installs Docker on its first boot.
wait_for_ec2_docker() {
  local attempt
  for attempt in $(seq 30); do
    if ssh_ec2 "$EC2_HOST_USER@$EC2_HOST" docker info >/dev/null 2>&1; then return; fi
    sleep 10
  done
  die "The Docker daemon on $EC2_HOST did not answer; check the instance's first boot"
}

# Points docker and Compose of this shell at the instance's daemon: one SSH connection forwards
# the instance's Docker socket to a socket file on this machine, and closes when the script
# exits. Docker's own ssh:// endpoint opens a connection per command, which a pushed key would
# stop admitting after a minute.
open_ec2_docker() {
  local socket="$EC2_SSH_DIR/docker.sock" control="$EC2_SSH_DIR/control"
  rm -f "$socket"
  ssh_ec2 -f -N -T -M -S "$control" -o ExitOnForwardFailure=yes \
    -L "$socket:/var/run/docker.sock" "$EC2_HOST_USER@$EC2_HOST"
  # shellcheck disable=SC2064  # the paths are fixed now, not when the trap runs
  trap "ssh -S '$control' -O exit '$EC2_HOST_USER@$EC2_HOST' 2>/dev/null; rm -f '$socket'" EXIT
  export DOCKER_HOST="unix://$socket"
}

# Selects the EC2 target for the rest of the script: the stack's instance, its Compose override
# and its Docker daemon.
use_ec2() {
  load_aws_config
  resolve_ec2_stack
  resolve_ec2_host
  COMPOSE_FILES+=("$EC2_COMPOSE_FILE")
  open_ec2_docker
}

# Deletes the stack after the operator types its name, and waits until it is gone. The instance's
# disk is not deleted on termination, so its volume id is read first and printed afterwards.
delete_ec2_stack() {
  local volume answer
  load_aws_config
  resolve_ec2_stack
  resolve_ec2_host
  volume="$(aws ec2 describe-instances --instance-ids "$EC2_INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].BlockDeviceMappings[0].Ebs.VolumeId' --output text)"
  echo "This deletes stack $STACK_NAME in $AWS_DEFAULT_REGION: the instance, its address, the"
  echo "security group and the CloudFront distribution at $EC2_URL."
  read -r -p "Type the stack's name to continue: " answer
  [[ "$answer" == "$STACK_NAME" ]] || die "Not deleted."
  aws cloudformation delete-stack --stack-name "$STACK_NAME"
  echo "Waiting for the stack to be deleted (the distribution takes several minutes)..."
  aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME"
  echo "Stack $STACK_NAME is deleted. Its disk, volume $volume, holds the database and stays in"
  echo "the account; delete it with:  aws ec2 delete-volume --volume-id $volume"
}
