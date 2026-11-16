# Demo deployment plan

A temporary, public demo of TraceScan on one small VM paid by free credit. The traces are seeded
synthetic ones, so Medas is not deployed and the collector is not reachable from the internet.
This narrows PLAN.md's **Deploy** task ("Docker Compose with Medas, TraceScan, the trace collector
and Postgres") to what a demo needs; the live path from Medas stays a local setup.

## Decisions

| Question | Choice | Why |
| --- | --- | --- |
| Host | AWS Lightsail, 2 vCPU / 4 GB, Linux, x86, an EU region | The free plan's credit ($100, up to $200) covers it for about 6 months; x86 means the images build as they do here |
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

- AWS account on the free plan; an AWS Budgets alert at $20 and $80.
- Lightsail instance (Ubuntu LTS), a static IP, firewall: 80 and 443 open, 22 only from my IP.
- Docker Engine and the compose plugin installed; a 2 GB swap file as a safety net.

**Done when** `ssh` works and `docker compose version` answers on the server.

### 4. Deploy

- `git clone` the repo on the server; copy `backend/.env` and `frontend/.env.local` with `scp`
  (never commit them). On the server: a strong `POSTGRES_PASSWORD` in the root `.env`, a new
  `COLLECTOR_TOKEN_MEDAS`, `DRY_RUN` left on.
- OpenRouter: a separate key for the demo with a credit limit (for example $10).
- Clerk dashboard: allow the `sslip.io` origin if the instance asks for it; invite the viewers.
- `SITE=tracescan.<ip>.sslip.io docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile app up -d --build`

**Done when** `https://tracescan.<ip>.sslip.io` shows the sign-in page with a valid certificate and
`/v1/traces` is not reachable from outside.

### 5. Seed the traces

From the laptop, through an SSH tunnel to the server's Postgres (bound to the server's localhost):

```bash
ssh -N -L 15433:127.0.0.1:5433 ubuntu@<ip>
```

```bash
cd backend && DATABASE_URL=postgresql://postgres:<password>@127.0.0.1:15433/postgres uv run python -m scripts.seed_traces --end <shortly before the demo>
```

**Done when** the Traces page on the server lists 52 traces.

### 6. Check a run end to end

Sign in, start a run over the seeded day, watch it stream, review it, approve one finding.
**Done when** the run completes and its issue file is in `backend/out/issues/` on the server. This
is PLAN.md's Deploy check: tick it then, and note there that Medas is not part of the deployed demo.

### 7. Keep it alive and tear it down

- Before each demo: seed a new day (step 5) so "the last 24 hours" has traces.
- A Lightsail snapshot once it works (the database lives on the instance).
- When the demo is over, or before the credit ends: delete the instance, the static IP and the
  snapshot; revoke the demo OpenRouter key.

## Risks

| Risk | Mitigation |
| --- | --- |
| Clerk's development instance refuses the `sslip.io` origin | Check in step 4; else a cheap domain and a production instance |
| A viewer starts many runs | The run limit (10 an hour per user), the per-run budget ($2) and the key's credit limit |
| The server is lost | It holds only seeded data; the snapshot and step 5 rebuild it |
| The credit runs out unnoticed | Budget alerts, teardown date in the calendar |
