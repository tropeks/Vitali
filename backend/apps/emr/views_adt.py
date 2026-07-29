"""
L1 — DRF viewsets for the ADT/Leitos bed structure (apps.emr.adt_models).

Permission split: reads require ``beds.read``, all writes require ``beds.manage``
(NIR/Gestão de Leitos gere a estrutura), gated per-action via ``get_permissions``
exactly like ``NursingDiagnosisViewSet``. Each viewset is filterable by its parent
FK. On ``Bed`` create/update the denormalized ``unit`` FK is derived from the room
(never client-set) so per-unit census queries stay consistent.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework import status as http_status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import HasPermission

from .serializers_adt import (
    AdmissionDischargeSerializer,
    AdmissionEventSerializer,
    AdmissionPlanDischargeSerializer,
    AdmissionSerializer,
    AdmissionTransferSerializer,
    BedSerializer,
    InpatientUnitSerializer,
    RoomSerializer,
)
from .services import adt as adt_service
from .services import census as census_service
from .views import log_audit

_FACILITY_PARAM = OpenApiParameter(
    "facility", str, description="Filtra por estabelecimento (UUID)."
)
_UNIT_PARAM = OpenApiParameter("unit", str, description="Filtra por unidade de internação (UUID).")
_ROOM_PARAM = OpenApiParameter("room", str, description="Filtra por quarto (UUID).")
_STATUS_PARAM = OpenApiParameter("status", str, description="Filtra leitos por situação.")
_PATIENT_PARAM = OpenApiParameter("patient", str, description="Filtra por paciente (UUID).")
_BED_PARAM = OpenApiParameter("bed", str, description="Filtra por leito atual (UUID).")
_ADM_STATUS_PARAM = OpenApiParameter(
    "status", str, description="Filtra internações por situação (admitted/discharged/cancelled)."
)
_ADMISSION_PARAM = OpenApiParameter(
    "admission", str, description="Filtra eventos por internação (UUID)."
)
_UNTIL_PARAM = OpenApiParameter(
    "until", str, description="Teto da alta prevista (ISO datetime); traz altas até esse instante."
)


class _BedsPermissionMixin:
    """Read=``beds.read`` / write=``beds.manage`` per-action gate."""

    def get_permissions(self):
        # ``board`` is a read-only bed-map view → beds.read, like list/retrieve.
        read_actions = {"list", "retrieve", "board"}
        permission = "beds.read" if self.action in read_actions else "beds.manage"
        return [IsAuthenticated(), HasPermission(permission)]


@extend_schema_view(
    list=extend_schema(parameters=[_FACILITY_PARAM]),
)
class InpatientUnitViewSet(_BedsPermissionMixin, viewsets.ModelViewSet):
    """Inpatient units (ala/unidade de internação). Managed by beds.manage."""

    serializer_class = InpatientUnitSerializer

    def get_queryset(self):
        from .models import InpatientUnit

        qs = InpatientUnit.objects.select_related("facility", "default_bed_type")
        facility = self.request.query_params.get("facility")
        if facility:
            qs = qs.filter(facility_id=facility)
        return qs

    def perform_create(self, serializer):
        obj = serializer.save()
        log_audit(self.request, "beds_unit_create", "InpatientUnit", obj.id)


@extend_schema_view(
    list=extend_schema(parameters=[_UNIT_PARAM]),
)
class RoomViewSet(_BedsPermissionMixin, viewsets.ModelViewSet):
    """Rooms (quarto) inside an inpatient unit."""

    serializer_class = RoomSerializer

    def get_queryset(self):
        from .models import Room

        qs = Room.objects.select_related("unit")
        unit = self.request.query_params.get("unit")
        if unit:
            qs = qs.filter(unit_id=unit)
        return qs

    def perform_create(self, serializer):
        obj = serializer.save()
        log_audit(self.request, "beds_room_create", "Room", obj.id)


@extend_schema_view(
    list=extend_schema(parameters=[_UNIT_PARAM, _ROOM_PARAM, _STATUS_PARAM]),
)
class BedViewSet(_BedsPermissionMixin, viewsets.ModelViewSet):
    """Physical beds (leito). ``unit`` is derived from the room server-side."""

    serializer_class = BedSerializer

    def get_queryset(self):
        from .models import Bed

        qs = Bed.objects.select_related("room", "unit", "bed_type")
        unit = self.request.query_params.get("unit")
        room = self.request.query_params.get("room")
        status = self.request.query_params.get("status")
        if unit:
            qs = qs.filter(unit_id=unit)
        if room:
            qs = qs.filter(room_id=room)
        if status:
            qs = qs.filter(status=status)
        return qs

    def perform_create(self, serializer):
        room = serializer.validated_data["room"]
        obj = serializer.save(unit=room.unit)
        log_audit(self.request, "beds_bed_create", "Bed", obj.id)

    def perform_update(self, serializer):
        # Keep the denormalized ``unit`` FK consistent if the room changes.
        room = serializer.validated_data.get("room")
        if room is not None:
            obj = serializer.save(unit=room.unit)
        else:
            obj = serializer.save()
        log_audit(self.request, "beds_bed_update", "Bed", obj.id)

    @extend_schema(
        parameters=[_FACILITY_PARAM, _UNIT_PARAM],
        responses=OpenApiTypes.OBJECT,
        description="Mapa de leitos: unidade → quarto → leito (com situação e "
        "paciente ocupante). Gated beds.read.",
    )
    @action(detail=False, methods=["get"])
    def board(self, request):
        """Bed-board tree: units → rooms → beds, each bed carrying its status and
        the occupying patient (id/name) when there is an active admission."""
        from .models import Admission, InpatientUnit

        units_qs = InpatientUnit.objects.all()
        facility = request.query_params.get("facility")
        unit = request.query_params.get("unit")
        if facility:
            units_qs = units_qs.filter(facility_id=facility)
        if unit:
            units_qs = units_qs.filter(id=unit)
        units_qs = units_qs.prefetch_related("rooms", "rooms__beds").order_by("code")

        # bed_id → {id, name} for the single active admission occupying it.
        occupant_by_bed: dict = {}
        active = Admission.objects.filter(
            status=Admission.Status.ADMITTED, current_bed__isnull=False
        ).select_related("patient")
        if unit:
            active = active.filter(current_bed__unit_id=unit)
        if facility:
            active = active.filter(current_bed__unit__facility_id=facility)
        for adm in active:
            occupant_by_bed[adm.current_bed_id] = {
                "id": str(adm.patient_id),
                "name": adm.patient.full_name,
            }

        units_out = []
        for u in units_qs:
            rooms_out = []
            for room in u.rooms.all():
                beds_out = [
                    {
                        "id": str(bed.id),
                        "identifier": bed.identifier,
                        "status": bed.status,
                        "patient": occupant_by_bed.get(bed.id),
                    }
                    for bed in room.beds.all()
                ]
                rooms_out.append({"id": str(room.id), "name": room.name, "beds": beds_out})
            units_out.append(
                {
                    "id": str(u.id),
                    "code": u.code,
                    "name": u.name,
                    "rooms": rooms_out,
                }
            )
        return Response({"units": units_out})


# ─── L2: admissão/internação ─────────────────────────────────────────────────


@extend_schema_view(
    list=extend_schema(parameters=[_PATIENT_PARAM, _ADM_STATUS_PARAM, _BED_PARAM]),
)
class AdmissionViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Admissões/internações. Create (admit) e a ação ``discharge`` passam SEMPRE
    pelo serviço ``apps.emr.services.adt`` para manter leito + eventos consistentes.

    Gate: create/list/retrieve → ``adt.admit``; ``discharge`` → ``adt.discharge``;
    ``transfer`` → ``adt.transfer``; ``census`` → ``beds.read`` (leitura ADT).
    """

    serializer_class = AdmissionSerializer

    def get_permissions(self):
        permission_by_action = {
            "discharge": "adt.discharge",
            "plan_discharge": "adt.discharge",
            "transfer": "adt.transfer",
            "census": "beds.read",
            "planned": "beds.read",
        }
        permission = permission_by_action.get(self.action, "adt.admit")
        return [IsAuthenticated(), HasPermission(permission)]

    def get_queryset(self):
        from .models import Admission

        qs = Admission.objects.select_related(
            "patient", "admitting_professional", "attending_professional", "current_bed"
        )
        patient = self.request.query_params.get("patient")
        state = self.request.query_params.get("status")
        bed = self.request.query_params.get("bed")
        if patient:
            qs = qs.filter(patient_id=patient)
        if state:
            qs = qs.filter(status=state)
        if bed:
            qs = qs.filter(current_bed_id=bed)
        return qs

    def create(self, request, *args, **kwargs):
        # Admit THROUGH the service (bed transition + append-only event), not
        # raw serializer.save.
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            admission = adt_service.admit(
                patient=data["patient"],
                bed=data["bed"],
                admitting_professional=data["admitting_professional"],
                attending_professional=data["attending_professional"],
                admission_source=data.get("admission_source", "outro"),
                admission_datetime=data.get("admission_datetime"),
                expected_discharge_datetime=data.get("expected_discharge_datetime"),
                encounter=data.get("encounter"),
                actor=request.user,
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=http_status.HTTP_409_CONFLICT)
        log_audit(request, "adt_admit", "Admission", admission.id)
        out = self.get_serializer(admission)
        return Response(out.data, status=http_status.HTTP_201_CREATED)

    @extend_schema(request=AdmissionDischargeSerializer, responses=AdmissionSerializer)
    @action(detail=True, methods=["post"])
    def discharge(self, request, pk=None):
        admission = self.get_object()
        payload = AdmissionDischargeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            admission = adt_service.discharge(
                admission=admission,
                disposition=payload.validated_data["disposition"],
                actual_discharge_datetime=payload.validated_data.get("actual_discharge_datetime"),
                actor=request.user,
                reason=payload.validated_data.get("reason", ""),
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=http_status.HTTP_409_CONFLICT)
        log_audit(request, "adt_discharge", "Admission", admission.id)
        return Response(self.get_serializer(admission).data)

    @extend_schema(request=AdmissionTransferSerializer, responses=AdmissionSerializer)
    @action(detail=True, methods=["post"])
    def transfer(self, request, pk=None):
        """Transfer the admission to another bed THROUGH the service (bed
        transitions + append-only transfer event). Rejection → 409."""
        admission = self.get_object()
        payload = AdmissionTransferSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            admission = adt_service.transfer(
                admission,
                payload.validated_data["to_bed"],
                actor=request.user,
                reason=payload.validated_data.get("reason", ""),
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=http_status.HTTP_409_CONFLICT)
        log_audit(request, "adt_transfer", "Admission", admission.id)
        return Response(self.get_serializer(admission).data)

    @extend_schema(request=AdmissionPlanDischargeSerializer, responses=AdmissionSerializer)
    @action(detail=True, methods=["post"], url_path="plan-discharge")
    def plan_discharge(self, request, pk=None):
        """Set/update the planned discharge datetime (alta prevista) THROUGH the
        service (append-only ``plan_discharge`` event). Rejection → 409."""
        admission = self.get_object()
        payload = AdmissionPlanDischargeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            admission = adt_service.plan_discharge(
                admission=admission,
                expected_discharge_datetime=payload.validated_data["expected_discharge_datetime"],
                actor=request.user,
                reason=payload.validated_data.get("reason", ""),
            )
        except DjangoValidationError as exc:
            return Response({"detail": exc.messages[0]}, status=http_status.HTTP_409_CONFLICT)
        log_audit(request, "adt_plan_discharge", "Admission", admission.id)
        return Response(self.get_serializer(admission).data)

    @extend_schema(
        parameters=[_UNIT_PARAM, _UNTIL_PARAM],
        responses=OpenApiTypes.OBJECT,
        description="Altas previstas (internações ativas com alta prevista), da "
        "mais próxima à mais distante. ``?until=`` teto do horário; ``?unit=`` "
        "escopa por unidade. Antecipa a rotatividade de leitos. Gated beds.read.",
    )
    @action(detail=False, methods=["get"])
    def planned(self, request):
        """Planned-discharge board: active admissions with an expected discharge,
        soonest first. Each row carries patient + current bed for the board."""
        from django.utils.dateparse import parse_datetime

        until_raw = request.query_params.get("until")
        until = parse_datetime(until_raw) if until_raw else None
        unit = request.query_params.get("unit")
        rows = [
            {
                "admission_id": str(adm.id),
                "patient": {"id": str(adm.patient_id), "name": adm.patient.full_name},
                "current_bed": (
                    {"id": str(adm.current_bed_id), "identifier": adm.current_bed.identifier}
                    if adm.current_bed_id
                    else None
                ),
                "unit_id": str(adm.current_bed.unit_id) if adm.current_bed_id else None,
                "expected_discharge_datetime": adm.expected_discharge_datetime.isoformat(),
            }
            for adm in adt_service.planned_discharges(until=until, unit=unit)
        ]
        return Response({"planned": rows})

    @extend_schema(
        parameters=[_UNIT_PARAM],
        responses=OpenApiTypes.OBJECT,
        description="Censo/ocupação: ocupação por unidade (contagens + taxa) e a "
        "lista de internações ativas com tempo de permanência (LOS). Gated beds.read.",
    )
    @action(detail=False, methods=["get"])
    def census(self, request):
        """Occupancy per unit (counts + rate) plus the active-census list with LOS.
        ``?unit=`` scopes both to a single unit."""
        from .models import InpatientUnit

        unit_id = request.query_params.get("unit")
        unit_obj = None
        if unit_id:
            unit_obj = InpatientUnit.objects.filter(id=unit_id).first()
            occupancy = [census_service.unit_occupancy(unit_obj)] if unit_obj else []
        else:
            occupancy = census_service.all_unit_occupancy()
        census_rows = census_service.census(unit=unit_obj)
        return Response({"occupancy": occupancy, "census": census_rows})


@extend_schema_view(
    list=extend_schema(parameters=[_ADMISSION_PARAM]),
)
class AdmissionEventViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only append-only ADT event log. Gated ``beds.read`` (leitura ADT)."""

    serializer_class = AdmissionEventSerializer

    def get_permissions(self):
        return [IsAuthenticated(), HasPermission("beds.read")]

    def get_queryset(self):
        from .models import AdmissionEvent

        qs = AdmissionEvent.objects.select_related("admission", "from_bed", "to_bed", "actor")
        admission = self.request.query_params.get("admission")
        if admission:
            qs = qs.filter(admission_id=admission)
        return qs
