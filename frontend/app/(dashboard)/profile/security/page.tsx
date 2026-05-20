"use client";

import { useState, useEffect } from "react";
import { ShieldCheck, ShieldOff, Loader2, Download, QrCode } from "lucide-react";
import { getAccessToken } from "@/lib/auth";
import { PageShell, SectionState, StatusBadge } from "@/components/shared";
import { getMfaStatusMeta } from "@/lib/operational-ui";

type Step = "idle" | "qr" | "verify" | "backup";

interface SetupData {
  secret: string;
  qr_uri: string;
  qr_image_base64: string;
}

interface MFAStatus {
  is_active: boolean;
}

async function apiFetch(path: string, options?: RequestInit) {
  const token = getAccessToken();
  const res = await fetch(`/api/v1${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      ...(options?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error ?? `Erro ${res.status}`);
  }
  return res.json();
}

function downloadBackupCodes(codes: string[]) {
  const content = [
    "Vitali — Códigos de Backup MFA",
    "================================",
    "Guarde estes códigos em local seguro.",
    "Cada código só pode ser usado uma vez.",
    "",
    ...codes.map((c, i) => `${i + 1}. ${c}`),
    "",
    `Gerado em: ${new Date().toLocaleString("pt-BR")}`,
  ].join("\n");
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "vitali-backup-codes.txt";
  a.click();
  URL.revokeObjectURL(url);
}

export default function SecurityPage() {
  const [mfaActive, setMfaActive] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [step, setStep] = useState<Step>("idle");
  const [setupData, setSetupData] = useState<SetupData | null>(null);
  const [otpCode, setOtpCode] = useState("");
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [downloaded, setDownloaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  useEffect(() => {
    apiFetch("/auth/mfa/status/")
      .then((data: MFAStatus) => setMfaActive(data.is_active))
      .catch(() => setMfaActive(false))
      .finally(() => setLoading(false));
  }, []);

  const startSetup = async () => {
    setError(null);
    setWorking(true);
    try {
      const data: SetupData = await apiFetch("/auth/mfa/setup/", { method: "POST" });
      setSetupData(data);
      setStep("qr");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao iniciar configuração.");
    } finally {
      setWorking(false);
    }
  };

  const verifyCode = async () => {
    if (!otpCode || otpCode.length !== 6) {
      setError("Digite o código de 6 dígitos.");
      return;
    }
    setError(null);
    setWorking(true);
    try {
      const data = await apiFetch("/auth/mfa/verify/", {
        method: "POST",
        body: JSON.stringify({ code: otpCode }),
      });
      setBackupCodes(data.backup_codes ?? []);
      setStep("backup");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Código inválido.");
    } finally {
      setWorking(false);
    }
  };

  const handleDownload = () => {
    downloadBackupCodes(backupCodes);
    setDownloaded(true);
  };

  const handleFinish = () => {
    if (!downloaded) {
      if (
        !confirm(
          "Você ainda não baixou seus códigos de backup. Se perder acesso ao app autenticador, não poderá fazer login. Fechar mesmo assim?"
        )
      ) {
        return;
      }
    }
    setMfaActive(true);
    setStep("idle");
    setSetupData(null);
    setOtpCode("");
    setBackupCodes([]);
    setDownloaded(false);
  };

  if (loading) {
    return (
      <PageShell variant="operational">
        <div className="flex items-center justify-center py-16">
          <Loader2 className="animate-spin text-slate-500" size={20} />
        </div>
      </PageShell>
    );
  }

  return (
    <PageShell variant="operational">
      <div className="max-w-2xl space-y-5">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Segurança da Conta</h1>
          <p className="text-sm text-slate-500 mt-1">
            Gerencie a autenticação de dois fatores (MFA).
          </p>
        </div>

        <section className="rounded-lg border border-slate-200 bg-white">
          <div className="border-b border-slate-100 px-4 py-3 flex items-center justify-between flex-wrap gap-3">
            <h2 className="text-base font-semibold text-slate-900">
              Autenticação de Dois Fatores
            </h2>
            <StatusBadge meta={getMfaStatusMeta(mfaActive)} />
          </div>
          <div className="p-4 space-y-4">
            <div className="flex items-center gap-3">
              {mfaActive ? (
                <div className="w-10 h-10 rounded-lg bg-green-50 flex items-center justify-center border border-green-200">
                  <ShieldCheck className="text-green-700" size={20} />
                </div>
              ) : (
                <div className="w-10 h-10 rounded-lg bg-slate-50 flex items-center justify-center border border-slate-200">
                  <ShieldOff className="text-slate-500" size={20} />
                </div>
              )}
              <p className="text-sm text-slate-700">
                {mfaActive
                  ? "MFA ativo — sua conta está protegida."
                  : "MFA inativo — recomendamos ativar para maior segurança."}
              </p>
            </div>

            {!mfaActive && step === "idle" && (
              <button
                onClick={startSetup}
                disabled={working}
                className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-semibold px-4 py-2 rounded-lg transition"
              >
                {working ? (
                  <Loader2 size={15} className="animate-spin" />
                ) : (
                  <QrCode size={15} />
                )}
                Configurar Autenticação de Dois Fatores
              </button>
            )}
          </div>
        </section>

        {step !== "idle" && (
          <section className="rounded-lg border border-slate-200 bg-white">
            <div className="border-b border-slate-100 px-4 py-3">
              <div className="flex items-center gap-2 text-xs text-slate-500">
                {["Escanear QR", "Verificar Código", "Códigos de Backup"].map((label, i) => {
                  const stepIdx = { qr: 0, verify: 1, backup: 2 }[step] ?? 0;
                  const isActive = i === stepIdx;
                  const isDone = i < stepIdx;
                  return (
                    <span
                      key={i}
                      className={`flex items-center gap-1 ${
                        isActive
                          ? "text-blue-700 font-semibold"
                          : isDone
                            ? "text-green-700"
                            : "text-slate-400"
                      }`}
                    >
                      {i > 0 && <span className="text-slate-300 mx-1">›</span>}
                      {isDone ? "✓ " : `${i + 1}. `}
                      {label}
                    </span>
                  );
                })}
              </div>
            </div>
            <div className="p-4 space-y-4">
              {error && (
                <SectionState title="Erro ao configurar MFA" detail={error} tone="critical" />
              )}

              {step === "qr" && setupData && (
                <div className="space-y-4">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-900">
                      Passo 1 de 3 — Escaneie o QR Code
                    </h3>
                    <p className="text-xs text-slate-500 mt-1">
                      Abra seu app autenticador (Google Authenticator, Authy, etc.) e escaneie o
                      código abaixo.
                    </p>
                  </div>
                  <div className="flex justify-center">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={`data:image/png;base64,${setupData.qr_image_base64}`}
                      alt="QR Code para configurar MFA"
                      className="w-48 h-48 rounded-lg border border-slate-200"
                    />
                  </div>
                  <div className="text-center">
                    <p className="text-xs text-slate-500 mb-1">Ou copie o código manualmente:</p>
                    <code className="text-xs bg-slate-50 border border-slate-200 px-3 py-1.5 rounded font-mono break-all select-all">
                      {setupData.secret}
                    </code>
                  </div>
                  <button
                    onClick={() => {
                      setStep("verify");
                      setError(null);
                    }}
                    className="w-full bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold py-2 rounded-lg transition"
                  >
                    Continuar →
                  </button>
                </div>
              )}

              {step === "verify" && (
                <div className="space-y-4">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-900">
                      Passo 2 de 3 — Verificar Código
                    </h3>
                    <p className="text-xs text-slate-500 mt-1">
                      Digite o código de 6 dígitos exibido no seu app autenticador. O código muda
                      a cada 30 segundos.
                    </p>
                  </div>
                  <input
                    type="text"
                    inputMode="numeric"
                    value={otpCode}
                    onChange={(e) => {
                      const val = e.target.value.replace(/\D/g, "").slice(0, 6);
                      setOtpCode(val);
                      setError(null);
                      if (val.length === 6) verifyCode();
                    }}
                    placeholder="000000"
                    maxLength={6}
                    autoFocus
                    className="w-full rounded-lg border border-slate-200 px-4 py-3 text-center text-2xl font-mono tracking-widest outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <button
                    onClick={verifyCode}
                    disabled={working || otpCode.length !== 6}
                    className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-semibold py-2 rounded-lg transition flex items-center justify-center gap-2"
                  >
                    {working && <Loader2 size={15} className="animate-spin" />}
                    Verificar
                  </button>
                </div>
              )}

              {step === "backup" && (
                <div className="space-y-4">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-900">
                      Passo 3 de 3 — Códigos de Backup
                    </h3>
                    <p className="text-xs text-slate-500 mt-1">
                      Guarde estes códigos em local seguro. Cada código pode ser usado apenas uma
                      vez para acessar sua conta se perder o app autenticador.
                    </p>
                  </div>
                  <div className="grid grid-cols-2 gap-2 bg-slate-50 rounded-lg p-4 border border-slate-200">
                    {backupCodes.map((code, i) => (
                      <code
                        key={i}
                        className="text-sm font-mono text-slate-700 text-center py-1"
                      >
                        {code}
                      </code>
                    ))}
                  </div>
                  <button
                    onClick={handleDownload}
                    className={`w-full flex items-center justify-center gap-2 text-sm font-semibold py-2 rounded-lg transition ${
                      downloaded
                        ? "bg-green-50 text-green-800 border border-green-200"
                        : "bg-blue-600 hover:bg-blue-700 text-white"
                    }`}
                  >
                    <Download size={15} />
                    {downloaded ? "✓ Baixado" : "Baixar Códigos como TXT"}
                  </button>
                  <button
                    onClick={handleFinish}
                    className="w-full text-sm text-slate-600 hover:text-slate-900 py-2 transition"
                  >
                    {downloaded ? "Concluir →" : "Fechar sem baixar"}
                  </button>
                </div>
              )}
            </div>
          </section>
        )}
      </div>
    </PageShell>
  );
}
