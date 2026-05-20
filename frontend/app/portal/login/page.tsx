"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Heart, Eye, EyeOff, AlertCircle, Loader2 } from "lucide-react";

interface LoginError {
  code?: string;
  message?: string;
}

export default function PortalLoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<LoginError | null>(null);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!email || !password || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const resp = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.ok) {
        if (data?.mfa_required) {
          // Portal accounts shouldn't require MFA, but if backend asks
          // we route through the same MFA page.
          router.push("/mfa?next=/portal");
          return;
        }
        // Use a hard navigation so the protected layout re-reads the
        // freshly-set cookie on a clean server-render.
        window.location.assign("/portal");
        return;
      }
      setError(data?.error ?? { message: `Erro ${resp.status}` });
    } catch {
      setError({ message: "Não foi possível conectar ao servidor." });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-12">
      <div className="w-full max-w-md">
        <div className="mb-6 text-center">
          <div className="mx-auto inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-600 text-white">
            <Heart size={26} fill="currentColor" />
          </div>
          <h1 className="mt-4 text-2xl font-semibold text-slate-900">
            Portal do Paciente
          </h1>
          <p className="mt-1 text-sm text-slate-600">Acesse seu acompanhamento na Vitali.</p>
        </div>

        <form
          onSubmit={onSubmit}
          className="space-y-4 rounded-lg border border-slate-200 bg-white p-6"
        >
          <div>
            <label
              htmlFor="email"
              className="text-xs font-semibold uppercase tracking-wide text-slate-500"
            >
              E-mail
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="voce@email.com"
            />
          </div>

          <div>
            <label
              htmlFor="password"
              className="text-xs font-semibold uppercase tracking-wide text-slate-500"
            >
              Senha
            </label>
            <div className="relative mt-1">
              <input
                id="password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-lg border border-slate-200 px-3 py-2 pr-10 text-sm outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="••••••••"
              />
              <button
                type="button"
                onClick={() => setShowPassword((s) => !s)}
                className="absolute inset-y-0 right-0 flex items-center px-3 text-slate-400 hover:text-slate-700"
                aria-label={showPassword ? "Esconder senha" : "Mostrar senha"}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          {error && (
            <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2">
              <AlertCircle size={16} className="mt-0.5 shrink-0 text-red-600" />
              <p className="text-sm text-red-800">
                {error.message ?? "Erro ao fazer login."}
              </p>
            </div>
          )}

          <button
            type="submit"
            disabled={submitting || !email || !password}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting && <Loader2 size={16} className="animate-spin" />}
            Entrar
          </button>

          <p className="pt-2 text-center text-xs text-slate-500">
            Recebeu um convite por e-mail ou WhatsApp?{" "}
            <Link
              href="/portal/activate"
              className="font-semibold text-blue-700 hover:underline"
            >
              Ativar convite
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
