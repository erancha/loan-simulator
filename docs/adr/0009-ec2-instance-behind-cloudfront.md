# 0009. One EC2 instance behind CloudFront for a hosted deployment

- Status: Accepted
- Date: 2026-11-14

## Context

The stack ran only on a workstation, under Docker Compose
([ADR 0007](0007-docker-compose-on-one-machine.md)), and Google sign-in accepts only `localhost`
or a public hostname, so nobody else could reach it. A hosted deployment had to add the fewest
parts: the heavy work is the model's API call, four containers use about 290 MB, and there are
no real users yet. The account's one existing instance serves three live apps with its memory
already committed, so sharing it would put them at risk.

## Decision

`deploy.sh --ec2` runs the same Compose stack on one ARM instance of its own (t4g.small by
default), described by a CloudFormation template, with a CloudFront distribution in front as
the only way in.

- TLS ends at CloudFront, whose own address needs no certificate, domain or DNS record. The hop
  to the instance is plain HTTP to the agent's port, with no reverse proxy on the instance.
- The security group admits the agent's port from CloudFront's servers only, and port 22 from
  the deployer's address, with EC2 Instance Connect keys instead of a stored key pair.
- CloudFront caches only the build's hashed files under `/assets/`; the index, the API, the
  event stream and the health routes always come from the agent.
- The images are built on the deployer's machine for ARM and loaded into the instance's Docker
  daemon over SSH; Compose runs there against the daemon. No registry or secret store: the
  settings reach the instance only inside each container's configuration, on the encrypted disk.
- The instance has an Elastic IP, so its address survives a stop and start, and a disk that is
  not deleted on termination, since it holds the database.

## Consequences

- No load balancer, container service, managed database or DNS zone to pay for or operate.
- The sign-in cookie crosses the hop from CloudFront to the instance unencrypted, and any
  CloudFront distribution, not only this one, passes the security group.
- The instance is a single point of failure, and its disk has no snapshots.
- A replaced instance starts with an empty disk; the data moves with
  `tools/sql-helper.sh --backup` and `--restore`. The ARM build runs under emulation.
