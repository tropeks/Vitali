from django.contrib import admin

from .models import DigitalSignature


@admin.register(DigitalSignature)
class DigitalSignatureAdmin(admin.ModelAdmin):
    list_display = (
        "document_type",
        "document_id",
        "signer",
        "is_icp_brasil",
        "cert_serial_hex",
        "signed_at",
    )
    list_filter = ("document_type", "is_icp_brasil")
    search_fields = ("document_id", "cert_subject", "cert_serial_hex")
    readonly_fields = (
        "id",
        "document_type",
        "document_id",
        "signer",
        "signature",
        "signature_algorithm",
        "document_hash_hex",
        "cert_subject",
        "cert_issuer",
        "cert_serial_hex",
        "cert_not_valid_before",
        "cert_not_valid_after",
        "is_icp_brasil",
        "signed_at",
    )
    ordering = ("-signed_at",)

    def has_add_permission(self, request) -> bool:
        # Signatures are produced by the API, not via admin.
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        # Signatures are append-only — supersede with a new row instead of deleting.
        return False
