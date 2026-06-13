"""
Vitali WSGI config.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vitali.settings.production")
application = get_wsgi_application()

from vitali.observability import setup_observability  # noqa: E402

setup_observability("web")
