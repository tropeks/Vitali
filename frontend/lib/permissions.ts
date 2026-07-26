/**
 * Canonical RBAC permission catalog for the Vitali frontend.
 *
 * SINGLE SOURCE OF TRUTH for nav↔permission mapping. Every string here mirrors a
 * permission the backend actually enforces — do NOT invent strings the backend
 * does not check. Derived from `backend/apps/core/permissions.py`:
 *   - `ADMIN_PERMISSIONS` (the exhaustive admin role set),
 *   - the per-role sets (`CLINICAL_PRESCRIBER_PERMISSIONS`, `NURSING_PERMISSIONS`,
 *     `RECEPTION_PERMISSIONS`, `PHARMACY_PERMISSIONS`, `BILLING_PERMISSIONS`) —
 *     which add `patients.limited_read`, `emr.partial_write`,
 *   - and literals passed to `HasPermission("…")` across the apps
 *     (`hr.manage` is enforced by `apps/hr/views.HRAccessPermission` but is not in
 *     the admin list, so it is included here explicitly).
 *
 * The menu is UX only (defense in depth). The real security boundary stays the
 * backend `permission_classes`; hiding a menu item is never an access control.
 */

import type { UserDTO } from "@/lib/auth";

export const PERMISSIONS = {
  // Tenant-admin capability (non-forgeable; see role_has_admin_capability)
  ADMIN: "admin",

  // EMR / clinical
  EMR_READ: "emr.read",
  EMR_WRITE: "emr.write",
  EMR_PARTIAL_WRITE: "emr.partial_write",
  EMR_SIGN: "emr.sign",
  EMR_DELETE: "emr.delete",

  // Patients
  PATIENTS_READ: "patients.read",
  PATIENTS_LIMITED_READ: "patients.limited_read",
  PATIENTS_WRITE: "patients.write",
  PATIENTS_DELETE: "patients.delete",

  // Scheduling
  SCHEDULE_READ: "schedule.read",
  SCHEDULE_WRITE: "schedule.write",
  SMART_SCHEDULING_READ: "smart_scheduling.read",

  // Billing / financial
  BILLING_READ: "billing.read",
  BILLING_WRITE: "billing.write",
  BILLING_FULL: "billing.full",

  // Pharmacy / supplies
  PHARMACY_READ: "pharmacy.read",
  PHARMACY_DISPENSE: "pharmacy.dispense",
  PHARMACY_DISPENSE_CONTROLLED: "pharmacy.dispense_controlled",
  PHARMACY_FULL: "pharmacy.full",
  PHARMACY_CATALOG_MANAGE: "pharmacy.catalog_manage",
  PHARMACY_STOCK_MANAGE: "pharmacy.stock_manage",
  PHARMACY_WAREHOUSE_MANAGE: "pharmacy.warehouse_manage",
  PHARMACY_INVENTORY_COUNT: "pharmacy.inventory_count",
  PHARMACY_INVENTORY_APPROVE: "pharmacy.inventory_approve",
  PHARMACY_TRANSFER_MANAGE: "pharmacy.transfer_manage",
  PHARMACY_TRANSFER_ACCEPT: "pharmacy.transfer_accept",
  PHARMACY_RECALL_MANAGE: "pharmacy.recall_manage",
  PHARMACY_QUARANTINE_MANAGE: "pharmacy.quarantine_manage",
  PHARMACY_CLINICAL_VALIDATE: "pharmacy.clinical_validate",
  PHARMACY_AI_READ: "pharmacy_ai.read",

  // Medication administration / nursing
  EMAR_READ: "emar.read",
  EMAR_ADMINISTER: "emar.administer",
  SAE_READ: "sae.read",
  SAE_WRITE: "sae.write",

  // Imaging / diagnostics
  IMAGING_READ: "imaging.read",
  IMAGING_WRITE: "imaging.write",
  FHIR_READ: "fhir.read",
  TRIAGE_READ: "triage.read",
  TRIAGE_RESPOND: "triage.respond",
  TELEMEDICINE_READ: "telemedicine.read",
  TELEMEDICINE_HOST: "telemedicine.host",

  // People & operations (HR)
  HR_MANAGE: "hr.manage",

  // Users / roles administration
  USERS_READ: "users.read",
  USERS_WRITE: "users.write",
  ROLES_READ: "roles.read",
  ROLES_WRITE: "roles.write",

  // Reporting / workflow / privacy
  REPORTS_READ: "reports.read",
  WORKFLOW_READ: "workflow.read",
  WORKFLOW_REQUEST: "workflow.request",
  WORKFLOW_APPROVE: "workflow.approve",
  PRIVACY_READ: "privacy.read",
  PRIVACY_MANAGE: "privacy.manage",

  // Organization / identity (MPI)
  ORGANIZATION_READ: "organization.read",
  ORGANIZATION_WRITE: "organization.write",
  ORGANIZATION_DELETE: "organization.delete",
  MPI_READ: "mpi.read",
  MPI_WRITE: "mpi.write",
  MPI_REVIEW: "mpi.review",

  // Integrations / signatures / AI / mobile
  INTEGRATIONS_OPERATIONS_READ: "integrations.operations.read",
  INTEGRATIONS_REPLAY: "integrations.replay",
  SIGNATURES_READ: "signatures.read",
  SIGNATURES_SIGN: "signatures.sign",
  AI_USE: "ai.use",
  AI_MANAGE: "ai.manage",
  MOBILE_ADMIN: "mobile.admin",
} as const;

