-- Vitali PostgreSQL Initialization
-- Extensions required for django-tenants + full-text search + crypto

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- UUID generation
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- Trigram full-text search (patients, TUSS)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";    -- Additional crypto functions

-- django-tenants needs the public schema to exist (it always does, but be explicit)
CREATE SCHEMA IF NOT EXISTS public;

-- Set the default search_path on whichever database this script runs in
-- (POSTGRES_DB — e.g. "vitali", or "vitali_test" in CI). Resolving the name via
-- current_database() avoids hardcoding a database that may not exist, which
-- previously logged `ERROR: database "healthos" does not exist` on every boot.
SELECT format('ALTER DATABASE %I SET search_path TO public', current_database())
\gexec
