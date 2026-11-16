# Demo deployment plan

A temporary, public demo of TraceScan on one small VM paid by free credit. The traces are seeded
synthetic ones, so Medas is not deployed and the collector is not reachable from the internet.
This narrows PLAN.md's **Deploy** task ("Docker Compose with Medas, TraceScan, the trace collector
and Postgres") to what a demo needs; the live path from Medas stays a local setup.

## Decisions

| Question | Choice | Why |
| --- | --- | --- |
| Host | AWS Lightsail `medium_3_0` (2 vCPU / 4 GB / 80 GB, x86, $24 a month) on Ubuntu 24.04, in the project's Region, `eu-north-1` (Stockholm) | The free plan's $100 credit covers about 4 months (more if the credit is raised to $200); x86 means the images build as they do here. Not the cheaper IPv6-only bundle: GitHub and some viewers have no IPv6 |
| How it runs | The existing `docker compose --profile app`, plus Caddy | No code change; the app's one-process assumptions (run limit in memory, `Runs.recover`) hold on one box |
| HTTPS | Caddy, on a free `sslip.io` name (`tracescan.<ip>.sslip.io`) | Clerk needs HTTPS off localhost; Caddy gets and renews the certificate itself |
| Traces | `scripts.seed_traces`, a fresh day before each demo | No Medas, no public collector, no clinical text |
| Collector | Not routed by Caddy | Nothing outside the box can post spans |
| Sign-in | The current Clerk development instance | A production instance needs a domain of our own; invite the demo's viewers |
| Writes | `DRY_RUN` on (the default) | Approved issues land in `backend/out`, nothing goes to GitHub |

Set aside: Cloud Run + Neon (free, but needs the model baked into the image, a migration job and
cold starts), and the 512 MB free tiers (too small). Fallback if the deploy slips: run the demo on
the laptop, where localhost needs no HTTPS.

## Steps

### 1. Measure memory locally

Run `docker compose --profile app up -d --build`, start a run on a seeded day and watch
`docker stats` until it pauses at the review.
**Done when** the peak of all four containers is written down and fits in 4 GB with room to spare
(if it does not, take the 8 GB plan).

**Done 2026-11-16:** a run over the 52 seeded traces, through Caddy, up to the review: peak 776 MiB
in all (backend 580, frontend 77, Postgres 76, Caddy 50), sampled every 2 s. 4 GB leaves plenty of
room; the run itself would fit 2 GB, but `next build` and `uv sync` on the box want the headroom.

### 2. Add the production pieces to the repo

- `deploy/Caddyfile`: the site name from an environment variable, `reverse_proxy frontend:3000`,
  nothing for `/v1/traces`.
- `docker-compose.prod.yml`, an override used with `-f docker-compose.yml -f docker-compose.prod.yml`:
  a `caddy` service (pinned image, ports 80 and 443 published, a volume for its certificates,
  `profiles: [app]`), and `CLERK_AUTHORIZED_PARTIES` set to `https://${SITE}` on the backend.
- A short "Deploy the demo" section in the README with the commands below.

