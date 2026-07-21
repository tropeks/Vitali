"use client";

import { Suspense, useState, useRef, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2, ShieldCheck, AlertCircle } from "lucide-react";

function MFALoginContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = searchParams.get("next") ?? "/dashboard";
  const [digits, setDigits] = useState<string[]>(Array(6).fill(""));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [useBackup, setUseBackup] = useState(false);
  const [backupCode, setBackupCode] = useState("");
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    inputRefs.current[0]?.focus();
  }, []);

  const getToken = (): string | null => {
    if (typeof window === "undefined") return null;
    return (
      document.cookie
        .split("; ")
        .find((c) => c.startsWith("access_token_js="))
        ?.split("=")[1] ?? null
    );
  };

  const submitMfa = async (code: string, isBackup = false) => {
    setSubmitting(true);
    setError(null);
    try {
      const token = getToken();
      const body = isBackup ? { backup_code: code } : { code };
      const res = await fetch("/api/v1/auth/mfa/login/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error ?? "Código inválido.");
        setDigits(Array(6).fill(""));
        setTimeout(() => inputRefs.current[0]?.focus(), 50);
        return;
      }
      // Update cookies with new mfa_verified tokens via the login route
      await fetch("/api/auth/mfa-complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ access: data.access, refresh: data.refresh }),
      });
      router.push(nextPath);
      router.refresh();
    } catch {
      setError("Erro ao verificar. Tente novamente.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDigitChange = (index: number, val: string) => {
    const char = val.replace(/\D/g, "").slice(-1);
    const newDigits = [...digits];
    newDigits[index] = char;
    setDigits(newDigits);

    if (char && index < 5) {
      inputRefs.current[index + 1]?.focus();
    }

    // Auto-submit on 6th digit
    if (char && index === 5) {
      const code = [...newDigits.slice(0, 5), char].join("");
      if (code.length === 6) {
        submitMfa(code);
      }
    }
  };

  const handleDigitKeyDown = (index: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Backspace" && !digits[index] && index > 0) {
      inputRefs.current[index - 1]?.focus();
    }
  };

  const handleDigitPaste = (e: React.ClipboardEvent) => {
    const pasted = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, 6);
    if (pasted.length === 6) {
      e.preventDefault();
      const newDigits = pasted.split("");
      setDigits(newDigits);
      submitMfa(pasted);
    }
  };

  const handleBackupSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (backupCode.trim()) submitMfa(backupCode.trim(), true);
  };

  return (
    <div className="min-h-screen bg-neu-app flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-b from-neu-brand to-neu-brandDeep shadow-neu-btn-primary border-t border-neu-brandEdge mb-4">
            <ShieldCheck className="text-white" size={28} />
          </div>
          <h1 className="text-2xl font-bold text-neu-ink">Autenticação de Dois Fatores</h1>
          <p className="text-neu-inkSoft text-sm mt-1">Digite o código gerado pelo seu app autenticador</p>
        </div>

        <div className="bg-neu-outer border border-white rounded-2xl p-8 shadow-neu-modal">
          {!useBackup ? (
            <>
              <p className="text-neu-inkSoft text-sm text-center mb-6">
                O código muda a cada 30 segundos
              </p>

              {error && (
                <div className="mb-4 p-3 bg-neu-danger/10 border border-neu-danger/20 rounded-lg flex items-center gap-2">
                  <AlertCircle className="text-neu-danger shrink-0" size={16} />
                  <p className="text-neu-danger text-xs font-medium">{error}</p>
                </div>
              )}

              {/* 6-digit OTP input */}
              <div
                className="flex gap-2 justify-center mb-6"
                onPaste={handleDigitPaste}
              >
                {digits.map((digit, i) => (
                  <input
                    key={i}
                    ref={el => { inputRefs.current[i] = el; }}
                    type="text"
                    inputMode="numeric"
                    maxLength={1}
                    value={digit}
                    onChange={e => handleDigitChange(i, e.target.value)}
                    onKeyDown={e => handleDigitKeyDown(i, e)}
                    disabled={submitting}
                    aria-label={`Dígito ${i + 1} do código TOTP`}
                    className="w-11 h-14 text-center text-xl font-mono font-bold text-neu-ink bg-neu-input border-transparent rounded-lg shadow-neu-inset focus:outline-none focus:bg-white focus:ring-2 focus:ring-neu-brand/50 disabled:opacity-50 transition"
                  />
                ))}
              </div>

              {submitting && (
                <div className="flex justify-center mb-4">
                  <Loader2 size={20} className="animate-spin text-neu-brand" />
                </div>
              )}

              <button
                type="button"
                onClick={() => { setUseBackup(true); setError(null); }}
                className="w-full text-center text-xs font-bold text-neu-inkSoft hover:text-neu-ink transition mt-2"
              >
                Usar código de backup
              </button>
            </>
          ) : (
            <>
              <p className="text-neu-inkSoft text-sm text-center mb-6">
                Digite um dos seus códigos de backup de 8 caracteres
              </p>

              {error && (
                <div className="mb-4 p-3 bg-neu-danger/10 border border-neu-danger/20 rounded-lg flex items-center gap-2">
                  <AlertCircle className="text-neu-danger shrink-0" size={16} />
                  <p className="text-neu-danger text-xs font-medium">{error}</p>
                </div>
              )}

              <form onSubmit={handleBackupSubmit} className="space-y-4">
                <input
                  type="text"
                  value={backupCode}
                  onChange={e => setBackupCode(e.target.value)}
                  placeholder="XXXX-XXXX"
                  autoFocus
                  className="w-full px-4 py-2.5 bg-neu-input border-transparent rounded-md text-sm font-mono tracking-widest text-center shadow-neu-inset focus:outline-none focus:bg-white focus:ring-2 focus:ring-neu-brand/50 transition-all text-neu-ink placeholder-neu-inkMuted"
                />
                <button
                  type="submit"
                  disabled={submitting || !backupCode.trim()}
                  className="w-full neu-btn-primary disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                >
                  {submitting ? <Loader2 size={16} className="animate-spin" /> : null}
                  Verificar Código de Backup
                </button>
              </form>

              <button
                type="button"
                onClick={() => { setUseBackup(false); setError(null); setBackupCode(""); }}
                className="w-full text-center text-xs font-bold text-neu-inkSoft hover:text-neu-ink transition mt-4"
              >
                ← Usar código TOTP
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function MFALoginPage() {
  return (
    <Suspense>
      <MFALoginContent />
    </Suspense>
  );
}
