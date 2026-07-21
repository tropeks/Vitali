"use client";

export const dynamic = "force-dynamic";

import { Suspense } from "react";
import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Eye, EyeOff, Loader2, Lock, Mail, AlertCircle } from "lucide-react";

const loginSchema = z.object({
  email: z.string().email("E-mail inválido"),
  password: z.string().min(1, "Senha obrigatória"),
});

type LoginForm = z.infer<typeof loginSchema>;

function getSafeNextPath(next: string | null): string {
  if (!next || !next.startsWith("/") || next.startsWith("//")) {
    return "/dashboard";
  }
  return next;
}

function LoginContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = getSafeNextPath(searchParams.get("next"));

  const [showPassword, setShowPassword] = useState(false);
  const [lockoutSeconds, setLockoutSeconds] = useState<number | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginForm>({ resolver: zodResolver(loginSchema) });

  const onSubmit = async (values: LoginForm) => {
    setApiError(null);
    setLockoutSeconds(null);

    const resp = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(values),
    });

    const data = await resp.json();

    if (resp.ok) {
      if (data?.mfa_required) {
        const nextEncoded = encodeURIComponent(nextPath);
        router.push(`/mfa?next=${nextEncoded}`);
        return;
      }
      router.push(nextPath);
      router.refresh();
      return;
    }

    const err = data?.error;
    if (err?.code === "ACCOUNT_LOCKED") {
      setLockoutSeconds(err.retry_after ?? 300);
    } else {
      setApiError(err?.message ?? "Erro ao fazer login.");
    }
  };

  return (
    <div className="min-h-screen bg-neu-app flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-b from-neu-brand to-neu-brandDeep shadow-neu-btn-primary border-t border-neu-brandEdge mb-4">
            <span className="text-white font-bold text-2xl">V</span>
          </div>
          <h1 className="text-2xl font-bold text-neu-ink">Vitali</h1>
          <p className="text-neu-inkSoft text-sm mt-1">Plataforma Hospitalar</p>
        </div>

        {/* Card */}
        <div className="bg-neu-outer border border-white rounded-2xl p-8 shadow-neu-modal">
          <h2 className="text-lg font-semibold text-neu-ink mb-6">Acesse sua conta</h2>

          {/* Lockout banner */}
          {lockoutSeconds !== null && (
            <div className="mb-4 p-3 bg-neu-danger/10 border border-neu-danger/20 rounded-lg flex items-start gap-2">
              <AlertCircle className="text-neu-danger mt-0.5 shrink-0" size={16} />
              <p className="text-neu-danger text-xs font-medium">
                Conta bloqueada temporariamente.{" "}
                <span className="font-bold">Tente novamente em {Math.ceil(lockoutSeconds / 60)} min.</span>
              </p>
            </div>
          )}

          {/* Generic error */}
          {apiError && !lockoutSeconds && (
            <div className="mb-4 p-3 bg-neu-danger/10 border border-neu-danger/20 rounded-lg flex items-start gap-2">
              <AlertCircle className="text-neu-danger mt-0.5 shrink-0" size={16} />
              <p className="text-neu-danger text-xs font-medium">{apiError}</p>
            </div>
          )}

          <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
            {/* Email */}
            <div>
              <label className="neu-label">
                E-mail
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 text-neu-inkMuted" size={16} />
                <input
                  {...register("email")}
                  type="email"
                  autoComplete="email"
                  placeholder="seu@email.com"
                  className="w-full pl-9 pr-4 py-1.5 bg-neu-input border-transparent rounded-md text-xs shadow-neu-inset focus:outline-none focus:bg-white focus:ring-2 focus:ring-neu-brand/50 transition-all h-8 text-neu-ink placeholder-neu-inkMuted"
                />
              </div>
              {errors.email && (
                <p className="mt-1 text-xs text-neu-danger font-medium">{errors.email.message}</p>
              )}
            </div>

            {/* Password */}
            <div>
              <label className="neu-label">
                Senha
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 text-neu-inkMuted" size={16} />
                <input
                  {...register("password")}
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  placeholder="••••••••"
                  className="w-full pl-9 pr-10 py-1.5 bg-neu-input border-transparent rounded-md text-xs shadow-neu-inset focus:outline-none focus:bg-white focus:ring-2 focus:ring-neu-brand/50 transition-all h-8 text-neu-ink placeholder-neu-inkMuted"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-neu-inkMuted hover:text-neu-inkSoft"
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              {errors.password && (
                <p className="mt-1 text-xs text-neu-danger font-medium">{errors.password.message}</p>
              )}
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={isSubmitting || lockoutSeconds !== null}
              className="w-full neu-btn-primary disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 mt-4"
            >
              {isSubmitting ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  Entrando…
                </>
              ) : (
                "Entrar"
              )}
            </button>
          </form>
        </div>

        <p className="text-center text-neu-inkMuted text-xs mt-6">
          Vitali © {new Date().getFullYear()} — Todos os direitos reservados
        </p>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginContent />
    </Suspense>
  );
}
