"use client";

import { useEffect, useState } from "react";

import {
  portalApi,
  PortalNotActiveError,
  PortalUnauthorizedError,
  type PortalPatient,
} from "@/lib/portal-api";
import { formatDateBR } from "@/lib/portal-status";

const GENDER_LABEL: Record<string, string> = {
  M: "Masculino",
  F: "Feminino",
  O: "Outro",
  N: "Não informado",
};

export default function PortalProfilePage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [patient, setPatient] = useState<PortalPatient | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setPatient(await portalApi.getMyProfile());
        setLoading(false);
      } catch (err) {
        if (err instanceof PortalUnauthorizedError) {
          window.location.assign("/portal/login");
          return;
        }
        if (err instanceof PortalNotActiveError) {
          window.location.assign("/portal/activate");
          return;
        }
        setError("Não foi possível carregar seu perfil.");
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) return <p className="text-sm text-slate-500">Carregando…</p>;
  if (error)
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
        {error}
      </div>
    );
  if (!patient) return null;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Meu perfil</h1>
        <p className="mt-1 text-sm text-slate-600">
          Para corrigir qualquer informação, fale com a recepção da clínica.
        </p>
      </div>

      <section className="rounded-lg border border-slate-200 bg-white">
        <div className="border-b border-slate-100 px-4 py-3">
          <h2 className="text-base font-semibold text-slate-900">Dados pessoais</h2>
        </div>
        <dl className="divide-y divide-slate-100">
          <Row label="Nome" value={patient.full_name} />
          <Row label="Nome social" value={patient.social_name || "—"} />
          <Row label="Data de nascimento" value={formatDateBR(patient.birth_date)} />
          <Row label="Idade" value={`${patient.age} anos`} />
          <Row label="Gênero" value={GENDER_LABEL[patient.gender] ?? patient.gender} />
          <Row label="Tipo sanguíneo" value={patient.blood_type || "—"} />
          <Row label="Prontuário" value={patient.medical_record_number || "—"} mono />
        </dl>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white">
        <div className="border-b border-slate-100 px-4 py-3">
          <h2 className="text-base font-semibold text-slate-900">Contato</h2>
        </div>
        <dl className="divide-y divide-slate-100">
          <Row label="E-mail" value={patient.email || "—"} />
          <Row label="Telefone" value={patient.phone || "—"} />
          <Row label="WhatsApp" value={patient.whatsapp || "—"} />
        </dl>
      </section>
    </div>
  );
}

function Row({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 px-4 py-3">
      <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {label}
      </dt>
      <dd className={`text-sm text-slate-900 ${mono ? "font-mono" : ""}`}>{value}</dd>
    </div>
  );
}
