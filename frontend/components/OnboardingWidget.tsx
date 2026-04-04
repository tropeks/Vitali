'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { getAccessToken } from '@/lib/auth';
import { CheckCircle, Circle } from 'lucide-react';

interface OnboardingStep {
  id: string;
  label: string;
  done: boolean;
  action_url: string;
}

interface OnboardingData {
  steps: OnboardingStep[];
}

export default function OnboardingWidget() {
  const router = useRouter();
  const [data, setData] = useState<OnboardingData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const token = getAccessToken();
      if (!token) {
        setLoading(false);
        return;
      }
      try {
        const res = await fetch('/api/v1/onboarding/', {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) return;
        const json = await res.json();
        setData(json);
      } catch {
        // silent — widget is optional
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  // Don't render while loading or if all steps are done
  if (loading || !data) return null;
  if (!data.steps.some((s) => !s.done)) return null;

  const total = data.steps.length;
  const done = data.steps.filter((s) => s.done).length;
  const progress = total > 0 ? Math.round((done / total) * 100) : 0;

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-4">
      {/* Header + progress bar */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-900">Configuração inicial</h2>
          <span className="text-xs text-slate-500 font-medium">
            {done} de {total} passos concluídos
          </span>
        </div>
        <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-600 rounded-full transition-all duration-500"
            style={{ width: `${progress}%` }}
            role="progressbar"
            aria-valuenow={done}
            aria-valuemin={0}
            aria-valuemax={total}
          />
        </div>
      </div>

      {/* Step list */}
      <ul className="space-y-2">
        {data.steps.map((step) => (
          <li
            key={step.id}
            className="flex items-center justify-between gap-4 py-2 border-b border-slate-50 last:border-b-0"
          >
            <div className="flex items-center gap-2.5 min-w-0">
              {step.done ? (
                <CheckCircle size={18} className="text-green-500 shrink-0" />
              ) : (
                <Circle size={18} className="text-slate-300 shrink-0" />
              )}
              <span
                className={`text-sm truncate ${
                  step.done ? 'text-slate-400 line-through' : 'text-slate-800 font-medium'
                }`}
              >
                {step.label}
              </span>
            </div>
            {!step.done && (
              <button
                onClick={() => router.push(step.action_url)}
                className="shrink-0 text-xs font-medium text-blue-600 hover:underline whitespace-nowrap"
              >
                Fazer agora →
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
