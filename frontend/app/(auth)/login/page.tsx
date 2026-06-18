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
    <div className="min-h-screen bg-[#DFE5EB] flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-b from-[#0066A1] to-[#005282] shadow-[0_3px_10px_rgba(0,102,161,0.3)] border-t border-[#3385b5] mb-4">
            <span className="text-white font-bold text-2xl">V</span>
          </div>
          <h1 className="text-2xl font-bold text-[#1f2937]">Vitali</h1>
          <p className="text-[#57606A] text-sm mt-1">Plataforma Hospitalar</p>
        </div>

        {/* Card */}
        <div className="bg-[#EBF0F5] border border-white rounded-2xl p-8 shadow-[0_20px_50px_rgba(0,0,0,0.2),_inset_0_2px_4px_rgba(255,255,255,0.8)]">
          <h2 className="text-lg font-semibold text-[#1f2937] mb-6">Acesse sua conta</h2>

          {/* Lockout banner */}
          {lockoutSeconds !== null && (
            <div className="mb-4 p-3 bg-[#CF222E]/10 border border-[#CF222E]/20 rounded-lg flex items-start gap-2">
              <AlertCircle className="text-[#CF222E] mt-0.5 shrink-0" size={16} />
              <p className="text-[#CF222E] text-xs font-medium">
                Conta bloqueada temporariamente.{" "}
                <span className="font-bold">Tente novamente em {Math.ceil(lockoutSeconds / 60)} min.</span>
              </p>
            </div>
          )}

          {/* Generic error */}
          {apiError && !lockoutSeconds && (
            <div className="mb-4 p-3 bg-[#CF222E]/10 border border-[#CF222E]/20 rounded-lg flex items-start gap-2">
              <AlertCircle className="text-[#CF222E] mt-0.5 shrink-0" size={16} />
              <p className="text-[#CF222E] text-xs font-medium">{apiError}</p>
            </div>
          )}

          <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
            {/* Email */}
            <div>
              <label className="block text-[11px] font-bold text-[#57606A] mb-1.5 uppercase tracking-wide">
                E-mail
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8C959F]" size={16} />
                <input
                  {...register("email")}
                  type="email"
                  autoComplete="email"
                  placeholder="seu@email.com"
                  className="w-full pl-9 pr-4 py-1.5 bg-[#E8EDF2] border-transparent rounded-md text-xs shadow-[inset_0_2px_4px_rgba(0,0,0,0.06)] focus:outline-none focus:bg-white focus:ring-2 focus:ring-[#0066A1]/50 transition-all h-8 text-[#24292F] placeholder-[#8C959F]"
                />
              </div>
              {errors.email && (
                <p className="mt-1 text-xs text-[#CF222E] font-medium">{errors.email.message}</p>
              )}
            </div>

            {/* Password */}
            <div>
              <label className="block text-[11px] font-bold text-[#57606A] mb-1.5 uppercase tracking-wide">
                Senha
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8C959F]" size={16} />
                <input
                  {...register("password")}
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  placeholder="••••••••"
                  className="w-full pl-9 pr-10 py-1.5 bg-[#E8EDF2] border-transparent rounded-md text-xs shadow-[inset_0_2px_4px_rgba(0,0,0,0.06)] focus:outline-none focus:bg-white focus:ring-2 focus:ring-[#0066A1]/50 transition-all h-8 text-[#24292F] placeholder-[#8C959F]"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[#8C959F] hover:text-[#57606A]"
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              {errors.password && (
                <p className="mt-1 text-xs text-[#CF222E] font-medium">{errors.password.message}</p>
              )}
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={isSubmitting || lockoutSeconds !== null}
              className="w-full px-6 py-2 text-xs font-bold text-white bg-gradient-to-b from-[#0066A1] to-[#005282] rounded-lg border-t border-[#3385b5] shadow-[0_3px_10px_rgba(0,102,161,0.3)] hover:shadow-[0_5px_15px_rgba(0,102,161,0.4)] transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 mt-4"
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

        <p className="text-center text-[#8C959F] text-xs mt-6">
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
