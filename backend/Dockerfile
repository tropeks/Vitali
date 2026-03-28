FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=vitali.settings.production

WORKDIR /app

# System deps for psycopg2 + cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/base.txt requirements/production.txt ./requirements/
RUN pip install --no-cache-dir -r requirements/production.txt

COPY . .

# collectstatic needs a SECRET_KEY — use a throwaway value at build time only
ARG SECRET_KEY=build-time-placeholder-not-used-in-production
ENV SECRET_KEY=${SECRET_KEY}
RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "vitali.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "120"]
