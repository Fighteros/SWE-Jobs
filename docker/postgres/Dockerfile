# =============================================================================
# PostgreSQL image for SWE-Jobs.
#
# Bakes the compatibility roles and schema migrations into
# /docker-entrypoint-initdb.d/, which the official postgres image runs (in
# lexical order) the first time an empty data volume is initialised:
#
#   000_roles.sql   -> creates anon/authenticated/service_role
#   001_init.sql .. -> the database schema
#
# NOTE: initdb scripts run ONLY on first boot (empty pgdata volume). Apply any
# later migrations manually, e.g.:
#   docker compose exec -T db psql -U postgres -d postgres -f - < postgres/migrations/007_job_deliveries.sql
# =============================================================================
FROM postgres:17-alpine

# Roles first (000_ prefix sorts before 001_), then the schema migrations.
COPY docker/postgres/000_roles.sql /docker-entrypoint-initdb.d/000_roles.sql
COPY postgres/migrations/ /docker-entrypoint-initdb.d/
