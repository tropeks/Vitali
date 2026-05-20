"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CalendarDays,
  ClipboardList,
  Pill,
  ShieldAlert,
} from "lucide-react";

import { StatusBadge } from "@/components/shared";
import { resolveBadgeMeta } from "@/lib/operational-ui";
import {
  PORTAL_ALLERGY_SEVERITY,
  PORTAL_APPOINTMENT_STATUS,
  PORTAL_PRESCRIPTION_STATUS,
  formatDateBR,
  formatDateTimeBR,
} from "@/lib/portal-status";
import {
  portalApi,
  PortalNotActiveError,
  PortalUnauthorizedError,
  type PortalAllergy,
  type PortalAppointment,
  type PortalPatient,
  type PortalPrescription,
} from "@/lib/portal-api";

interface HomeState {
  loading: boolean;
  error: string | null;
  patient: PortalPatient | null;
  nextAppointment: PortalAppointment | null;
  activeAllergies: PortalAllergy[];
  recentPrescriptions: PortalPrescription[];
}

export default function PortalHomePage() {
  const [state, setState] = useState<HomeState>({
    loading: true,
    error: null,
    patient: null,
    nextAppointment: null,
    activeAllergies: [],
    recentPrescriptions: [],
  });

  useEffect(() => {
    async function load() {
      try {
        const [patient, appointments, allergies, prescriptions] = await Promise.all([
          portalApi.getMyProfile(),
          portalApi.getMyAppointments(),
          portalApi.getMyAllergies(),
          portalApi.getMyPrescriptions(),
        ]);
        const now = Date.now();
        const upcoming = appointments
          .filter(
            (a) =>
              new Date(a.start_time).getTime() >= now &&
              a.status !== "cancelled" &&
              a.status !== "completed",
          )
          .sort(
            (a, b) =>
              new Date(a.start_time).getTime() - new Date(b.start_time).getTime(),
          );
        setState({
          loading: false,
          error: null,
          patient,
          nextAppointment: upcoming[0] ?? null,
          activeAllergies: allergies.filter((a) => a.status === "active"),
          recentPrescriptions: prescriptions.slice(0, 5),
        });
      } catch (err) {
        if (err instanceof PortalUnauthorizedError) {
          window.location.assign("/portal/login");
          return;
        }
        if (err instanceof PortalNotActiveError) {
          window.location.assign("/portal/activate");
          return;
        }
        setState((s) => ({
          ...s,
          loading: false,
          error: "Não foi possível carregar suas informações. Tente novamente.",
        }));
      }
    }
    load();
  }, []);

  if (state.loading) {
    return <p className="text-sm text-slate-500">Carregando suas informações…</p>;
  }
  if (state.error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
        {state.error}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">
          Olá, {state.patient?.social_name || state.patient?.full_name?.split(" ")[0] || "paciente"}
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          Aqui você acompanha suas consultas, prontuário e receitas.
        </p>
      </div>

      {/* Allergy banner — life-threatening or severe gets a loud surface */}
      {state.activeAllergies.length > 0 && (
        <AllergyBanner allergies={state.activeAllergies} />
      )}

      {/* Next appointment */}
      <section className="rounded-lg border border-slate-200 bg-white">
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <h2 className="inline-flex items-center gap-2 text-base font-semibold text-slate-900">
            <CalendarDays size={18} className="text-blue-600" />
            Próxima consulta
          </h2>
          <Link
            href="/portal/agendamentos"
            className="text-sm font-medium text-blue-700 hover:underline"
          >
            Ver todas
          </Link>
        </div>
        <div className="p-4">
          {state.nextAppointment ? (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-slate-900">
                  {formatDateTimeBR(state.nextAppointment.start_time)}
                </p>
                <p className="text-xs text-slate-500">
                  Tipo: {state.nextAppointment.type || "consulta"}
                </p>
              </div>
              <StatusBadge
                meta={resolveBadgeMeta(
                  PORTAL_APPOINTMENT_STATUS,
                  state.nextAppointment.status,
                )}
              />
            </div>
          ) : (
            <p className="text-sm text-slate-500">
              Você não tem consultas agendadas no momento.
            </p>
          )}
        </div>
      </section>

      {/* Quick links */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <QuickLink
          href="/portal/receitas"
          icon={Pill}
          title="Receitas"
          subtitle={`${state.recentPrescriptions.length} recente${state.recentPrescriptions.length === 1 ? "" : "s"}`}
        />
        <QuickLink
          href="/portal/prontuario"
          icon={ClipboardList}
          title="Prontuário"
          subtitle="Atendimentos assinados pelo médico"
        />
        <QuickLink
          href="/portal/alergias"
          icon={ShieldAlert}
          title="Alergias"
          subtitle={`${state.activeAllergies.length} ativa${state.activeAllergies.length === 1 ? "" : "s"}`}
        />
      </div>

      {/* Recent prescriptions */}
      {state.recentPrescriptions.length > 0 && (
        <section className="rounded-lg border border-slate-200 bg-white">
          <div className="border-b border-slate-100 px-4 py-3">
            <h2 className="text-base font-semibold text-slate-900">Receitas recentes</h2>
          </div>
          <ul className="divide-y divide-slate-100">
            {state.recentPrescriptions.map((rx) => (
              <li key={rx.id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="text-sm font-medium text-slate-900">
                    {formatDateBR(rx.signed_at ?? rx.created_at)}
                  </p>
                  {rx.notes && (
                    <p className="mt-0.5 text-xs text-slate-500 line-clamp-1">{rx.notes}</p>
                  )}
                </div>
                <StatusBadge
                  meta={resolveBadgeMeta(PORTAL_PRESCRIPTION_STATUS, rx.status)}
                />
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function AllergyBanner({ allergies }: { allergies: PortalAllergy[] }) {
  const worst = allergies.reduce<PortalAllergy | null>((acc, a) => {
    const order = ["mild", "moderate", "severe", "life_threatening"];
    if (!acc) return a;
    return order.indexOf(a.severity) > order.indexOf(acc.severity) ? a : acc;
  }, null);
  if (!worst) return null;
  const loud = worst.severity === "life_threatening" || worst.severity === "severe";
  return (
    <div
      className={`flex items-start gap-3 rounded-lg border px-4 py-3 ${
        loud ? "border-red-200 bg-red-50" : "border-yellow-200 bg-yellow-50"
      }`}
    >
      <AlertTriangle
        size={18}
        className={loud ? "text-red-600" : "text-yellow-700"}
      />
      <div className="flex-1">
        <p
          className={`text-sm font-semibold ${
            loud ? "text-red-800" : "text-yellow-900"
          }`}
        >
          Alergia registrada — {worst.substance}
        </p>
        <p className={`text-xs ${loud ? "text-red-700" : "text-yellow-800"}`}>
          Severidade: {
            resolveBadgeMeta(PORTAL_ALLERGY_SEVERITY, worst.severity).label
          }
          {allergies.length > 1 && ` · ${allergies.length - 1} outra${allergies.length - 1 === 1 ? "" : "s"}`}.
          Sempre informe ao profissional de saúde.
        </p>
      </div>
    </div>
  );
}

function QuickLink({
  href,
  icon: Icon,
  title,
  subtitle,
}: {
  href: string;
  icon: typeof CalendarDays;
  title: string;
  subtitle: string;
}) {
  return (
    <Link
      href={href}
      className="group flex items-center gap-3 rounded-lg border border-slate-200 bg-white p-4 transition-colors hover:border-blue-300 hover:bg-blue-50/40"
    >
      <span className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-700 group-hover:bg-blue-100">
        <Icon size={20} />
      </span>
      <div>
        <p className="text-sm font-semibold text-slate-900">{title}</p>
        <p className="text-xs text-slate-500">{subtitle}</p>
      </div>
    </Link>
  );
}
