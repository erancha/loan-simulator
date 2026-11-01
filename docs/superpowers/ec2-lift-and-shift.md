# EC2 lift and shift

How to run the loan simulator on AWS with the fewest resources: the Docker Compose stack moves
unchanged onto one EC2 instance, and CloudFront serves it over HTTPS. The short-term plan is what
ships first; the long-term plan lists enhancements that are each optional and independent.

This note covers the loan simulator's own deployment. Everything about the AWS account itself
lives in `/mnt/c/Projects/-- docs --/aws-account-inventory.md`, called the inventory below: the
instances, access, credentials, costs, and the decisions already made and still open.

## Short-term plan

### Decisions

- **2026-10-30, TLS ends at CloudFront.** The viewer's browser talks HTTPS to CloudFront's edge,
  CloudFront terminates TLS there, and the hop from the edge to the instance is plain HTTP to
  the agent's published port.
- **2026-10-30, only the hashed build files are cached.** Vite names the page's script and
  stylesheet under `/assets/` with a content hash, so a new build gets new names and the edge
  can hold them for a long time. Everything else always comes from the origin: `index.html` and
  `favicon.svg` have fixed names and would point at a previous build's files; `/api/*` is
  per-person and changes on every request; `/health` and `/ready` cached would hide an outage.
  The agent sends ETag and Last-Modified but no Cache-Control, so the TTLs are CloudFront's.
- **2026-10-31, no reverse proxy.** The agent's own server is CloudFront's origin. A proxy would
  earn its place only with TLS at the origin, which is a long-term item.
- **2026-10-31, the host is undecided.** The account's two running t4g.small instances are
  unmonitored and their availability is unknown, so they are put in order before choosing between
  reusing one and adding an instance. A separate session handles that work, starting from the
  inventory.

### Proposed, not decided

Nothing in this section is agreed yet. Where it conflicts with the steps below, the steps are
pending this decision: step 1 copies the repo onto the instance, and the proposal does not.

**Deployment mechanism**

- `deploy.sh` creates one CloudFormation stack in one phase: the security group, the Elastic IP,
  the instance and the CloudFront distribution. The Elastic IP does not force a second phase. The
  template builds the origin's DNS name from the address, and it must not use the instance's
  `PublicDnsName`, which resolves before the Elastic IP is attached.
- User data only installs Docker and adds the login user to the docker group.
- The app is deployed by a Docker context over SSH, so `start.sh` and `docker-helper.sh` run on
  this machine against the instance's Docker daemon, selected by an `--aws` flag in `common.sh`.
  Without the flag, local runs stay as they are.
- A Compose override file publishes the agent on the instance's address. Compose reads the local
  `.env`, so secrets stay on this machine, with no SSM parameters and no repo on the instance.
- `start.sh` waits on the containers' healthchecks through `docker compose ps`, because a
  localhost URL does not answer when the daemon is remote.
- A code update is `start.sh --aws` again. `deploy.sh` runs only when the infrastructure changes.
- Registering the CloudFront address with Google stays a manual, one-time step, and `deploy.sh`
  prints the address.
- The stack is removed with `delete-stack.sh`, and AWS settings live in `scripts/aws-config.sh`
  with its `.example`, following the AWS-repo conventions.

The stack's contents assume a new instance. Reusing an existing one, which another stack owns,
would drop the instance from this stack and may change how its security group is handled.

**Open choices**

1. Postgres data: a separate EBS volume the stack keeps, or accept losing the data when the
   instance is replaced, while there are no real users.
2. SSH for the Docker context: through Session Manager with port 22 closed, or port 22 open to
   one IP address.
3. Instance: reuse one, merge, or add a third. Instance type follows from that choice.

**Agreed direction, pending the host choice**

- The family stays t4g. The base images are multi-architecture, the Dockerfiles need no change,
  and the active reservation and the free trial apply only to t4g.
- The inventory gives the EC2 session's brief. Its report on memory, exposure and merging decides
  the host.
- Without a merge, a third t4g.small is billed on demand from day one. The inventory's Reservations
  section gives the price and the end of the free trial.

**Sizing**

- The loan stack measured locally takes about 290 MB running and 1.4 GB of disk for its images.
- home-finance-agent, cal-agent and amex-agent may follow it to AWS. All four would need about
  3.2 GB at most before the OS, counted from their Compose memory limits. All three should run on
  ARM, which one build of each image on ARM confirms.
- Building on the instance is the tight point: Node and Maven builds can peak near the 1 GB free
  on a small instance. A swap file helps, and images built elsewhere for ARM avoid the problem.

### What runs where

- **One EC2 instance** (t4g.small or t3.small) runs the current `docker compose`: Postgres, the
  migration, the engine and the agent. The heavy work is the model API call, not local compute.
- **CloudFront** in front of it, at its own `https://<id>.cloudfront.net` address. That address
  comes with HTTPS built in: no certificate, no domain, no DNS record.
