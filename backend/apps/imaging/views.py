"""
REST views for the imaging (DICOM Study tracking) module.

Endpoints:
- `GET    /api/v1/imaging/studies/?patient=…&modality=…&_count=…` — list
- `POST   /api/v1/imaging/studies/`                              — register
- `GET    /api/v1/imaging/studies/{id}/`                         — read
- `PATCH  /api/v1/imaging/studies/{id}/orthanc/`                 — backfill
                                                                   orthanc UID

All endpoints are gated by the `imaging` module FeatureFlag (default OFF)
plus `imaging.read` / `imaging.write` permissions.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasPermission, ModuleRequiredPermission

from .models import DicomStudy
from .serializers import (
    DicomStudyCreateSerializer,
    DicomStudyOrthancPatchSerializer,
    DicomStudySerializer,
)

_IMAGING_MODULE = ModuleRequiredPermission("imaging")


class StudyListCreateView(APIView):
    """GET / POST `/api/v1/imaging/studies/`."""

    DEFAULT_COUNT = 50
    MAX_COUNT = 200

    def get_permissions(self):
        if self.request.method == "POST":
            return [
                IsAuthenticated(),
                _IMAGING_MODULE,
                HasPermission("imaging.write"),
            ]
        return [IsAuthenticated(), _IMAGING_MODULE, HasPermission("imaging.read")]

    def get(self, request):
        qs = DicomStudy.objects.select_related("patient").all()
        patient = request.query_params.get("patient")
        modality = request.query_params.get("modality")
        encounter = request.query_params.get("encounter")
        if patient:
            qs = qs.filter(patient_id=patient)
        if modality:
            qs = qs.filter(modality=modality.upper())
        if encounter:
            qs = qs.filter(encounter_id=encounter)
        try:
            count = min(int(request.query_params.get("_count", self.DEFAULT_COUNT)), self.MAX_COUNT)
        except (TypeError, ValueError):
            count = self.DEFAULT_COUNT
        if count < 1:
            count = self.DEFAULT_COUNT
        return Response(DicomStudySerializer(qs[:count], many=True).data)

    def post(self, request):
        serializer = DicomStudyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        study = serializer.save(created_by=request.user)
        return Response(DicomStudySerializer(study).data, status=status.HTTP_201_CREATED)


class StudyDetailView(APIView):
    """GET `/api/v1/imaging/studies/{id}/`."""

    def get_permissions(self):
        return [IsAuthenticated(), _IMAGING_MODULE, HasPermission("imaging.read")]

    def get(self, request, study_id):
        try:
            study = DicomStudy.objects.select_related("patient").get(pk=study_id)
        except (DicomStudy.DoesNotExist, ValueError):
            return Response({"detail": "Study not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(DicomStudySerializer(study).data)


class StudyOrthancBackfillView(APIView):
    """PATCH `/api/v1/imaging/studies/{id}/orthanc/` — set the Orthanc UID."""

    def get_permissions(self):
        return [IsAuthenticated(), _IMAGING_MODULE, HasPermission("imaging.write")]

    def patch(self, request, study_id):
        try:
            study = DicomStudy.objects.get(pk=study_id)
        except (DicomStudy.DoesNotExist, ValueError):
            return Response({"detail": "Study not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = DicomStudyOrthancPatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        study.orthanc_study_id = data["orthanc_study_id"]
        if "number_of_series" in data:
            study.number_of_series = data["number_of_series"]
        if "number_of_instances" in data:
            study.number_of_instances = data["number_of_instances"]
        study.save(
            update_fields=[
                "orthanc_study_id",
                "number_of_series",
                "number_of_instances",
            ]
        )
        return Response(DicomStudySerializer(study).data)
