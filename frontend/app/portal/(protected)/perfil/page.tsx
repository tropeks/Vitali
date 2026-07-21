"use client";

import { useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle,
  FileJson,
  FileText,
  Loader2,
  ShieldAlert,
  Trash2,
} from "lucide-react";

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

  if (loading) return <p className="text-sm text-[#8C959F]">Carregando…</p>;
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
        <h1 className="text-2xl font-semibold text-[#24292F]">Meu perfil</h1>
        <p className="mt-1 text-sm text-[#57606A]">
          Para corrigir qualquer informação, fale com a recepção da clínica.
        </p>
      </div>

      <section className="rounded-lg border border-slate-200 bg-[#F4F7FA]">
        <div className="border-b border-slate-100 px-4 py-3">
          <h2 className="text-base font-semibold text-[#24292F]">Dados pessoais</h2>
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

      <section className="rounded-lg border border-slate-200 bg-[#F4F7FA]">
        <div className="border-b border-slate-100 px-4 py-3">
          <h2 className="text-base font-semibold text-[#24292F]">Contato</h2>
        </div>
        <dl className="divide-y divide-slate-100">
          <Row label="E-mail" value={patient.email || "—"} />
          <Row label="Telefone" value={patient.phone || "—"} />
          <Row label="WhatsApp" value={patient.whatsapp || "—"} />
        </dl>
      </section>

      <PrivacySection patientId={patient.id} />
    </div>
  );
}

/**
 * LGPD (Lei Geral de Proteção de Dados) self-service section: data portability
 * (download as JSON / PDF) and the right to request account deletion. Deletion
 * only files an audited request — clinical records are retained for 20 years
 * per CFM rules and are never physically removed here.
 */
function PrivacySection({ patientId }: { patientId: string }) {
  const [exporting, setExporting] = useState<"json" | "pdf" | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [reason, setReason] = useState("");
  const [deleteState, setDeleteState] = useState<
    "idle" | "submitting" | "success" | "error"
  >("idle");
  const [deleteMessage, setDeleteMessage] = useState<string | null>(null);

  async function handleExport(exportFormat: "json" | "pdf") {
    if (exporting) return;
    setExporting(exportFormat);
    setExportError(null);
    try {
      const blob = await portalApi.exportMyData(exportFormat);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `meus-dados-${patientId}.${exportFormat}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch {
      setExportError("Não foi possível gerar o arquivo. Tente novamente.");
    } finally {
      setExporting(null);
    }
  }

  async function handleDeleteRequest() {
    if (deleteState === "submitting") return;
    setDeleteState("submitting");
    setDeleteMessage(null);
    try {
      const res = await portalApi.requestAccountDeletion(reason.trim());
      setDeleteMessage(res.detail);
      setDeleteState("success");
      setConfirmingDelete(false);
    } catch {
      setDeleteMessage("Não foi possível registrar a solicitação. Tente novamente.");
      setDeleteState("error");
    }
  }

  return (
    <section className="rounded-lg border border-slate-200 bg-[#F4F7FA]">
      <div className="border-b border-slate-100 px-4 py-3">
        <h2 className="text-base font-semibold text-[#24292F]">Privacidade e dados</h2>
        <p className="mt-0.5 text-xs text-[#8C959F]">
          Seus direitos previstos na LGPD (Lei nº 13.709/2018).
        </p>
      </div>

      <div className="space-y-4 px-4 py-4">
        <div>
          <h3 className="text-sm font-semibold text-[#24292F]">Baixar meus dados</h3>
          <p className="mt-0.5 text-xs text-[#57606A]">
            Exporte uma cópia dos seus dados (cadastro, consultas, atendimentos,
            receitas e alergias).
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => handleExport("json")}
              disabled={exporting !== null}
              className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-[#24292F] shadow-[0_1px_3px_rgba(0,0,0,0.06)] transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {exporting === "json" ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <FileJson size={16} className="text-[#0066A1]" />
              )}
              Baixar meus dados (JSON)
            </button>
            <button
              type="button"
              onClick={() => handleExport("pdf")}
              disabled={exporting !== null}
              className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-[#24292F] shadow-[0_1px_3px_rgba(0,0,0,0.06)] transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {exporting === "pdf" ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <FileText size={16} className="text-[#0066A1]" />
              )}
              Baixar meus dados (PDF)
            </button>
          </div>
          {exportError && (
            <div className="mt-2 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2">
              <AlertCircle size={16} className="mt-0.5 shrink-0 text-red-600" />
              <p className="text-sm text-red-800">{exportError}</p>
            </div>
          )}
        </div>

        <div className="border-t border-slate-100 pt-4">
          <h3 className="text-sm font-semibold text-[#24292F]">Excluir minha conta</h3>
          <div className="mt-1 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
            <ShieldAlert size={16} className="mt-0.5 shrink-0 text-amber-600" />
            <p className="text-xs text-amber-800">
              A solicitação é registrada e analisada pela clínica. Seus dados
              clínicos (prontuário) <strong>não são apagados</strong>: a legislação
              do CFM exige retenção por 20 anos.
            </p>
          </div>

          {deleteState === "success" ? (
            <div className="mt-3 flex items-start gap-2 rounded-lg border border-green-200 bg-green-50 px-3 py-2">
              <CheckCircle size={16} className="mt-0.5 shrink-0 text-green-700" />
              <p className="text-sm text-green-800">{deleteMessage}</p>
            </div>
          ) : confirmingDelete ? (
            <div className="mt-3 space-y-3">
              <div>
                <label
                  htmlFor="delete-reason"
                  className="text-xs font-semibold uppercase tracking-wide text-[#8C959F]"
                >
                  Motivo (opcional)
                </label>
                <textarea
                  id="delete-reason"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  rows={3}
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="Conte por que deseja excluir a conta…"
                />
              </div>
              {deleteState === "error" && deleteMessage && (
                <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2">
                  <AlertCircle size={16} className="mt-0.5 shrink-0 text-red-600" />
                  <p className="text-sm text-red-800">{deleteMessage}</p>
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={handleDeleteRequest}
                  disabled={deleteState === "submitting"}
                  className="inline-flex items-center justify-center gap-2 rounded-lg bg-gradient-to-b from-[#C13515] to-[#A12810] border-t border-[#d4583a] px-4 py-2.5 text-sm font-semibold text-white shadow-[0_3px_10px_rgba(193,53,21,0.3)] transition-shadow hover:shadow-[0_5px_15px_rgba(193,53,21,0.4)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {deleteState === "submitting" && (
                    <Loader2 size={16} className="animate-spin" />
                  )}
                  Confirmar solicitação
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setConfirmingDelete(false);
                    setDeleteState("idle");
                    setDeleteMessage(null);
                  }}
                  disabled={deleteState === "submitting"}
                  className="inline-flex items-center justify-center rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-[#24292F] transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Cancelar
                </button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmingDelete(true)}
              className="mt-3 inline-flex items-center justify-center gap-2 rounded-lg border border-red-200 bg-white px-4 py-2.5 text-sm font-semibold text-[#C13515] shadow-[0_1px_3px_rgba(0,0,0,0.06)] transition-colors hover:bg-red-50"
            >
              <Trash2 size={16} />
              Solicitar exclusão de conta
            </button>
          )}
        </div>
      </div>
    </section>
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
      <dt className="text-xs font-semibold uppercase tracking-wide text-[#8C959F]">
        {label}
      </dt>
      <dd className={`text-sm text-[#24292F] ${mono ? "font-mono" : ""}`}>{value}</dd>
    </div>
  );
}
