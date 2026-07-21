"use client";

import { ExternalLink, FileText, ImageOff, ScanLine } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  portalApi,
  PortalApiError,
  type PortalImagingStudy,
} from "@/lib/portal-api";

function defaultViewerUrl(study: PortalImagingStudy) {
  return `/visualizador/viewer?StudyInstanceUIDs=${encodeURIComponent(study.study_instance_uid)}`;
}

function studyLabel(study: PortalImagingStudy) {
  return study.description || study.body_part_examined || study.modality || "Exame de imagem";
}

export default function PortalImagingPage() {
  const [studies, setStudies] = useState<PortalImagingStudy[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    portalApi
      .getMyImagingStudies()
      .then((items) => {
        setStudies(items);
        // Do not fetch pixels or create the viewer until the patient asks for it.
        setActiveId(null);
      })
      .catch((err) => {
        if (err instanceof PortalApiError && [401, 403].includes(err.status)) {
          window.location.assign(err.status === 401 ? "/portal/login" : "/portal/activate");
        } else {
          setError("Não foi possível carregar seus exames de imagem.");
        }
      })
      .finally(() => setLoading(false));
  }, []);

  const activeStudy = useMemo(
    () => studies.find((study) => study.id === activeId) ?? null,
    [activeId, studies],
  );

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-neu-ink">Meus exames de imagem</h1>
        <p className="mt-1 text-sm text-neu-inkSoft">
          Visualize imagens e laudos liberados pela sua clínica com segurança.
        </p>
      </div>

      {error && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <div role="status" className="neu-panel p-8 text-center text-sm text-neu-inkSoft">
          Carregando exames…
        </div>
      ) : studies.length > 0 ? (
        <div className="space-y-4">
          <ul className="grid gap-3 sm:grid-cols-2">
            {studies.map((study) => {
              const selected = study.id === activeId;
              return (
                <li key={study.id}>
                  <article className={`neu-panel h-full p-4 ${selected ? "ring-2 ring-blue-500" : ""}`}>
                    <div className="flex items-start gap-3">
                      <span className="rounded-lg bg-blue-50 p-2 text-blue-700"><ScanLine size={20} /></span>
                      <div className="min-w-0 flex-1">
                        <h2 className="font-semibold text-neu-ink">{studyLabel(study)}</h2>
                        <p className="mt-0.5 text-xs text-neu-inkSoft">
                          {study.modality}
                          {study.study_date ? ` · ${new Date(study.study_date).toLocaleDateString("pt-BR")}` : ""}
                        </p>
                        <p className="mt-1 text-xs text-neu-inkMuted">
                          {study.series_count} série(s) · {study.instance_count} imagem(ns)
                        </p>
                      </div>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      {study.available ? (
                        <button
                          type="button"
                          onClick={() => setActiveId(study.id)}
                          className="neu-btn-primary px-3 py-2 text-sm"
                        >
                          {selected ? "Visualizando imagens" : "Ver imagens"}
                        </button>
                      ) : (
                        <span className="rounded-full bg-slate-100 px-3 py-1.5 text-xs text-slate-600">Imagens em processamento</span>
                      )}
                      {study.report_url && (
                        <a href={study.report_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
                          <FileText size={15} /> Ver laudo assinado
                        </a>
                      )}
                    </div>
                  </article>
                </li>
              );
            })}
          </ul>

          {activeStudy && (
            <section aria-label={`Imagens de ${studyLabel(activeStudy)}`} className="overflow-hidden rounded-xl border border-slate-300 bg-black">
              <div className="flex items-center justify-between bg-slate-900 px-4 py-3 text-white">
                <p className="text-sm font-medium">Visualizador Vitali · {studyLabel(activeStudy)}</p>
                <a href={activeStudy.viewer_url || defaultViewerUrl(activeStudy)} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-slate-200 hover:text-white">
                  <ExternalLink size={13} /> Ampliar
                </a>
              </div>
              <iframe
                key={activeStudy.id}
                title={`Visualizador Vitali — ${studyLabel(activeStudy)}`}
                src={activeStudy.viewer_url || defaultViewerUrl(activeStudy)}
                className="h-[70vh] w-full border-0"
                allow="fullscreen"
              />
            </section>
          )}
        </div>
      ) : !error ? (
        <div className="neu-panel p-10 text-center">
          <ImageOff className="mx-auto text-neu-inkMuted" />
          <p className="mt-3 font-medium text-neu-ink">Nenhum exame de imagem liberado</p>
          <p className="text-sm text-neu-inkSoft">Seus exames aparecerão aqui quando estiverem disponíveis.</p>
        </div>
      ) : null}
    </div>
  );
}
