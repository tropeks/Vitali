"""
MFA service for S-062 — TOTP-based multi-factor authentication.

Uses pyotp for TOTP generation/verification (NOT django-otp).
TOTPDevice lives in the public schema alongside User.
Backup codes are SHA-256 hashed before storage (LGPD).
"""

import base64
import hashlib
import io
import json
import logging
import secrets
from datetime import datetime

import pyotp
import qrcode
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

BACKUP_CODE_COUNT = 8
TOTP_VALID_WINDOW = 1  # T-1, T, T+1
MFA_GRACE_PERIOD_SECONDS = getattr(settings, "MFA_GRACE_PERIOD_SECONDS", 3600)


# ─── Secret Generation ────────────────────────────────────────────────────────


def generate_totp_secret() -> str:
    """Generate a new cryptographically secure base32 TOTP secret."""
    return pyotp.random_base32()


def generate_qr_uri(user_email: str, secret: str, issuer: str = "Vitali") -> str:
    """Return an otpauth:// URI suitable for QR code scanning."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=user_email, issuer_name=issuer)


def generate_qr_image_base64(uri: str) -> str:
    """
    Generate a QR code image from an otpauth:// URI.
    Returns a base64-encoded PNG data URL: 'data:image/png;base64,...'
    """
    img = qrcode.make(uri)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    b64 = base64.b64encode(buffer.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"


# ─── TOTP Verification ────────────────────────────────────────────────────────


def verify_totp_code(secret: str, code: str, valid_window: int = TOTP_VALID_WINDOW) -> bool:
    """
    Verify a 6-digit TOTP code against the given secret.
    valid_window=1 accepts T-1, T, and T+1 (±30s drift).
    Returns False on any exception (fail-safe).
    """
    try:
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=valid_window)
    except Exception:
        logger.warning("TOTP verification error", exc_info=True)
        return False


# ─── Backup Codes ─────────────────────────────────────────────────────────────


def generate_backup_codes(count: int = BACKUP_CODE_COUNT) -> list:
    """
    Generate a list of one-time backup codes in format "XXXX-XXXX".
    Returns plain codes (shown once; caller must hash before storing).
    """
    codes = []
    for _ in range(count):
        part1 = secrets.token_hex(2).upper()
        part2 = secrets.token_hex(2).upper()
        codes.append(f"{part1}-{part2}")
    return codes


def hash_backup_code(code: str) -> str:
    """SHA-256 hex digest of a backup code (for secure storage)."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def check_backup_code(device, plain_code: str) -> bool:
    """
    Check if plain_code matches any stored hashed backup code.
    If match found: remove the code from the list (single-use), save device.
    Returns True if code was valid and consumed, False otherwise.
    """
    try:
        stored_hashes = json.loads(device.encrypted_backup_codes or "[]")
    except (json.JSONDecodeError, Exception):
        logger.warning("Could not parse backup codes for device %s", device.id)
        return False

    incoming_hash = hash_backup_code(plain_code.upper())
    if incoming_hash in stored_hashes:
        stored_hashes.remove(incoming_hash)
        device.encrypted_backup_codes = json.dumps(stored_hashes)
        device.last_used_at = timezone.now()
        device.save(update_fields=["encrypted_backup_codes", "last_used_at", "updated_at"])
        return True

    return False


# ─── Device Lifecycle ─────────────────────────────────────────────────────────


def get_or_create_device(user):
    """
    Get or create a TOTPDevice for the given user.
    New devices are created with is_active=False.
    A new secret is generated only if creating a new device.
    """
    from apps.core.models import TOTPDevice

    device, created = TOTPDevice.objects.get_or_create(
        user=user,
        defaults={"encrypted_secret": generate_totp_secret(), "is_active": False},
    )
    if not created and not device.is_active:
        # Regenerate secret so each setup attempt gets a fresh secret
        device.encrypted_secret = generate_totp_secret()
        device.save(update_fields=["encrypted_secret", "updated_at"])
    return device


def activate_device(device, totp_code: str) -> tuple:
    """
    Verify TOTP code and activate the device if valid.

    Returns:
        (True, [plain_backup_codes]) on success
        (False, None) if TOTP code is invalid
    """
    secret = device.encrypted_secret  # decrypted by EncryptedCharField
    if not verify_totp_code(secret, totp_code):
        return False, None

    plain_codes = generate_backup_codes(BACKUP_CODE_COUNT)
    hashed_codes = [hash_backup_code(c) for c in plain_codes]

    device.encrypted_backup_codes = json.dumps(hashed_codes)
    device.is_active = True
    device.confirmed_at = timezone.now()
    device.save(update_fields=["encrypted_backup_codes", "is_active", "confirmed_at", "updated_at"])

    return True, plain_codes


# ─── JWT MFA State ────────────────────────────────────────────────────────────


def is_mfa_verified(request) -> bool:
    """
    Check whether the current request's JWT contains the mfa_verified=True claim.
    Returns False on any error (fail-safe — always require MFA if uncertain).
    """
    try:
        from rest_framework_simplejwt.authentication import JWTAuthentication

        jwt_auth = JWTAuthentication()
        validated = jwt_auth.get_validated_token(
            jwt_auth.get_raw_token(jwt_auth.get_header(request))
        )
        return bool(validated.get("mfa_verified", False))
    except Exception:
        return False


def get_mfa_grace_expiry(user) -> datetime | None:
    """
    Returns the MFA grace period expiry datetime for the user, or None.
    Grace period: MFA_GRACE_PERIOD_SECONDS after the device was confirmed.
    """
    try:
        device = user.totp_device
        if device.is_active and device.confirmed_at:
            return device.confirmed_at + timezone.timedelta(seconds=MFA_GRACE_PERIOD_SECONDS)
    except Exception:
        pass
    return None
