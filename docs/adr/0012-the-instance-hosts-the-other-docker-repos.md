# 0012. The instance hosts the other Docker Compose repos

- Status: Accepted
- Date: 2026-11-16

## Context

`deploy.sh --ec2` ran the stack on an instance of its own
([ADR 0009](0009-ec2-instance-behind-cloudfront.md)), and its stack owned that instance outright.
home-finance-agent, cal-agent and amex-agent, the other repos of the Docker Compose group, were
to deploy the same way into the same AWS account. None of the four has more than a handful of
users, so four instances would cost four times one for capacity nobody uses, and one repo's
stack owning the instance meant the others could only reach it by depending on that stack.

## Decision

One instance serves the group. This repo's stack is its host: it owns the instance, its Elastic
IP and its security group, and exports the instance and the address. It also offers four empty
security groups attached to the instance, slots that name no guest. Each other repo deploys a
guest stack, from the same template file, which names this stack, claims a free slot and opens
only its own port there, to CloudFront alone, and adds its own CloudFront distribution in front
of that port. Each repo runs its own Compose project on the instance's one Docker daemon.

- A rule admitting CloudFront's servers counts as 55 of a group's 60 rules, so each stack's rule
  needs a group of its own; the host offers the slots rather than naming its guests, and a
  deleted guest's rule leaves with its stack and frees its slot.

- The template, `scripts/lib/ec2.sh`, the settings guard and the pre-commit hook are the same
  files in every repo of the group; a repo's own values (its stack name, its host, its port)
  live in its `stack-params.sh`.
- A guest deploy from an address the host's SSH rule does not admit updates only that parameter
  of the host stack.
- A feature branch deploys `<stack>-fb` onto the host's own `-fb` stack, so it never touches the
  stacks of `main`.

## Consequences

- One instance's cost for the group; each app keeps its own address and is deleted alone.
- CloudFormation refuses to delete the host stack while a guest imports its exports, so the
  instance cannot disappear from under a guest.
- The apps share the instance's memory and disk: the instance type is sized for all of them, and
  one app's load or failure can starve the others.
- An app that outgrows the instance blanks its `EC2_HOST_STACK`, which turns its stack into a
  host with an instance of its own; its distribution and address stay, and its data moves with
  its own backup and restore.
