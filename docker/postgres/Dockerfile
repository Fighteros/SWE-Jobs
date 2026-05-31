# =============================================================================
# Postgres image for SWE-Jobs — self-hosted replacement for Supabase.
#
# Bakes the Supabase-compatible roles and the existing schema migrations into
# /docker-entrypoint-initdb.d/, which the official postgres image runs (in
# lexical order) the first time an empty data volume is initialised:
#
#   000_roles.sql   -> creates anon/authenticated/service_role
#   001_init.sql .. 006_job_apply_fields.sql -> the existing schema
#
# NOTE: initdb scripts run ONLY on first boot (empty pgdata volume). Apply any
# later migrations manually, e.g.:
#   docker compose exec -T db psql -U postgres -d postgres -f - < supabase/migrations/006_*.sql
# =============================================================================
# Postgres 17 to match the pg_dump version used for the Supabase data export
# (a dump can only be restored into a server >= the pg_dump major version).
FROM postgres:17-alpine

# Roles first (000_ prefix sorts before 001_), then the schema migrations.
COPY docker/postgres/000_roles.sql /docker-entrypoint-initdb.d/000_roles.sql
COPY supabase/migrations/ /docker-entrypoint-initdb.d/