**Done when** the override starts locally with `SITE=localhost` (Caddy's local certificate) and the
UI signs in through it.

**Done 2026-11-16:** signed in on `https://localhost` and streamed a run to the review through Caddy.
Leaving `/v1/traces` out of Caddy was not enough: the frontend's `/api/:path*` rewrite hands
`POST /api/traces` to the collector, so the Caddyfile answers that route with a 404.

### 3. Create the server

The AWS project: free plan, $100 credit, plan ends 2027-05-16, Region `eu-north-1` (confirm in
AWS Settings > View all projects > Overview > Additional info > Region). Every command below uses
`--profile tracescan --region eu-north-1`. Nothing is created outside that Region.

- **Spend alerts:** an AWS Budgets cost budget of $20 with email alerts at 25%, 80% and 100%
  ($5, $16 (about 2026-12-06, the cue to tear down) and $20). It alerts, it does not stop anything: at $24 a month the server alone reaches $20 in
  under a month.
- **SSH key:** `aws lightsail import-key-pair --key-pair-name tracescan --public-key-base64 "$(cat ~/.ssh/id_ed25519.pub)"`.
- **Instance:** `aws lightsail create-instances --instance-names tracescan-demo --availability-zone eu-north-1a --blueprint-id ubuntu_24_04 --bundle-id medium_3_0 --key-pair-name tracescan --user-data file://deploy/lightsail-init.sh`.
  `deploy/lightsail-init.sh` (to write): installs Docker Engine and the compose plugin from
  Docker's apt repository, adds `ubuntu` to the `docker` group and makes a 2 GB swap file.
- **Static IP:** `allocate-static-ip --static-ip-name tracescan-ip` and `attach-static-ip`
  (free while attached). The `sslip.io` name is built from it.
- **Firewall:** `put-instance-public-ports` with exactly 80/tcp, 443/tcp and 443/udp open to all,
  and 22/tcp only from my IP (`cidrs` `<ip>/32`). Postgres, the backend and the frontend stay
  on the server's localhost (the base compose file binds them to `127.0.0.1`).

**Done when** `ssh ubuntu@<static ip>` works, `docker compose version` answers on the server,
and `get-instance-port-states` shows only those four rules.

**Done 2026-11-16:** budget `tracescan-demo` ($20 a year, lowered from $80 the same day; credits excluded, so it tracks what the
credit pays; alerts at 25% and 100%), key pair `tracescan`, instance `tracescan-demo`, static IP
`tracescan-ip` = `13.50.197.100` (so `SITE=tracescan.13-50-197-100.sslip.io`), the four port
rules. Lightsail names are unique across resource types, hence `tracescan-demo`. The user data
failed on first boot: Lightsail prepends its own `#!/bin/sh` script, so a bash shebang is
ignored and `set -o pipefail` stopped it; the script is now POSIX sh and was run over SSH. Docker
Compose 5.7.1 and the 2 GB swap answer on the server.

### 4. Deploy

- `git clone` the repo on the server; copy `backend/.env` and `frontend/.env.local` with `scp`
  (never commit them). On the server: a strong `POSTGRES_PASSWORD` in the root `.env`, a new
  `COLLECTOR_TOKEN_MEDAS`, `DRY_RUN` left on.
- OpenRouter: a separate key for the demo with a credit limit (for example $10).
- Clerk dashboard: allow the `sslip.io` origin if the instance asks for it; invite the viewers.
- `SITE=tracescan.<ip>.sslip.io docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile app up -d --build`

**Done when** `https://tracescan.<ip>.sslip.io` shows the sign-in page with a valid certificate and
`/v1/traces` is not reachable from outside.

**Done 2026-11-16:** the code went over as a `git archive` of the branch (no GitHub access on the
server). The server's `backend/.env` is the local one without `GITHUB_TOKEN`/`GITHUB_REPO`, with
`DRY_RUN=1` (the local file has it off), a new `COLLECTOR_TOKEN_MEDAS` and the demo OpenRouter
key; the root `.env` (`SITE`, `POSTGRES_PASSWORD`) was generated on the server. Checked from
outside: `/` redirects to the Clerk sign-in, which renders with no console error (the development
instance accepts the `sslip.io` origin), a Let's Encrypt certificate, HTTP redirects to HTTPS,
`/api/health` answers, `POST /api/traces` is a 404, `/api/runs` without a session a 401, and
5433, 8010 and 3010 are closed.

### 5. Seed the traces

From the laptop, through an SSH tunnel to the server's Postgres (bound to the server's localhost):

```bash
ssh -N -L 15433:127.0.0.1:5433 ubuntu@<ip>
```

```bash
cd backend && DATABASE_URL=postgresql://postgres:<password>@127.0.0.1:15433/postgres uv run python -m scripts.seed_traces --end <shortly before the demo>
```

**Done when** the Traces page on the server lists 52 traces.

**Done 2026-11-16:** 52 traces, 216 spans, a day ending 12:29 UTC; the root spans run from
2026-11-15 12:29 to 2026-11-16 12:01 UTC. In a script, start the tunnel in the foreground shell
(`ssh -N -L ... &` on its own line, then `kill` its pid): chained into `cd ... && S=... && ssh ... &`
the whole chain runs in a subshell, and a leftover tunnel holds the port for the next try.

### 6. Check a run end to end

Sign in, start a run over the seeded day, watch it stream, review it, approve one finding.
**Done when** the run completes and its issue file is in `backend/out/issues/` on the server. This
is PLAN.md's Deploy check: tick it then, and note there that Medas is not part of the deployed demo.

### 7. Keep it alive and tear it down

- Before each demo: seed a new day (step 5) so "the last 24 hours" has traces.
- A Lightsail snapshot once it works (the database lives on the instance; snapshots cost about
  $0.05 per GB a month).
- **Teardown by 2026-12-11** (decided 2026-11-16): the demo may use at most $20 of the credit,
  and at $24 a month ($0.80 a day) that is about 25 days. Budget alerts and stopping the instance
  do not cap it (a stopped Lightsail instance is still billed), so only deleting does. In
  `eu-north-1`, with `--profile tracescan`:
  `aws lightsail delete-instance --instance-name tracescan-demo`, then
  `release-static-ip --static-ip-name tracescan-ip` (a detached one is billed),
  `get-instance-snapshots` and `delete-instance-snapshot` for each, and
  `delete-key-pair --key-pair-name tracescan`; revoke the demo OpenRouter key; check
  `get-instances` and `get-static-ips` come back empty. A free plan that runs out of credit or time closes
  the account's resources unless it is upgraded to the paid plan.

## Risks

| Risk | Mitigation |
| --- | --- |
| Clerk's development instance refuses the `sslip.io` origin | Check in step 4; else a cheap domain and a production instance |
| A viewer starts many runs | The run limit (10 an hour per user), the per-run budget ($2) and the key's credit limit |
| The server is lost | It holds only seeded data; the snapshot and step 5 rebuild it |
| The credit runs out unnoticed | Budget alerts, teardown date in the calendar (about 4 months at $24, and no later than 2027-05-16) |
| Sudden "Access Denied" on calls that worked | Check the credit and plan state in AWS Settings > Billing first |
