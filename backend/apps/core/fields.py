"""Shared encrypted model fields (LGPD — campos sensíveis).

Extends django-encrypted-model-fields (the library already used for CPF, the
TOTP secret and the AI scribe transcription) with a JSON variant so that
structured PII such as the patient address can be encrypted at rest while
staying transparently dict/list-shaped to every reader.

Like every Fernet-backed encrypted field, the ciphertext is non-deterministic:
the column is stored as TEXT and CANNOT be indexed, searched or filtered at the
database level (no JSON-path queries).
"""

import json

import cryptography.fernet
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from encrypted_model_fields.fields import decrypt_str, encrypt_str


class EncryptedJSONField(models.JSONField):
    """A ``JSONField`` whose value is encrypted at rest with the project's
    ``FIELD_ENCRYPTION_KEY`` (same key/crypter as ``EncryptedCharField`` &co).

    The JSON is serialised to a string, encrypted, and stored in a TEXT column.
    On read it is decrypted and parsed back into the native Python value, so all
    existing dict-based access (``patient.address.get("city")``) keeps working
    and DRF still maps it to a ``serializers.JSONField``.

    Rows written before the field was encrypted (plaintext JSON) are detected
    via ``InvalidToken`` and parsed as-is, so the schema migration can run before
    the data migration re-encrypts existing rows.
    """

    def get_internal_type(self):
        # Store as TEXT (encrypted blob), not jsonb — the ciphertext is opaque.
        return "TextField"

    def get_db_prep_save(self, value, connection):
        if value is None:
            return value
        encoder = self.encoder or DjangoJSONEncoder
        return encrypt_str(json.dumps(value, cls=encoder)).decode("utf-8")

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        try:
            value = decrypt_str(value)
        except cryptography.fernet.InvalidToken:
            # Legacy plaintext row (pre-encryption) — parse it directly.
            pass
        try:
            return json.loads(value, cls=self.decoder)
        except (TypeError, ValueError):
            return value
