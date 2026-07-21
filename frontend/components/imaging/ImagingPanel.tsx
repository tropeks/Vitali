'use client';

import { useCallback, useEffect, useState } from 'react';
import { ExternalLink, ImageOff, ScanLine } from 'lucide-react';
import { getAccessToken } from '@/lib/auth';

// Base URL of the OHIF viewer served by Orthanc. Behind the bundled nginx it is
// same-origin at /ohif/ (see docker/nginx/nginx.conf); in a split dev setup point
// NEXT_PUBLIC_OHIF_VIEWER_URL at the Orthanc host, e.g. http://localhost:8042/ohif.
const OHIF_BASE = (process.env.NEXT_PUBLIC_OHIF_VIEWER_URL ?? '/ohif').replace(/\/$/, '');

interface DicomStudy {
  id: string;
  study_instance_uid: string;
  accession_number: string;
  modality: string;
  modality_display: string;
  body_part_examined: string;
  description: string;
  study_date: string | null;
  number_of_series: number;
  number_of_instances: number;
  orthanc_study_id: string;
  has_pixel_data: boolean;
}

function viewerUrl(study: DicomStudy): string {
  return `${OHIF_BASE}/viewer?StudyInstanceUIDs=${encodeURIComponent(study.study_instance_uid)}`;
}

/**
 * ImagingPanel — lists the encounter's DICOM studies and embeds the OHIF viewer
 * for any study whose pixel data has landed in Orthanc (orthanc_study_id set by
 * the webhook/poller). Gated by the `imaging` module: a 403 from the API hides
 * the panel entirely, matching the FaturamentoCard pattern.
 */
interface ImagingPanelProps {
  encounterId?: string;
  labOrderId?: string;
  labOrderItemId?: string;
}

export function ImagingPanel({ encounterId, labOrderId, labOrderItemId }: ImagingPanelProps) {
  const [studies, setStudies] = useState<DicomStudy[]>([]);
  const [loading, setLoading] = useState(true);
  const [hidden, setHidden] = useState(false);
  const [activeUid, setActiveUid] = useState<string | null>(null);

  const load = useCallback(() => {
    const token = getAccessToken();
    if (!token) {
      setLoading(false);
      return;
    }
    setLoading(true);
    const params = new URLSearchParams();
    if (encounterId) params.set('encounter', encounterId);
    if (labOrderId) params.set('lab_order', labOrderId);
    if (labOrderItemId) params.set('lab_order_item', labOrderItemId);
    fetch(`/api/v1/imaging/studies/?${params.toString()}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => {
        if (r.status === 403) {
          setHidden(true);
          return null;
        }
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json();
      })
      .then((data) => {
        if (!data) return;
        const list: DicomStudy[] = Array.isArray(data) ? data : (data.results ?? []);
        setStudies(list);
        // Auto-open the first viewable study so the clinician sees imagery immediately.
        const firstViewable = list.find((s) => s.has_pixel_data);
        setActiveUid(firstViewable ? firstViewable.study_instance_uid : null);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [encounterId, labOrderId, labOrderItemId]);

  useEffect(() => {
    load();
  }, [load]);

  if (hidden) return null;

  if (loading) {
    return <p className="text-sm text-slate-400">Carregando estudos de imagem...</p>;
  }

  if (studies.length === 0) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-500">
        <ImageOff size={16} className="text-slate-400" />
        Nenhum estudo de imagem (DICOM) encontrado.
      </div>
    );
  }

  const activeStudy = studies.find((s) => s.study_instance_uid === activeUid) ?? null;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="block text-[11px] font-bold uppercase tracking-wide text-[#57606A]">
          Estudos de imagem (DICOM)
        </h3>
        <button
          type="button"
          onClick={load}
          className="text-xs font-medium text-blue-600 hover:text-blue-800"
        >
          Atualizar
        </button>
      </div>

      <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
        {studies.map((study) => {
          const selected = study.study_instance_uid === activeUid;
          return (
            <li
              key={study.id}
              className={`flex flex-wrap items-center justify-between gap-2 px-3 py-2 ${
                selected ? 'bg-blue-50' : ''
              }`}
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                  <ScanLine size={15} className="text-blue-600" />
                  <span className="font-mono">{study.modality}</span>
                  <span className="truncate">
                    {study.body_part_examined || study.description || study.modality_display}
                  </span>
                </div>
                <p className="mt-0.5 text-xs text-slate-500">
                  {study.study_date
                    ? new Date(study.study_date).toLocaleDateString('pt-BR')
                    : 'Sem data'}
                  {' · '}
                  {study.number_of_series} série(s) · {study.number_of_instances} imagem(ns)
                </p>
              </div>

              {study.has_pixel_data ? (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setActiveUid(study.study_instance_uid)}
                    className="rounded-lg border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-100"
                  >
                    {selected ? 'Visualizando' : 'Abrir'}
                  </button>
                  <a
                    href={viewerUrl(study)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-800"
                  >
                    <ExternalLink size={13} />
                    Nova aba
                  </a>
                </div>
              ) : (
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
                  Aguardando PACS
                </span>
              )}
            </li>
          );
        })}
      </ul>

      {activeStudy && (
        <div className="overflow-hidden rounded-xl border border-slate-300 bg-black">
          <iframe
            key={activeStudy.study_instance_uid}
            title={`OHIF Viewer — ${activeStudy.modality} ${activeStudy.body_part_examined}`}
            src={viewerUrl(activeStudy)}
            className="h-[70vh] w-full border-0"
            allow="fullscreen"
          />
        </div>
      )}
    </div>
  );
}
