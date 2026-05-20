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

async function portalFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
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

// ─── Endpoints ───────────────────────────────────────────────────────────────

export const portalApi = {
  getMyProfile: () => portalFetch<PortalPatient>("/portal/me/"),
  getMyAppointments: () => portalFetch<PortalAppointment[]>("/portal/me/appointments/"),
  getMyEncounters: () => portalFetch<PortalEncounter[]>("/portal/me/encounters/"),
  getMyPrescriptions: () => portalFetch<PortalPrescription[]>("/portal/me/prescriptions/"),
  getMyAllergies: () => portalFetch<PortalAllergy[]>("/portal/me/allergies/"),
  activateInvite: (inviteToken: string) =>
    portalFetch<{ id: string; status: string }>("/portal/access/activate/", {
      method: "POST",
      body: JSON.stringify({ invite_token: inviteToken }),
    }),
};
