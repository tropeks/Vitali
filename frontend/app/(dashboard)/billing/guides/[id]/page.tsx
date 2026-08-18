'use client';

import { useState, useEffect } from 'react';
import { useRouter, useParams } from 'next/navigation';
import RemoteCombobox from '@/components/shared/RemoteCombobox';

const STATUS_BADGE: Record<string, string> = {
  draft: 'bg-neu-app text-neu-inkSoft',
  pending: 'bg-yellow-100 text-yellow-700',
  submitted: 'bg-blue-100 text-blue-700',
  paid: 'bg-green-100 text-green-700',
  denied: 'bg-red-100 text-red-700',
  appeal: 'bg-orange-100 text-orange-700',
};

const STATUS_LABEL: Record<string, string> = {
  draft: 'Rascunho',
  pending: 'Pendente',
  submitted: 'Enviado',
  paid: 'Pago',
  denied: 'Glosado',
  appeal: 'Recurso',
};

function fmtCurrency(val: any) {
  if (val == null) return '—';
  return Number(val).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

function Field({ label, value }: { label: string; value: any }) {
  return (
    <div>
      <dt className="text-xs font-medium text-neu-inkMuted uppercase tracking-wide">{label}</dt>
      <dd className="mt-0.5 text-sm text-neu-ink">{value ?? '—'}</dd>
    </div>
  );
}

type TipoFaturamentoOption = { value: string; label: string };

/** Espelha o que `ProfessionalSerializer` expõe e o combobox precisa. */
type ProfessionalOption = { id: string; user_name?: string | null; council_number?: string | null };

const professionalLabel = (p: ProfessionalOption) =>
  p.user_name || (p.council_number ? `Registro ${p.council_number}` : p.id);

export default function GuideDetailPage() {
  const router = useRouter();
  const params = useParams();
  const id = params.id as string;

  const [guide, setGuide] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [actionMsg, setActionMsg] = useState('');

  const [authNumber, setAuthNumber] = useState('');
  const [authDate, setAuthDate] = useState('');
  const [savingAuth, setSavingAuth] = useState(false);
  const [authError, setAuthError] = useState('');
  const [authSaved, setAuthSaved] = useState(false);
  const [tipoFaturamento, setTipoFaturamento] = useState('');
  const [tipoFaturamentoOptions, setTipoFaturamentoOptions] = useState<TipoFaturamentoOption[]>([]);
  const [tipoFaturamentoOptionsError, setTipoFaturamentoOptionsError] = useState('');
  const [savingTipoFaturamento, setSavingTipoFaturamento] = useState(false);
  // Erro e confirmação PRÓPRIOS do bloco de tipo de faturamento. Reaproveitar
  // authError/authSaved fazia a falha de um painel aparecer dentro de outro
  // ("Autorização TISS"), longe do botão que o faturista acabou de clicar.
  const [tipoFaturamentoError, setTipoFaturamentoError] = useState('');
  const [tipoFaturamentoSaved, setTipoFaturamentoSaved] = useState(false);
  const [solicitante, setSolicitante] = useState<ProfessionalOption | null>(null);
  const [savingSolicitante, setSavingSolicitante] = useState(false);
  const [solicitanteError, setSolicitanteError] = useState('');
  const [solicitanteSaved, setSolicitanteSaved] = useState(false);

  useEffect(() => {
    fetch(`/api/v1/billing/guides/${id}/`, {
          })
      .then(r => { if (!r.ok) throw new Error(`${r.status}`); return r.json(); })
      .then(setGuide)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  // dm_tipoFaturamento existe SÓ na guia de resumo de internação: é o único
  // template TISS que emite o campo (internacao_guide.xml.j2) e o único tipo
  // para o qual o gerador resolve ctm_internacaoDados. Em consulta, SADT e
  // honorários o valor não vai a lugar nenhum, então a tela não o mostra —
  // pedir ao faturista um código ANS que nenhum XML carrega é prometer
  // significado que o sistema não tem.
  const isInternacao = guide?.guide_type === 'internacao';
  // dadosSolicitante existe SÓ em ctm_sp-sadtGuia. A guia de resumo de
  // internação não tem o bloco (tem numeroGuiaSolicitacaoInternacao, que é
  // outra coisa), e a de consulta também não.
  const isSadt = guide?.guide_type === 'sadt';

  useEffect(() => {
    // Só busca a lista quando o painel pode aparecer: para os outros tipos de
    // guia esta request voltaria para uma tela que não tem onde exibi-la.
    if (!isInternacao) return;
    // Única fonte dos códigos de dm_tipoFaturamento (o serializer da guia não
    // repete mais a lista). Mesma chamada same-origin da guia acima: o cookie
    // httpOnly de sessão vai por padrão e o proxy /api do Next injeta o
    // Authorization — o endpoint exige autenticação e perfil de faturamento.
    // A falha é EXIBIDA: engolir o erro deixava o select vazio, e um select
    // vazio é indistinguível de "esta guia não tem tipo de faturamento".
    fetch('/api/v1/billing/guides/tipo-faturamento-options/', {})
      .then(r => { if (!r.ok) throw new Error(`${r.status}`); return r.json(); })
      .then((data) => {
        if (!Array.isArray(data)) throw new Error('resposta inesperada da API');
        setTipoFaturamentoOptions(data);
        setTipoFaturamentoOptionsError('');
      })
      .catch((e) => {
        setTipoFaturamentoOptions([]);
        setTipoFaturamentoOptionsError(
          `Não foi possível carregar os códigos de tipo de faturamento (${e.message}). `
          + 'Recarregue a página — sem a lista este campo não pode ser preenchido.'
        );
      });
  }, [isInternacao]);

  useEffect(() => {
    if (!guide) return;
    setAuthNumber(guide.authorization_number ?? '');
    // DRF DateField serializa como "YYYY-MM-DD" puro — usamos a string direto,
    // sem passar por Date/toISOString, para não arriscar deslocar o dia por fuso.
    setAuthDate(guide.authorization_date ?? '');
    setTipoFaturamento(guide.tipo_faturamento ?? '');
  }, [guide]);

  const isDraft = guide?.status === 'draft';

  const saveAuthorization = async () => {
    setSavingAuth(true);
    setAuthError('');
    setAuthSaved(false);
    try {
      const res = await fetch(`/api/v1/billing/guides/${id}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          authorization_number: authNumber,
          authorization_date: authDate || null,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail ?? JSON.stringify(data) ?? `${res.status}`);
      }
      const data = await res.json();
      setGuide(data);
      setAuthSaved(true);
    } catch (e: any) {
      setAuthError(e.message || 'Não foi possível salvar a autorização.');
    } finally {
      setSavingAuth(false);
    }
  };

  const submitGuide = async () => {
    setSubmitting(true);
    setActionMsg('');
    try {
      const res = await fetch(`/api/v1/billing/guides/${id}/submit/`, {
        method: 'POST',
              });
      if (!res.ok) throw new Error(`${res.status}`);
      const data = await res.json();
      setGuide(data);
      setActionMsg('Guia enviada com sucesso!');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const saveSolicitante = async () => {
    setSavingSolicitante(true);
    setSolicitanteError('');
    setSolicitanteSaved(false);
    try {
      const res = await fetch(`/api/v1/billing/guides/${id}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ requesting_professional: solicitante?.id ?? null }),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `${res.status}`);
      setGuide(await res.json());
      setSolicitanteSaved(true);
    } catch (e: any) {
      setSolicitanteError(e.message || 'Não foi possível salvar o profissional solicitante.');
    } finally {
      setSavingSolicitante(false);
    }
  };

  const saveTipoFaturamento = async () => {
    setSavingTipoFaturamento(true);
    setTipoFaturamentoError('');
    setTipoFaturamentoSaved(false);
    try {
      const res = await fetch(`/api/v1/billing/guides/${id}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tipo_faturamento: tipoFaturamento }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail ?? JSON.stringify(data) ?? `${res.status}`);
      }
      setGuide(await res.json());
      setTipoFaturamentoSaved(true);
    } catch (e: any) {
      setTipoFaturamentoError(e.message || 'Não foi possível salvar o tipo de faturamento.');
    } finally {
      setSavingTipoFaturamento(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-48 bg-neu-app rounded animate-pulse" />
        <div className="bg-neu-panel rounded-lg border border-slate-200 p-4 space-y-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-5 bg-neu-app rounded animate-pulse w-3/4" />
          ))}
        </div>
      </div>
    );
  }

  if (error && !guide) {
    return (
      <div className="space-y-4">
        <button onClick={() => router.back()} className="text-sm text-neu-inkMuted hover:text-neu-inkSoft">← Voltar</button>
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{error}</div>
      </div>
    );
  }

  const canSubmit = guide && (guide.status === 'draft' || guide.status === 'pending');
  const isDenied = guide?.status === 'denied';

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 flex-wrap">
        <button onClick={() => router.back()} className="text-slate-400 hover:text-neu-inkSoft text-sm">← Voltar</button>
        <h1 className="text-2xl font-semibold text-neu-ink">
          Guia #{guide?.guide_number ?? guide?.id}
        </h1>
        {guide?.status && (
          <span className={`inline-flex px-3 py-1 rounded-full text-sm font-medium ${STATUS_BADGE[guide.status] ?? 'bg-neu-app text-neu-inkSoft'}`}>
            {STATUS_LABEL[guide.status] ?? guide.status}
          </span>
        )}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{error}</div>
      )}
      {actionMsg && (
        <div className="bg-green-50 border border-green-200 text-green-700 rounded-lg px-4 py-3 text-sm">{actionMsg}</div>
      )}

      {/* Guide details card */}
      <div className="bg-neu-panel rounded-lg border border-slate-200 p-4">
        <h2 className="font-semibold text-neu-ink mb-4">Dados da Guia</h2>
        <dl className="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-4">
          <Field label="Nº da Guia" value={guide?.guide_number} />
          <Field label="Paciente" value={guide?.patient_name ?? guide?.patient} />
          <Field label="Operadora" value={guide?.provider_name ?? guide?.provider} />
          <Field label="Tipo de Guia" value={guide?.guide_type_display ?? guide?.guide_type} />
          {/* Só a guia de internação carrega dm_tipoFaturamento; nas demais a
              linha não existe — nem em branco, porque o campo não pertence
              àquele documento. */}
          {isInternacao && (
            <Field label="Tipo de faturamento (TISS)" value={guide?.tipo_faturamento_display ?? guide?.tipo_faturamento} />
          )}
          <Field label="Competência" value={guide?.competency} />
          <Field label="Nº Carteirinha" value={guide?.insured_card_number} />
          <Field label="Valor Total" value={fmtCurrency(guide?.total_value)} />
          <Field label="Criado em" value={guide?.created_at ? new Date(guide.created_at).toLocaleString('pt-BR') : null} />
          <Field label="Encontro" value={guide?.encounter} />
        </dl>
      </div>

      {/* Tipo de faturamento (TISS) — painel próprio, com erro e confirmação
          próprios: quem clica "Salvar tipo de faturamento" precisa ver a
          resposta aqui, não no painel de autorização logo abaixo. Só aparece na
          guia de internação, a única que emite o campo no XML. */}
      {/* dadosSolicitante (SP/SADT) — quem PEDIU, distinto de quem executou.
          Guia nascida de pedido de exame já vem preenchida; as demais precisam
          disto, senão a emissão do XML falha alto. */}
      {isSadt && (
        <div className="bg-neu-panel rounded-lg border border-slate-200 p-4">
          <h2 className="font-semibold text-neu-ink mb-1">Profissional solicitante (TISS)</h2>
          <p className="text-xs text-neu-inkMuted mb-4">
            <code>dadosSolicitante</code> exige conselho, número, UF e CBO de quem{' '}
            <strong>solicitou</strong> o procedimento — que não é o executante. Guias geradas de um
            pedido de exame herdam o solicitante automaticamente; nas demais, informe aqui. Sem
            isso a guia não gera XML, e o executante nunca é usado no lugar.
          </p>

          <Field
            label="Solicitante atual"
            value={guide?.requesting_professional_name ?? guide?.requesting_professional ?? null}
          />

          {!isDraft ? (
            <p className="mt-3 text-xs text-neu-inkMuted bg-neu-app rounded-lg px-3 py-2">
              Guia com status &quot;{STATUS_LABEL[guide.status] ?? guide.status}&quot;: o
              solicitante só muda enquanto a guia é rascunho.
            </p>
          ) : (
            <div className="mt-3 max-w-xl">
              <RemoteCombobox<ProfessionalOption>
                label="Profissional solicitante"
                endpoint="/api/v1/professionals/"
                value={solicitante}
                getKey={(item) => item.id}
                getLabel={professionalLabel}
                onChange={setSolicitante}
                placeholder="Buscar quem solicitou..."
              />
            </div>
          )}

          {solicitanteError && (
            <div className="mt-3 bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{solicitanteError}</div>
          )}
          {solicitanteSaved && (
            <div className="mt-3 bg-green-50 border border-green-200 text-green-700 rounded-lg px-4 py-3 text-sm">Profissional solicitante salvo.</div>
          )}

          {isDraft && (
            <button
              type="button"
              onClick={saveSolicitante}
              disabled={savingSolicitante || !solicitante}
              className="mt-4 bg-gradient-to-b from-neu-brand to-neu-brandDeep border-t border-neu-brandEdge shadow-neu-btn-primary text-white px-4 py-2 rounded-lg text-sm font-medium hover:shadow-neu-btn-primary-hover disabled:opacity-50"
            >
              {savingSolicitante ? 'Salvando...' : 'Salvar solicitante'}
            </button>
          )}
        </div>
      )}


      {isInternacao && (
        <div className="bg-neu-panel rounded-lg border border-slate-200 p-4">
          <h2 className="font-semibold text-neu-ink mb-1">Tipo de faturamento (TISS)</h2>
          <p className="text-xs text-neu-inkMuted mb-4">
            dm_tipoFaturamento da guia de resumo de internação. Os códigos e rótulos vêm da API; o
            manual de tabelas de domínio da ANS ainda não está no sistema, então o rótulo aparece como
            &quot;a confirmar&quot; em vez de um significado inventado aqui.
          </p>

          {!isDraft && (
            <p className="mb-3 text-xs text-neu-inkMuted bg-neu-app rounded-lg px-3 py-2">
              Guia com status &quot;{STATUS_LABEL[guide.status] ?? guide.status}&quot;: o tipo de
              faturamento só muda enquanto a guia é rascunho, porque trocá-lo depois do envio mudaria
              o significado do documento já transmitido à operadora.
            </p>
          )}

          <div className="max-w-xl">
            <label htmlFor="guide-tipo-faturamento" className="block text-xs font-medium text-neu-inkMuted uppercase tracking-wide mb-1">
              Tipo de faturamento (TISS)
            </label>
            <select
              id="guide-tipo-faturamento"
              value={tipoFaturamento}
              onChange={(e) => setTipoFaturamento(e.target.value)}
              disabled={!isDraft}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <option value="">Não informado</option>
              {tipoFaturamentoOptions.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </div>

          {tipoFaturamentoOptionsError && (
            <div className="mt-3 bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{tipoFaturamentoOptionsError}</div>
          )}
          {tipoFaturamentoError && (
            <div className="mt-3 bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{tipoFaturamentoError}</div>
          )}
          {tipoFaturamentoSaved && (
            <div className="mt-3 bg-green-50 border border-green-200 text-green-700 rounded-lg px-4 py-3 text-sm">Tipo de faturamento salvo.</div>
          )}

          {isDraft && (
            <button
              type="button"
              onClick={saveTipoFaturamento}
              disabled={savingTipoFaturamento}
              className="mt-4 bg-gradient-to-b from-neu-brand to-neu-brandDeep border-t border-neu-brandEdge shadow-neu-btn-primary text-white px-4 py-2 rounded-lg text-sm font-medium hover:shadow-neu-btn-primary-hover disabled:opacity-50"
            >
              {savingTipoFaturamento ? 'Salvando...' : 'Salvar tipo de faturamento'}
            </button>
          )}
        </div>
      )}

      {/* Autorização TISS */}
      <div className="bg-neu-panel rounded-lg border border-slate-200 p-4">
        <h2 className="font-semibold text-neu-ink mb-1">Autorização TISS</h2>
        <p className="text-xs text-neu-inkMuted mb-4">
          Senha e data comunicadas pela operadora. Se esta guia tiver uma autorização aprovada
          registrada, ela é usada na guia de resumo de internação e esta data digitada é ignorada —
          preencha aqui só o fallback para quando não há autorização aprovada correspondente.
        </p>

        {!isDraft && (
          <p className="mb-3 text-xs text-neu-inkMuted bg-neu-app rounded-lg px-3 py-2">
            Guia com status &quot;{STATUS_LABEL[guide.status] ?? guide.status}&quot; não pode mais
            ser editada — apenas rascunhos aceitam alteração de autorização.
          </p>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-xl">
          <div>
            <label htmlFor="guide-auth-number" className="block text-xs font-medium text-neu-inkMuted uppercase tracking-wide mb-1">
              Senha de autorização
            </label>
            <input
              id="guide-auth-number"
              type="text"
              value={authNumber}
              onChange={(e) => setAuthNumber(e.target.value)}
              disabled={!isDraft}
              maxLength={20}
              placeholder="Senha informada pela operadora"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none placeholder:text-slate-400 focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
            />
          </div>
          <div>
            <label htmlFor="guide-auth-date" className="block text-xs font-medium text-neu-inkMuted uppercase tracking-wide mb-1">
              Data da autorização
            </label>
            <input
              id="guide-auth-date"
              type="date"
              value={authDate}
              onChange={(e) => setAuthDate(e.target.value)}
              disabled={!isDraft}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
            />
          </div>
        </div>

        {authError && (
          <div className="mt-3 bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{authError}</div>
        )}
        {authSaved && (
          <div className="mt-3 bg-green-50 border border-green-200 text-green-700 rounded-lg px-4 py-3 text-sm">Autorização salva.</div>
        )}

        {isDraft && (
          <button
            type="button"
            onClick={saveAuthorization}
            disabled={savingAuth}
            className="mt-4 bg-gradient-to-b from-neu-brand to-neu-brandDeep border-t border-neu-brandEdge shadow-neu-btn-primary text-white px-4 py-2 rounded-lg text-sm font-medium hover:shadow-neu-btn-primary-hover disabled:opacity-50"
          >
            {savingAuth ? 'Salvando...' : 'Salvar autorização'}
          </button>
        )}
      </div>

      {/* Items table */}
      {guide?.items && guide.items.length > 0 && (
        <div className="bg-neu-panel rounded-lg border border-slate-200 overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-100">
            <h2 className="font-semibold text-neu-ink">Procedimentos</h2>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-neu-panel border-b border-slate-100">
              <tr>
                {['#', 'Descrição', 'Qtd', 'Valor Unit.', 'Total'].map(h => (
                  <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-neu-inkMuted uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {guide.items.map((item: any, idx: number) => (
                <tr key={item.id ?? idx}>
                  <td className="px-4 py-3 text-neu-inkMuted">{idx + 1}</td>
                  <td className="px-4 py-3 text-neu-ink">{item.description ?? '—'}</td>
                  <td className="px-4 py-3 text-neu-inkSoft">{item.quantity}</td>
                  <td className="px-4 py-3 text-neu-inkSoft">{fmtCurrency(item.unit_value)}</td>
                  <td className="px-4 py-3 text-neu-ink font-medium">{fmtCurrency(item.total_value ?? (item.quantity * item.unit_value))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Glosas section */}
      {isDenied && (
        <div className="bg-neu-panel rounded-lg border border-red-200 p-4">
          <h2 className="font-semibold text-red-700 mb-3">Glosas</h2>
          {guide?.glosas && guide.glosas.length > 0 ? (
            <ul className="space-y-2">
              {guide.glosas.map((g: any, i: number) => (
                <li key={g.id ?? i} className="text-sm text-neu-inkSoft border border-slate-100 rounded-lg p-3">
                  <span className="font-medium">{g.reason ?? g.motivo ?? 'Motivo não informado'}</span>
                  {g.value && <span className="ml-2 text-red-600">{fmtCurrency(g.value)}</span>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-400">Nenhum detalhe de glosa disponível.</p>
          )}
        </div>
      )}

      {/* Action buttons */}
      {canSubmit && (
        <div className="flex gap-3">
          <button
            onClick={submitGuide}
            disabled={submitting}
            className="bg-gradient-to-b from-neu-brand to-neu-brandDeep border-t border-neu-brandEdge shadow-neu-btn-primary text-white px-4 py-2 rounded-lg text-sm font-medium hover:shadow-neu-btn-primary-hover disabled:opacity-50"
          >
            {submitting ? 'Enviando...' : 'Enviar Guia'}
          </button>
        </div>
      )}
    </div>
  );
}