/** A backend-enforced permission string. */
export type Permission = (typeof PERMISSIONS)[keyof typeof PERMISSIONS];

/** Flat list of every catalog permission (deduped). */
export const ALL_PERMISSIONS: Permission[] = Array.from(
  new Set(Object.values(PERMISSIONS)),
) as Permission[];

/**
 * Visibility gate carried by a nav entry. All three dimensions are optional and
 * evaluated in order by {@link canSee}. Absent dimensions do not restrict.
 */
export interface NavGate {
  /** Module/tier key checked against the tenant's active modules (FeatureFlag). */
  module?: string;
  /** RBAC permissions — visible if the user holds AT LEAST ONE (`.some`). */
  permissions?: Permission[];
  /** Platform (superuser) gate — only for Vitali platform operators. */
  superuser?: boolean;
}

/**
 * Decide whether a nav entry is visible for `user`, given the tenant's resolved
 * `activeModules` (null = still loading).
 *
 * Gate order and fail-safe policy (see UI_NAVIGATION_IA.md §6):
 *   1. Module/tier — fail-OPEN while modules load (`null`) to avoid flicker;
 *      once resolved, a missing module hides the item.
 *   2. Superuser — fail-SAFE: hidden unless `is_superuser === true` (an absent
 *      signal keeps Plataforma hidden by default).
 *   3. RBAC permission — NEVER fail-open: a user without at least one listed
 *      permission is hidden. This is the dominant gate.
 *
 * This is UX only; the backend `permission_classes` remains the real barrier.
 */
export function canSee(
  user: Pick<UserDTO, "permissions" | "is_superuser">,
  gate: NavGate,
  activeModules: string[] | null,
): boolean {
  // Gate 1 — module/tier (fail-open while loading).
  if (gate.module && activeModules !== null && !activeModules.includes(gate.module)) {
    return false;
  }

  // Gate 2 — superuser / Plataforma (fail-safe: undefined → hidden).
  if (gate.superuser && user.is_superuser !== true) {
    return false;
  }

  // Gate 3 — RBAC permission (never fail-open).
  if (gate.permissions && gate.permissions.length > 0) {
    const held = user.permissions ?? [];
    if (!gate.permissions.some((permission) => held.includes(permission))) {
      return false;
    }
  }

  return true;
}
