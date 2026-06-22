import logging

from apps.signatures.models import DigitalSignature
from apps.signatures.services.icp_brasil import ICPBrasilSigner, ICPBrasilSignerError

logger = logging.getLogger(__name__)

def sign_with_icp_brasil(
    user,
    document_type: str,
    document_id: str,
    document_content: bytes,
    pkcs12_b64: str | None,
    pkcs12_password: str | None
) -> tuple[bool, str]:
    """
    Tries to sign the document with ICP-Brasil.
    Returns (is_icp_brasil, signature_hash).
    If pkcs12_b64 is not provided, or chain validation fails, fail-open (returns False, "").
    """
    if not pkcs12_b64:
        logger.warning(f"No certificate provided for signing {document_type} {document_id}. Failing open.")
        return False, ""

    try:
        import base64
        pfx_bytes = base64.b64decode(pkcs12_b64, validate=True)
    except Exception as e:
        logger.warning(f"Invalid base64 certificate provided for {document_type} {document_id}: {e}. Failing open.")
        return False, ""

    try:
        result = ICPBrasilSigner.sign(
            document=document_content,
            pfx_bytes=pfx_bytes,
            password=pkcs12_password or None,
        )
    except ICPBrasilSignerError as exc:
        logger.warning(f"ICP-Brasil signature failed for {document_type} {document_id}: {exc}. Failing open.")
        return False, ""

    # Persist the DigitalSignature row
    DigitalSignature.objects.create(
        document_type=document_type,
        document_id=document_id,
        signer=user,
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

    return result.is_icp_brasil, result.document_hash_hex