- Nothing else: no load balancer, ECS, RDS, Route 53 or NAT gateway.

### Steps

1. **Launch the instance** in a public subnet, with Docker and the Compose plugin installed.
   Copy the repo and create `.env` with `./scripts/init-env.sh`, then fill `LLM_API_KEY` and
   `GOOGLE_CLIENT_ID`.
2. **Attach an Elastic IP.** Without one, the instance's public address and DNS name change on
   every stop and start, and CloudFront's origin breaks. It costs what any public IPv4 address
   costs (about $3.6 a month), so it adds nothing over the address the instance needs anyway.
3. **Expose the agent.** Compose publishes the agent on `127.0.0.1` only (the `ports` entry of
   the `agent` service in `docker-compose.yml`). On the instance it is published on the
   instance's address instead, so CloudFront reaches it. The engine and Postgres stay local.
4. **Lock the instance to CloudFront.** The security group allows the agent's port only from
   AWS's managed prefix list `com.amazonaws.global.cloudfront.origin-facing`, so nobody can
   bypass CloudFront.
   SSH stays closed; use Session Manager or open 22 to your own IP only.
5. **Create the CloudFront distribution:**
   - **Origin:** the instance's public DNS name (the `ec2-…amazonaws.com` name of the Elastic IP),
     protocol HTTP, on the agent's published port.
   - **Default behavior:** caching disabled; forward all viewer headers, cookies and query
     strings. Sign-in rides on the `ls_id_token` cookie, and the event stream on the
     `Last-Event-ID` header. This covers `index.html`, `/api/*`, `/health` and `/ready`.
   - **`/assets/*` behavior:** a caching policy with a long TTL, for the hashed build files.
   - **Viewer protocol:** redirect HTTP to HTTPS.
   - The event stream stays open: CloudFront cuts a response after 30 silent seconds, and the
     agent sends a keep-alive every 15 seconds.
6. **Register the address with Google.** In the OAuth client, add `https://<id>.cloudfront.net`
   under Authorized JavaScript origins and `https://<id>.cloudfront.net/` under Authorized
   redirect URIs.
7. **Back up Postgres** with scheduled EBS snapshots (Data Lifecycle Manager); no database service.

### Costs

- The instance: a few dollars to about $15 a month, depending on type and region.
- The Elastic IP: about $3.6 a month.
- CloudFront and EBS: small at this traffic.

### Known limits

- **CloudFront to the instance is plain HTTP.** The viewer's connection is HTTPS, but the hop
  from CloudFront's edge to the instance crosses the internet unencrypted, sign-in cookie
  included. The first long-term item closes this.
- **The sign-in cookie is not marked Secure.** The agent sets `Secure` only when the request it
  sees is HTTPS (the `secure=` argument of `set_cookie` in
  `backend/src/loan_agent/platform/api/auth.py`), and behind an HTTP origin it sees HTTP. The
  browser still sends it only to this site, over HTTPS, but a fix needs the agent to trust the
  forwarded protocol, or the proxy to pass it on.
- **One machine.** The agent runs as a single copy, matching the scaling-safety item already on
  the list, and the instance is a single point of failure.

## Long-term plan

Each item is independent; add one only when its reason applies.

### Decisions

- **2026-10-30, HTTPS to the origin is a later enhancement**, not part of the first deployment.
- **2026-10-31, Caddy if TLS reaches the origin.** It obtains and renews its own certificates;
  nginx, the proxy in the other Compose repos, would need a renewal sidecar for the same job.

### HTTPS from CloudFront to the instance

When: before real users sign in, to stop the cookie crossing the internet in plain text.

- Caddy on the instance, in front of the agent, terminates HTTPS on port 443 with a Let's Encrypt
  certificate, and the origin switches to HTTPS on 443 (the security group allows 443 from the
  CloudFront list).
- The certificate needs a name Let's Encrypt will issue for. The `amazonaws.com` names may be
  refused, so this goes with an own domain (below) or a Let's Encrypt certificate for the IP.

### A private instance (VPC origin)

When: the instance should have no public address at all.

- CloudFront reaches an instance in a private subnet directly, inside AWS, so plain HTTP to it is
  acceptable and the security-group lock is unnecessary.
- The agent still calls out (the LLM API, Google's sign-in keys, the Bank of Israel data), which
  from a private subnet needs a NAT gateway: about $32 a month plus data, far more than the
  Elastic IP it saves.

### Your own domain

When: a name like `loans.example.com` is wanted instead of `<id>.cloudfront.net`.

- A free ACM certificate for the name, created in `us-east-1` (where CloudFront reads
  certificates from), attached to the distribution as an alternate domain name.
- A CNAME record from the name to the distribution, at any DNS provider; Route 53 is not needed.
- The new address added to the Google OAuth client, as in step 6.

### Lightsail instead of EC2

When: a flat monthly price is preferred over EC2's separate charges.

- The same Compose stack on a Lightsail instance with a static IP, CloudFront in front as above.
