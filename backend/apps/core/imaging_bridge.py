"""Framework-level model lookup shared with imaging consumers.

Keeping this lookup in ``apps.core`` avoids a static dependency between the
patient portal and imaging domains while preserving Django's concrete model
class for querysets and serializers.
"""

from django.apps import apps

DicomStudy = apps.get_model("imaging", "DicomStudy")

__all__ = ["DicomStudy"]
