"""
REST views for the ICP-Brasil signature module.

POST /api/v1/signatures/sign/   — sign a document; create a DigitalSignature row.
GET  /api/v1/signatures/        — list signatures, filterable by document.

Module is gated behind FeatureFlag `signatures` (per-tenant) and the per-user
permissions `signatures.sign` (write) + `signatures.read` (list/detail). The
signing endpoint accepts the PKCS#12 bundle in the request body only — never
multipart, never query string — so the key payload doesn't leak into request
logs.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasPermission, ModuleRequiredPermission

from .models import DigitalSignature
from .serializers import DigitalSignatureSerializer, SignatureCreateSerializer
from .services.icp_brasil import ICPBrasilSigner, ICPBrasilSignerError

logger = logging.getLogger(__name__)

_SIGNATURES_MODULE = ModuleRequiredPermission("signatures")


class SignatureCreateView(APIView):
    """POST /api/v1/signatures/sign/ — sign a document with an ICP-Brasil A1 cert."""

    def get_permissions(self):
        return [IsAuthenticated(), _SIGNATURES_MODULE, HasPermission("signatures.sign")]

    def post(self, request):
        serializer = SignatureCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            result = ICPBrasilSigner.sign(
                document=data["document_b64"],
                pfx_bytes=data["pkcs12_b64"],
                password=data.get("pkcs12_password") or None,
            )
        except ICPBrasilSignerError as exc:
            # Includes ICP-Brasil chain-of-trust rejection when the trust store
            # is populated and ICP_BRASIL_ENFORCE_CHAIN is on (default).
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        record = DigitalSignature.objects.create(
            document_type=data["document_type"],
            document_id=data["document_id"],
            signer=request.user,
            signature=result.signature,
            signature_algorithm=result.algorithm,
            document_hash_hex=result.document_hash_hex,
            cert_subject=result.cert_subject,
            cert_issuer=result.cert_issuer,
            cert_serial_hex=result.cert_serial_hex,
            cert_not_valid_before=result.cert_not_valid_before,
            cert_not_valid_after=result.cert_not_valid_after,
            is_icp_brasil=result.is_icp_brasil,
        )

        logger.info(
            "Digital signature recorded: doc_type=%s doc_id=%s signer=%s icp_brasil=%s",
            record.document_type,
            record.document_id,
            request.user.pk,
            record.is_icp_brasil,
        )

        return Response(DigitalSignatureSerializer(record).data, status=status.HTTP_201_CREATED)


class SignatureListView(APIView):
    """
    GET /api/v1/signatures/?document_type=…&document_id=…

    Lists signatures, scoped to the current tenant. Filterable by the document
    being signed; when both filters are present, returns the audit trail for
    that exact document.
    """

    def get_permissions(self):
        return [IsAuthenticated(), _SIGNATURES_MODULE, HasPermission("signatures.read")]

    def get(self, request):
        qs = DigitalSignature.objects.select_related("signer").all()
        document_type = request.query_params.get("document_type")
        document_id = request.query_params.get("document_id")
        if document_type:
            qs = qs.filter(document_type=document_type)
        if document_id:
            qs = qs.filter(document_id=document_id)
        return Response(DigitalSignatureSerializer(qs[:200], many=True).data)
