# Configuration

Configuration is provided through environment variables in `.env`. The production Docker Compose stack reads this file on the VPS. GitHub Actions uses repository secrets for the SSH deployment connection.

## Database (required)

| Variable | Description | Example |
|----------|-------------|---------|
| `DB_HOST` | PostgreSQL host; use `db` inside Docker Compose | `db` |
| `DB_PORT` | PostgreSQL port | `5432` |
| `DB_NAME` | Database name | `postgres` |
| `DB_USER` | Database user | `postgres` |
| `DB_PASSWORD` | Database password | — |

The PostgreSQL image applies the schema in `postgres/migrations/` when it initializes an empty data volume. Existing installations need new migrations applied manually; see [Self-hosting](SELF_HOSTING.md).

## Telegram (required)

| Variable | Description | How to get it |
|----------|-------------|---------------|
| `TELEGRAM_BOT_TOKEN` | Bot API token | Create a bot via [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_GROUP_ID` | Group chat ID (negative number) | See [Getting the Group ID](#getting-the-group-id) below |

### Getting the Group ID

1. Add your bot to the Telegram group
2. Send any message in the group
3. Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
4. Find `"chat":{"id":` — that negative number is your Group ID

## Topic Thread IDs

Each topic in a Telegram supergroup has a thread ID. The thread ID is the number at the end of the topic link (e.g., `t.me/YourGroup/2` -> thread_id is `2`).

| Variable | Topic | Required? |
|----------|-------|-----------|
| `TOPIC_GENERAL` | All Jobs | Recommended |
| `TOPIC_BACKEND` | Backend | Optional |
| `TOPIC_FRONTEND` | Frontend | Optional |
| `TOPIC_MOBILE` | Mobile | Optional |
| `TOPIC_DEVOPS` | DevOps & Cloud | Optional |
| `TOPIC_QA` | QA & Testing | Optional |
| `TOPIC_AI_ML` | AI/ML & Data Science | Optional |
| `TOPIC_CYBERSECURITY` | Cybersecurity | Optional |
| `TOPIC_GAMEDEV` | Game Development | Optional |
| `TOPIC_BLOCKCHAIN` | Blockchain & Web3 | Optional |
| `TOPIC_EGYPT` | Egypt Jobs | Optional |
| `TOPIC_SAUDI` | Saudi Jobs | Optional |
| `TOPIC_INTERNSHIPS` | Internships | Optional |
| `TOPIC_ERP` | ERP & Accounting | Optional |
| `TOPIC_MARKETING_SALES` | Marketing & Sales | Optional |
| `TOPIC_HR_RECRUITING` | HR & Recruiting | Optional |
| `TOPIC_FINANCE_ACCOUNTING` | Finance & Accounting | Optional |
| `TOPIC_ADMIN_OPERATIONS` | Admin & Operations | Optional |
| `TOPIC_CUSTOMER_SUPPORT` | Customer Support | Optional |
| `TOPIC_PRODUCT_PM` | Product & Project Management | Optional |

Topics without a configured thread ID are skipped. You can start with just `TOPIC_GENERAL` and add more later.

### Setting up Telegram Topics

1. Create a **Supergroup** on Telegram
2. Go to group settings and enable **Topics**
3. Create topics for each category you want (Backend, Frontend, etc.)
4. Add the bot as an **Admin** with permission to post in topics
5. Note the thread ID from each topic's link

## API Keys

All API keys are optional. Sources are skipped if their key is absent — the bot works with whatever keys you provide.

| Variable | Source | Where to get it |
|----------|--------|-----------------|
| `RAPIDAPI_KEY` | JSearch (LinkedIn + Indeed + Glassdoor) | [RapidAPI JSearch](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch) |
| `ADZUNA_APP_ID` | Adzuna | [Adzuna Developer](https://developer.adzuna.com/) |
| `ADZUNA_APP_KEY` | Adzuna | [Adzuna Developer](https://developer.adzuna.com/) |
| `FINDWORK_API_KEY` | Findwork.dev | [Findwork.dev](https://findwork.dev/developers/) |
| `JOOBLE_API_KEY` | Jooble | [Jooble API](https://jooble.org/api/about) |
| `REED_API_KEY` | Reed.co.uk | [Reed Developers](https://www.reed.co.uk/developers) |
| `MUSE_API_KEY` | The Muse | [The Muse API](https://www.themuse.com/developers) |

Sources that don't require keys: Remotive, Himalayas, Jobicy, RemoteOK, Arbeitnow, We Work Remotely, Working Nomads, LinkedIn, USAJobs.

## Admin & Operational

| Variable | Description | Default |
|----------|-------------|---------|
| `ADMIN_TELEGRAM_ID` | Your Telegram user ID (for alert DMs) | — |
| `SEED_MODE` | `true` = register jobs without creating live deliveries | `false` |

Seed mode is useful for the first run — it populates the database without flooding the Telegram group with existing jobs.

## Delivery Queue

The delivery queue is stored in PostgreSQL; no Redis/RabbitMQ/SQS is required.

| Variable | Description | Default |
|----------|-------------|---------|
| `FETCH_INTERVAL_MINUTES` | How often the fetch/ingestion pipeline runs | `5` |
| `DELIVERY_INTERVAL_SECONDS` | How often the delivery scheduler wakes up | `60` |
| `DELIVERY_BATCH_SIZE` | Records claimed per delivery batch | `50` |
| `DELIVERY_MAX_ATTEMPTS` | Maximum delivery attempts before dead-letter | `5` |
| `DELIVERY_RETRY_BASE_SECONDS` | Base delay for exponential backoff | `30` |
| `DELIVERY_PROCESSING_LEASE_SECONDS` | How long a `processing` record can sit before recovery | `600` |
| `DELIVERY_IDLE_SLEEP_SECONDS` | How long the delivery scheduler sleeps when no work is found | `10` |
| `DELIVERY_MAX_CYCLE_SECONDS` | Runtime budget for one delivery cycle | `50` |
| `DM_MAX_PER_USER_PER_WINDOW` | Max subscriber DMs per user per window | `20` |
| `DM_RATE_WINDOW_SECONDS` | Sliding window for DM rate limiting | `3600` |

All values read from the environment with the stated fallback if unset.

Backoff sequence (retryable failures): 30s, 60s, 120s, 240s (capped at 24h).

Permanent failures (dead-letter immediately): bot blocked, forbidden, chat/user not found, bot cannot initiate conversation, missing/invalid topic config, invalid recipient.

## Deployment secrets

The backend deployment workflow needs these repository secrets:

1. Go to your repo on GitHub
2. **Settings** > **Secrets and variables** > **Actions**
3. Click **New repository secret** for each variable

The workflow uses `SERVER_HOST`, `SERVER_USER`, `SERVER_SSH_KEY`, and `PROJECT_PATH`. Application secrets remain in the VPS `.env` file.

## Pipeline Constants

These are hardcoded in the source but can be adjusted:

| Constant | Value | Location | Description |
|----------|-------|----------|-------------|
| `REQUEST_TIMEOUT` | 15s | `main.py` | HTTP request timeout |
| `TELEGRAM_SEND_DELAY` | 3s | `bot/sender.py` | Delay between Telegram messages |
| `SCORE_THRESHOLD` | 10 | `core/keywords.py` | Minimum keyword score to pass filter |
| `CIRCUIT_OPEN_FAILURES` | 3 | `core/circuit_breaker.py` | Failures before circuit opens |
| `FUZZY_THRESHOLD` | 0.7 | `core/dedup.py` | pg_trgm similarity threshold |

The old `MAX_JOBS_PER_RUN` cap has been removed; all inserted jobs are now enqueued in the durable delivery queue and delivered independently.
