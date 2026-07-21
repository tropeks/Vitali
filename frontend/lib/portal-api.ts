/**
 * Typed fetch client for the Patient Portal REST surface.
 *
 * The portal user authenticates through the same `/api/auth/login` Next.js
 * route as staff (one cookie set, same JWT). The differentiator is the
 * backend's `IsPortalSelfAccess` permission — checked here at layout level
 * by calling `getMyProfile()` on every protected layout render.
 *
 * Errors are typed: `PortalUnauthorizedError` means redirect to /portal/login;
 * `PortalNotActiveError` means redirect to /portal/activate. Everything else
 * is a `PortalApiError` carrying the HTTP status.
 */

import { getAccessToken } from "@/lib/auth";

export class PortalApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
    message?: string,
  ) {
    super(message ?? `Portal API error ${status}`);
    this.name = "PortalApiError";
  }
}

export class PortalUnauthorizedError extends PortalApiError {
  constructor(body: unknown) {
    super(401, body, "Sessão expirada");
    this.name = "PortalUnauthorizedError";
  }
}

export class PortalNotActiveError extends PortalApiError {
  constructor(body: unknown) {
    super(403, body, "Portal access not active");
    this.name = "PortalNotActiveError";
  }
}

async function portalFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const token = getAccessToken();
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(init.headers ?? {}),
  };
  const resp = await fetch(`/api/v1${path}`, { ...init, headers });
  if (resp.status === 401) {
    throw new PortalUnauthorizedError(await resp.json().catch(() => ({})));
  }
  if (resp.status === 403) {
    throw new PortalNotActiveError(await resp.json().catch(() => ({})));
  }
  if (!resp.ok) {
    throw new PortalApiError(resp.status, await resp.json().catch(() => ({})));
  }
  return (await resp.json()) as T;
}

/**
 * Fetch a binary/blob response (used for LGPD data exports, which the backend
 * returns as a JSON payload or a generated PDF rather than the usual decoded
 * JSON object). Shares the same auth + typed-error handling as `portalFetch`.
 */
async function portalFetchBlob(path: string): Promise<Blob> {
  const token = getAccessToken();
  const headers: HeadersInit = {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const resp = await fetch(`/api/v1${path}`, { headers });
  if (resp.status === 401) {
    throw new PortalUnauthorizedError(await resp.json().catch(() => ({})));
  }
  if (resp.status === 403) {
    throw new PortalNotActiveError(await resp.json().catch(() => ({})));
  }
  if (!resp.ok) {
    throw new PortalApiError(resp.status, await resp.json().catch(() => ({})));
  }
  return resp.blob();
}

// ─── Resource types ──────────────────────────────────────────────────────────

export interface PortalPatient {
  id: string;
  full_name: string;
  social_name: string;
  birth_date: string;
  age: number;
  gender: string;
  blood_type: string;
  phone: string;
  whatsapp: string;
  email: string;
  medical_record_number: string;
}

export interface PortalAppointment {
  id: string;
  start_time: string;
  end_time: string;
  status: string;
  type: string;
  professional: string;
  created_at: string;
}

export interface PortalEncounter {
  id: string;
  encounter_date: string;
  status: string;
  chief_complaint: string;
  professional: string;
  signed_at: string | null;
}

export interface PortalPrescription {
  id: string;
  encounter: string;
  status: string;
  signed_at: string | null;
  notes: string;
  created_at: string;
}

export interface PortalAllergy {
  id: string;
  substance: string;
  reaction: string;
  severity: string;
  status: string;
  created_at: string;
}

export interface PortalLabItem {
  id: string;
  test_name: string;
  category: string;
  method: string;
  specimen_type: string;
  unit: string;
  reference_range: string;
  result_value: string;
  abnormal_flag: string;
  abnormal_flag_display: string;
  result_notes: string;
  validated_at: string;
}

export interface PortalLabOrder {
  id: string;
  accession_number: string;
  requested_at: string;
  completed_at: string;
  clinical_indication: string;
  items: PortalLabItem[];
  report_url: string;
}

// ─── Endpoints ───────────────────────────────────────────────────────────────

export const portalApi = {
  getMyProfile: () => portalFetch<PortalPatient>("/portal/me/"),
  getMyAppointments: () =>
    portalFetch<PortalAppointment[]>("/portal/me/appointments/"),
  getMyEncounters: () =>
    portalFetch<PortalEncounter[]>("/portal/me/encounters/"),
  getMyPrescriptions: () =>
    portalFetch<PortalPrescription[]>("/portal/me/prescriptions/"),
  getMyAllergies: () => portalFetch<PortalAllergy[]>("/portal/me/allergies/"),
  getMyLabResults: () =>
    portalFetch<PortalLabOrder[]>("/portal/me/lab-results/"),
  downloadLabReport: (orderId: string) =>
    portalFetchBlob(
      `/portal/me/lab-results/${encodeURIComponent(orderId)}/report/`,
    ),
  activateInvite: (inviteToken: string) =>
    portalFetch<{ id: string; status: string }>("/portal/access/activate/", {
      method: "POST",
      body: JSON.stringify({ invite_token: inviteToken }),
    }),
  // LGPD data portability: download the full self-data export as JSON or PDF.
  exportMyData: (exportFormat: "json" | "pdf") =>
    portalFetchBlob(`/portal/me/export/?export_format=${exportFormat}`),
  // LGPD: register an audited account-deletion request. Clinical records are
  // retained (CFM 20-year rule) — this only files the request for the clinic.
  requestAccountDeletion: (reason: string) =>
    portalFetch<{ detail: string }>("/portal/me/delete-request/", {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
};
