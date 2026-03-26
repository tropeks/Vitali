-- HealthOS PostgreSQL Initialization
-- Extensions required for django-tenants + full-text search + crypto

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- UUID generation
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- Trigram full-text search (patients, TUSS)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";    -- Additional crypto functions

-- django-tenants needs the public schema to exist (it always does, but be explicit)
CREATE SCHEMA IF NOT EXISTS public;

-- Set search_path default
ALTER DATABASE healthos SET search_path TO public;
