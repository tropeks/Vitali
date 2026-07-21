'use client';

import { ScanLine } from 'lucide-react';

import { ImagingPanel } from '@/components/imaging/ImagingPanel';
import { ModuleGate } from '@/components/layout/ModuleGate';

export default function ImagingWorkspacePage() {
  return (
    <ModuleGate module="imaging">
      <main className="mx-auto w-full max-w-[1600px] space-y-5 p-4 md:p-6">
        <header className="rounded-2xl border border-white/70 bg-neu-surface p-5 shadow-neu-raised">
          <div className="flex items-center gap-3">
            <span className="rounded-xl bg-blue-50 p-2.5 text-blue-700 shadow-neu-inset">
              <ScanLine size={24} />
            </span>
            <div>
              <h1 className="text-2xl font-bold text-neu-ink">Vitali Imagem</h1>
              <p className="text-sm text-neu-inkMuted">
                Exames e estudos DICOM visualizados com segurança, sem sair do Vitali.
              </p>
            </div>
          </div>
        </header>

        <section className="rounded-2xl border border-white/70 bg-neu-surface p-4 shadow-neu-raised md:p-5">
          <ImagingPanel />
        </section>
      </main>
    </ModuleGate>
  );
}
