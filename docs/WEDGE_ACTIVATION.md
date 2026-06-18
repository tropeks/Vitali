# Wedge Activation Runbook

This runbook describes the procedure to gradually activate Wedges (external integrations or advanced modules) in a Pilot tenant. To minimize disruption and ensure data integrity, Wedges are activated in two waves.

## Wave 1: Zero-Data / Read-Only Setup
**When to activate:** Day 1 of the pilot, immediately after the tenant is provisioned but *before* the bulk of the curated clinical data is imported.

**Included Wedges:**
- **Identity & Access Management (SSO / MFA)**: Ensure users can log in securely.
- **Basic Telemetry & Audit Logs**: Ensure all actions from day 1 are logged.
- **Static Configurations**: Setup clinic structure, schedules, and billing static data.

**Procedure:**
1. Enable the `WEDGE_WAVE_1` feature flag for the tenant.
2. Verify that users can authenticate.
3. Validate that audit logs are recording events correctly (e.g., test by logging in).

## Wave 2: Full Data-Driven Modules
**When to activate:** After the core data (Patients, Professionals, and Insurances) has been imported, cleaned, and verified (curated data). 

**Included Wedges:**
- **AI Modules (Whisper transcription, TUSS suggestion, etc.)**: Requires a signed DPA and valid historical data.
- **WhatsApp Integration (Evolution API)**: Ensure patient routing uses correct dedup keys (WhatsApp number).
- **Asaas Billing Integration (PIX)**: Wait until all professional accounts are fully set up.

**Procedure:**
1. Ensure the `FEATURE_AI_GLOBAL` or equivalent flags are toggled.
2. Ensure the clinic has a signed DPA (Data Processing Agreement) recorded in the admin panel before enabling AI.
3. Toggle the `WEDGE_WAVE_2` feature flag for the tenant.
4. Run the post-activation sync scripts if necessary to warm up caches for AI suggestions.

## Kill-Switches (Emergency Disablement)
If a Wedge causes severe issues (e.g., incorrect billing, AI hallucinations, or WhatsApp spam), you can immediately disable it per-tenant or globally.

- **Global Kill-Switch**: In Django Admin > Feature Flags, set the module flag (e.g., `whatsapp_integration`) to `False` globally.
- **Tenant-Level Kill-Switch**: In the Django shell:
  ```python
  from apps.core.models import FeatureFlag, Tenant
  tenant = Tenant.objects.get(schema_name="pilot_schema")
  FeatureFlag.objects.update_or_create(
      tenant=tenant, 
      module_key="whatsapp_integration", 
      defaults={"is_enabled": False}
  )
  ```
- **Fallback Behavior**: The system degrades gracefully. For example, if the AI Escriba is disabled, users must type their SOAP notes manually. If WhatsApp is disabled, users must communicate via standard SMS/calls without automation.
