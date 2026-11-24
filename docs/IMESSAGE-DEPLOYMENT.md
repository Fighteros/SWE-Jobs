# Deploying the iMessage variant alongside the existing stack

This runs the personalized iMessage version (Photon Spectrum) on the same
server as the existing Telegram deployment, in fully separate containers,
network, and database volume. The existing stack is untouched.

The iMessage mode has no group, channel, or topic delivery: users text the
Photon number, save alerts, and receive only matching jobs.

## 1. Fresh checkout in a new directory

After PR #21 is merged into the `imessage` branch:

```bash
git clone -b imessage https://github.com/Fighteros/SWE-Jobs.git swe-jobs-imessage
cd swe-jobs-imessage
```

(Before merging, check out the PR branch instead:
`git clone -b feature/photon-imessage-delivery https://github.com/Fighteros/SWE-Jobs.git swe-jobs-imessage`)

## 2. Configure .env

```bash
cp -n .env.imessage.example .env
```

The dedicated template sets the iMessage Compose project, profile, isolated
port `8001`, delivery channel, and sidecar URL. Edit `.env` to set `DB_PASSWORD`,
`SPECTRUM_PROJECT_ID`, `SPECTRUM_PROJECT_SECRET`, and `IMESSAGE_WEBHOOK_SECRET`
(generate the latter with `openssl rand -hex 32`). Optionally set
`IMESSAGE_RECIPIENTS` for admin alerts. If `.env` already exists, `cp -n` keeps
it unchanged: merge the missing settings into it without replacing its current
secrets or changing the password of a database that's already initialized.

No Telegram settings are needed in this mode. TELEGRAM_BOT_TOKEN /
TELEGRAM_GROUP_ID can stay unset: no Telegram polling, no group broadcast.

## 3. Build and start

The compose project name keeps every container, network, and volume
(including its own Postgres `pgdata`) separate from the existing stack:

```bash
docker compose -p swejobs-imessage --profile imessage up -d --build
```

This starts: `db` (its own Postgres), `backend` (API + job fetcher + iMessage
delivery scheduler), `imessage-sidecar` (the spectrum-ts connection), and
`autoheal`.

## 4. Verify

```bash
docker compose -p swejobs-imessage ps
docker compose -p swejobs-imessage logs -f imessage-sidecar
curl http://localhost:8001/health    # -> {"status":"ok","channel":"imessage"}
```

## 5. First contact

On Photon's free shared line, your number must text the line once before the
bot can message it. From your iPhone: text anything to the Photon number,
then send `/help`. Create your first alert, for example:

```
/alert add seniority=mid,senior locations=remote,EG keywords=python min_salary=60000
```

Matching new jobs then arrive as iMessages.

## Automatic deploys

Set the repository secret `IMESSAGE_PROJECT_PATH` to the absolute path of
this separate checkout on the server. Reuse `SERVER_HOST`, `SERVER_USER`, and
`SERVER_SSH_KEY` from the main deployment. Use a recent Docker Compose v2
with `up --wait` support. The checkout must already be on `imessage` and its
`.env` must include the Photon credentials and webhook secret above.

Pushes to `imessage` (including PR merges) trigger **Deploy iMessage**. It
fast-forwards the checkout, applies migration 010 to the iMessage database,
rebuilds the isolated stack and waits for the backend and sidecar health
checks. It never uses the main checkout or main Compose project.

To update manually after pulling `imessage`:

```bash
bash scripts/deploy_imessage.sh "$PWD"
```

## Notes

- The two stacks are independent: each fetches and stores its own copy of
  jobs in its own database. Nothing is shared.
- Autoheal isolation: the backend's autoheal label is `autoheal-$STACK`, and
  each stack's autoheal only watches that label. With `STACK=swejobs-imessage`
  here (and the default `swejobs` elsewhere), neither stack's autoheal can
  see or restart the other's containers. The existing stack picks its new
  `autoheal-swejobs` label up on its next `up -d`; until then it keeps
  working under its old label.
- Ports: existing stack keeps 8000; this stack uses 8001 (only needed if you
  want the API reachable from outside the compose network).
- Live iMessage delivery requires the Spectrum credentials above; without
  them the sidecar exits on startup and the backend delivers nothing.

### Inbound recovery and pending notifications

The sidecar persists accepted commands in the `imessage_inbound` Compose volume
before forwarding. Unacknowledged commands are retried after outages and restarts;
HTTP 400 entries are retained with a `.rejected` suffix for operator inspection.
Protect this volume as it contains message data, and do not delete it during upgrades.
A reply can be duplicated if Photon accepted it but the backend could not record
that success; command mutations are deduplicated separately.

Queued jobs are checked against current alert and blacklist settings before sending.
An alert change does not recall an iMessage already in flight.
