FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=vitali.settings.production

WORKDIR /app

# System deps for psycopg2 + cryptography + WeasyPrint (Cairo/Pango/fonts)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    python3-dev \
    build-essential \
    libcairo2-dev \
    libpango1.0-dev \
    libffi-dev \
    libjpeg-dev \
    libpng-dev \
    libfreetype6-dev \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Non-root runtime user (frontend image already runs as non-root). Ownership is
# transferred after collectstatic, just before we switch to it.
RUN groupadd --system --gid 1001 appgroup && \
    useradd --system --uid 1001 --gid appgroup --no-create-home appuser

COPY requirements/base.txt requirements/production.txt requirements/development.txt ./requirements/

# When INSTALL_DEV=true (set by docker-compose.override.yml), bake pytest/ruff/mypy
# into the image so `make test|lint|typecheck` work without re-installing every time
# the container is recreated. Production builds keep INSTALL_DEV=false (default) and
# stay slim.
ARG INSTALL_DEV=false
RUN pip install --no-cache-dir -r requirements/production.txt && \
    if [ "$INSTALL_DEV" = "true" ]; then \
        pip install --no-cache-dir -r requirements/development.txt; \
    fi

COPY . .

# collectstatic needs ALLOWED_HOSTS/DATABASE_URL/REDIS_URL at build time.
# SECRET_KEY is intentionally NOT baked as ENV — it's passed inline below, so a
# runtime container that forgets to set SECRET_KEY fails fast (production reads it
# with no default) instead of silently using a baked placeholder.
ARG ALLOWED_HOSTS=localhost
ARG DATABASE_URL=sqlite:///tmp/build.db
ARG REDIS_URL=redis://localhost:6379/0
ENV ALLOWED_HOSTS=${ALLOWED_HOSTS}
ENV DATABASE_URL=${DATABASE_URL}
ENV REDIS_URL=${REDIS_URL}
# collectstatic loads production settings, which require non-placeholder secrets.
# Pass throwaway values INLINE for this build step only — none persist as ENV, so
# production must still supply real secrets at runtime. The throwaway SECRET_KEY
# avoids the dev/placeholder/"django-insecure-" patterns the validators reject.
RUN SECRET_KEY="ci-build-throwaway-secret-not-for-prod-0123456789abcdef" \
    FIELD_ENCRYPTION_KEY="OrnFQUsB_Cffudfe79JCnCs8NkrE7t9sMr-x2oliags=" \
    POSTGRES_PASSWORD="ci-build-throwaway-pw" \
    REDIS_PASSWORD="ci-build-throwaway-pw" \
    WHATSAPP_EVOLUTION_API_KEY="build-time-throwaway" \
    python manage.py collectstatic --noinput

# Drop root: create media dir, hand /app to the non-root user, then switch.
RUN mkdir -p media && chown -R appuser:appgroup /app
USER appuser

EXPOSE 8000

CMD ["gunicorn", "vitali.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "120"]
