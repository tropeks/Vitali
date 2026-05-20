"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import Link from "next/link";
import { AlertCircle, CheckCircle, Loader2, Mail } from "lucide-react";

import { portalApi, PortalUnauthorizedError } from "@/lib/portal-api";

function ActivateContent() {
  const router = useRouter();
  const search = useSearchParams();
  const [token, setToken] = useState(search?.get("token") ?? "");
  const [state, setState] = useState<"idle" | "submitting" | "success" | "error">(
    "idle",
  );
  const [error, setError] = useState<string | null>(null);

  // If the URL carries ?token=..., prefill but don't auto-submit — the user
  // confirms with a click for clarity.
  useEffect(() => {
    const urlToken = search?.get("token");
    if (urlToken) setToken(urlToken);
  }, [search]);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || state === "submitting") return;
    setState("submitting");
    setError(null);
    try {
      const access = await portalApi.activateInvite(token.trim());
      if (access.status !== "active") {
        setError("Convite consumido, mas o acesso ainda não está ativo. Contate a clínica.");
        setState("error");
        return;
      }
      setState("success");
      setTimeout(() => router.push("/portal"), 1200);
    } catch (err) {
      if (err instanceof PortalUnauthorizedError) {
        // The activation endpoint requires the user to be logged in
        // (the backend verifies token.user == request.user).
        router.push(`/portal/login?next=/portal/activate?token=${encodeURIComponent(token)}`);
        return;
      }
      setError("Token inválido ou expirado. Solicite um novo convite na clínica.");
      setState("error");
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-12">
      <div className="w-full max-w-md">
        <div className="mb-6 text-center">
          <div className="mx-auto inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-600 text-white">
            <Mail size={26} />
          </div>
          <h1 className="mt-4 text-2xl font-semibold text-slate-900">Ativar convite</h1>
          <p className="mt-1 text-sm text-slate-600">
            Cole o código que você recebeu por e-mail ou WhatsApp.
          </p>
        </div>

        <form
          onSubmit={onSubmit}
          className="space-y-4 rounded-lg border border-slate-200 bg-white p-6"
        >
          <div>
            <label
              htmlFor="token"
              className="text-xs font-semibold uppercase tracking-wide text-slate-500"
            >
              Código do convite
            </label>
            <input
              id="token"
              type="text"
              required
              value={token}
              onChange={(e) => setToken(e.target.value)}
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 font-mono text-sm outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="ex: 7f3...xJ_"
            />
          </div>

          {state === "success" && (
            <div className="flex items-start gap-2 rounded-lg border border-green-200 bg-green-50 px-3 py-2">
              <CheckCircle size={16} className="mt-0.5 shrink-0 text-green-700" />
              <p className="text-sm text-green-800">
                Convite ativado. Redirecionando para o seu portal…
              </p>
            </div>
          )}

          {state === "error" && error && (
            <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2">
              <AlertCircle size={16} className="mt-0.5 shrink-0 text-red-600" />
              <p className="text-sm text-red-800">{error}</p>
            </div>
          )}

          <button
            type="submit"
            disabled={!token || state === "submitting" || state === "success"}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {state === "submitting" && <Loader2 size={16} className="animate-spin" />}
            Ativar e entrar no portal
          </button>

          <p className="pt-2 text-center text-xs text-slate-500">
            Já tem conta?{" "}
            <Link
              href="/portal/login"
              className="font-semibold text-blue-700 hover:underline"
            >
              Fazer login
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}

export default function PortalActivatePage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center text-sm text-slate-500">
          Carregando…
        </div>
      }
    >
      <ActivateContent />
    </Suspense>
  );
}
