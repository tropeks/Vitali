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

# collectstatic needs SECRET_KEY + ALLOWED_HOSTS - use throwaway values at build time only
ARG SECRET_KEY=build-time-placeholder-not-used-in-production
ARG ALLOWED_HOSTS=localhost
ARG DATABASE_URL=sqlite:///tmp/build.db
ARG REDIS_URL=redis://localhost:6379/0
ENV SECRET_KEY=${SECRET_KEY}
ENV ALLOWED_HOSTS=${ALLOWED_HOSTS}
ENV DATABASE_URL=${DATABASE_URL}
ENV REDIS_URL=${REDIS_URL}
RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "vitali.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "120"]
