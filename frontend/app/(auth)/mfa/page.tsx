"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Loader2, ShieldCheck, AlertCircle } from "lucide-react";

const DJANGO_API =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function MFALoginPage() {
  const router = useRouter();
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
      router.push("/dashboard");
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
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-blue-950 to-slate-900 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-blue-600 mb-4">
            <ShieldCheck className="text-white" size={28} />
          </div>
          <h1 className="text-2xl font-bold text-white">Autenticação de Dois Fatores</h1>
          <p className="text-slate-400 text-sm mt-1">Digite o código gerado pelo seu app autenticador</p>
        </div>

        <div className="bg-white/5 backdrop-blur border border-white/10 rounded-2xl p-8 shadow-2xl">
          {!useBackup ? (
            <>
              <p className="text-slate-300 text-sm text-center mb-6">
                O código muda a cada 30 segundos
              </p>

              {error && (
                <div className="mb-4 p-3 bg-red-900/40 border border-red-500/50 rounded-lg flex items-center gap-2">
                  <AlertCircle className="text-red-400 shrink-0" size={16} />
                  <p className="text-red-300 text-sm">{error}</p>
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
                    className="w-11 h-14 text-center text-xl font-mono font-bold text-white bg-white/10 border border-white/20 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50 transition"
                  />
                ))}
              </div>

              {submitting && (
                <div className="flex justify-center mb-4">
                  <Loader2 size={20} className="animate-spin text-blue-400" />
                </div>
              )}

              <button
                type="button"
                onClick={() => { setUseBackup(true); setError(null); }}
                className="w-full text-center text-sm text-slate-400 hover:text-slate-200 transition mt-2"
              >
                Usar código de backup
              </button>
            </>
          ) : (
            <>
              <p className="text-slate-300 text-sm text-center mb-6">
                Digite um dos seus códigos de backup de 8 caracteres
              </p>

              {error && (
                <div className="mb-4 p-3 bg-red-900/40 border border-red-500/50 rounded-lg flex items-center gap-2">
                  <AlertCircle className="text-red-400 shrink-0" size={16} />
                  <p className="text-red-300 text-sm">{error}</p>
                </div>
              )}

              <form onSubmit={handleBackupSubmit} className="space-y-4">
                <input
                  type="text"
                  value={backupCode}
                  onChange={e => setBackupCode(e.target.value)}
                  placeholder="XXXX-XXXX"
                  autoFocus
                  className="w-full bg-white/5 border border-white/10 text-white placeholder-slate-500 rounded-lg py-2.5 px-4 text-sm font-mono tracking-widest text-center focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <button
                  type="submit"
                  disabled={submitting || !backupCode.trim()}
                  className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-blue-800 disabled:cursor-not-allowed text-white font-medium rounded-lg py-2.5 text-sm transition flex items-center justify-center gap-2"
                >
                  {submitting ? <Loader2 size={16} className="animate-spin" /> : null}
                  Verificar Código de Backup
                </button>
              </form>

              <button
                type="button"
                onClick={() => { setUseBackup(false); setError(null); setBackupCode(""); }}
                className="w-full text-center text-sm text-slate-400 hover:text-slate-200 transition mt-4"
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
