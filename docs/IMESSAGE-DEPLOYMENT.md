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
cp .env.example .env
```

Set in `.env`:

```bash
DB_PASSWORD=<new random password for this stack's database>
APP_PORT=8001                      # existing stack already publishes 8000
DELIVERY_CHANNEL=imessage
SPECTRUM_PROJECT_ID=<from https://app.photon.codes project settings>
SPECTRUM_PROJECT_SECRET=<from https://app.photon.codes project settings>
IMESSAGE_SIDECAR_URL=http://imessage-sidecar:8789
IMESSAGE_RECIPIENTS=<your iMessage number, e.g. +201099599616>   # admin alerts only
```

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
/alert add topics=backend,ai_ml seniority=mid,senior locations=remote,EG
```

Matching new jobs then arrive as iMessages.

## Updating later

```bash
cd swe-jobs-imessage
git pull
docker compose -p swejobs-imessage --profile imessage up -d --build
```

## Notes

- The two stacks are independent: each fetches and stores its own copy of
  jobs in its own database. Nothing is shared.
- Ports: existing stack keeps 8000; this stack uses 8001 (only needed if you
  want the API reachable from outside the compose network).
- Live iMessage delivery requires the Spectrum credentials above; without
  them the sidecar exits on startup and the backend delivers nothing.
