# 0014. Any Docker Compose repo's stack can host the instance

- Status: Accepted
- Date: 2026-11-18

## Context

[ADR 0012](0012-the-instance-hosts-the-other-docker-repos.md) made this repo's stack the host of the
group's one instance, and every other repo's committed `stack-params.sh` named it as theirs. A
person who cloned another repo of the group alone had no such stack, so that repo's `deploy.sh
--ec2` stopped on a missing host. Which repos share an instance is a choice of each deployment, not
a property of a repo.

## Decision

`EC2_HOST_STACK` moves to the gitignored `params.sh`, blank in `params.example.sh`. Blank, the
repo's stack is a host with an instance of its own; set to another repo's host stack, it is a guest
on that instance. Every repo commits `EC2_INSTANCE_TYPE`, which only a host uses. The rest of ADR
0012 holds: one template, the host's four guest slots, a guest per repo.

## Consequences

- Any one repo deploys alone, and any repo of the group can be the host of the others; a person
  who can afford several instances makes several repos hosts.
- The host goes first, and CloudFormation refuses to delete it while a guest imports its exports.
- Moving the host to another repo starts a new instance with an empty disk: each stack's data
  comes back only from its own backup (`tools/sql-helper.sh --ec2`).
