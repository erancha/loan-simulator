# 0013. A preview of the working tree runs beside production

- Status: Accepted
- Date: 2026-11-17

## Context

Changes reached the EC2 instance only by deploying production, so a change was first seen on the
real host by its users, and a schema migration first ran on production's data during the deploy
that needed it. A second instance per branch had been refused as cost for nothing
([ADR 0012](0012-the-instance-hosts-the-other-docker-repos.md) puts the group on one instance).

## Decision

`deploy.sh --ec2 --preview` runs the working tree, committed or not, as the guest stack
`loan-simulator-preview` on production's instance: its own CloudFront address, Compose project,
database, image names and ports, all selected by `DEPLOY_PREVIEW` in `stack-params.sh`.
`sql-helper.sh --ec2 --preview --copy-live` streams production's database into the preview's on
the instance and runs the preview's migration on the copy, a rehearsal of production's next
upgrade. `docker-helper.sh --ec2 --preview --delete-stack` removes all of it.

## Consequences

- A change and its migration are tried on the real host and on production's data before
  production runs them; production's containers, images and database are never written.
- The preview takes one of the host's four slots and shares the instance's memory, about 300 MiB
  idle.
- It uses production's model key and Google client; its address is registered with Google once.
