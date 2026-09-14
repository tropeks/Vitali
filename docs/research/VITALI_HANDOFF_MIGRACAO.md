# Handoff — estado do Vitali antes da migração de `/home/rcosta00/dev`

**Data:** 18 de agosto de 2026 · **Branch:** `onda0-perimetro-multitenant` · **HEAD:** `af7f33d`
**Remote:** sincronizado (`origin/onda0-perimetro-multitenant`) · **PR:** #211, em draft

## Como retomar

O trabalho está todo publicado no remote. Após a migração, um `git clone` ou o diretório movido
retomam do mesmo ponto — nada depende de estado local não versionado, exceto o que está listado
em "Fora do repositório" abaixo.

```
git checkout onda0-perimetro-multitenant   # 14 commits à frente de master
gh pr view 211                             # contexto completo da entrega
```

Leia, nesta ordem: `VITALI_READINESS_REPORT.md` (o diagnóstico), `VITALI_EXECUTION_WAVES.md`
(o plano), `VITALI_HUMAN_APPLIED_GATES.md` (o que precisa de mão humana) e
`VITALI_ONDA4_TISS_MODELAGEM.md` (a onda em curso). As mensagens de commit carregam o
raciocínio, não só o quê — valem mais que qualquer resumo.

## O que foi entregue

| Onda | Escopo |
|---|---|
| Sondagem | Readiness real por swarm de 10 domínios; score composto ~5,9/10 |
| 0 | Perímetro multi-tenant: JWT cross-tenant, listagem global de usuários, IDOR de escrita, MFA no-op, DICOMweb compartilhado |
| 1 | Recuperação e sinal: drill de restore quebrado por construção, Alertmanager inexistente, Celery sem schema de tenant, backup em texto claro |
| 2 | Receita: taxas de internação sem caminho de entrada, guia editável pós-envio, conformidade TISS medida contra o XSD |
| 3 | Conformidade: PHI cru para provider externo, auditoria de leitura em 2 de ~40 viewsets, senha nunca validada, `httpOnly` cosmético |
| 4 | TISS hospitalar: forma dos templates, taxonomias em `Admission`, autorização por digitação manual, `dadosBeneficiario`/`dadosExecutante` |

**Verificação da última suíte completa:** 1123 passed, 45 skipped, 2 xfailed, 0 failed ·
`ruff` limpo · `mypy` 0 erros em 1042 arquivos · `lint-imports` 0 contratos quebrados ·
frontend `tsc` limpo, 765 testes.

## Estado da árvore no momento da migração

**Nada funcional pendente.** Todo trabalho de `backend/`, `frontend/` e `docs/` está commitado
e publicado.

**Churn externo, deliberadamente não tocado:** `.claude/skills/gstack-*` e `skills/` têm milhares
de alterações que vieram de uma reinstalação do gstack durante a sessão. **Não são deste trabalho,
nunca entraram em commit** (verificado: `git diff --name-only origin/master..HEAD` não retorna
nenhum arquivo desses diretórios). Não foram revertidas de propósito — reverter alteração externa
que não se fez é mais arriscado que deixá-la. Após a migração, decida se restaura ou reinstala o
gstack.

## Onde a Onda 4 parou

A guia de Resumo de Internação avançou campo a campo, medindo com `validate_xml` contra o XSD real
a cada passo. Sequência destravada: `cabecalhoGuia` → `numeroGuiaSolicitacaoInternacao` →
`dadosAutorizacao` → `dadosBeneficiario` → `dadosExecutante`.

**Residual atual:** `dadosInternacao`, e é gap de **dado**, não de forma. O filho `tipoFaturamento`
não tem fonte em model nenhum — nem `TISSGuide`, nem `emr.Admission`. É decisão de produto sobre o
momento de faturamento. Atrás dele seguem `dadosSaidaInternacao` e o breakdown de `valorTotal`,
ainda inalcançados pelo validador.

**A SP/SADT** para em `dadosSolicitante`: o `TISSGuide` não distingue quem pediu de quem executou.

Lição da onda, confirmada cinco vezes: **quatro das cinco fatias não precisaram de model novo**.
Era dado existente mal ligado ao template. A estimativa inicial de "modelagem de domínio cara"
superestimou; cada medição corrigiu para baixo.

## Decisões humanas pendentes

1. **`tipoFaturamento`** — de onde vem o momento de faturamento? Bloqueia a conclusão da guia.
2. **`dadosSolicitante`** — o fluxo real registra quem solicitou o exame? Bloqueia a SP/SADT.
3. **Correção pós-draft** — não existe caminho para corrigir autorização depois que a guia sai de
   `draft`. Cenário real: internação de urgência, guia enviada antes de a operadora aprovar. As
   três saídas (correção auditada, retorno a draft, reemissão) têm implicação diferente com a
   operadora.
4. **Rótulos ANS `41`–`67`** — 11 códigos de `dm_motivoSaida` sem rótulo confiável; precisa do
   manual oficial. Hoje aparecem na UI como "Código NN (rótulo a confirmar no manual ANS)".
5. **`OverviewView.revenue`** — expõe financeiro sem gate, por decisão de produto documentada (CP-1).
6. **WhatsApp → `triage.read`** — essas views expõem telefone e conteúdo de mensagem de paciente.

## Bloqueios operacionais

**Acesso ao Docker.** `rcosta00` não está no grupo `docker` e `sudo` é barrado pelo guard. Isso
**não** impede pytest — há Postgres no host e a suíte roda normalmente. Impede duas coisas:

- **O drill de restore** (`scripts/restore_test.sh:40` faz `command -v docker || fail`). É o
  bloqueador nº 1 da auditoria: não há prova de que um backup do Vitali já tenha sido restaurado.
- **Deploy em staging.** Os critérios da diretriz estão satisfeitos (dado de teste apenas,
  migrations aditivas, sem secret novo, rollback claro via `IMAGE_TAG=sha-<anterior>`).

Destrava com `sudo usermod -aG docker rcosta00` e nova sessão de login.

**Ordem obrigatória antes de qualquer deploy:** rodar `backfill_tenant_memberships`
(`--dry-run --report` → `grant_tenant_membership` nos órfãos → backfill real →
`--dry-run --fail-on-orphans`) **antes** de subir o compose, senão `ENFORCE_TENANT_MEMBERSHIP=true`
dá 401 em todo usuário sem vínculo materializado.

**Smoke test manual obrigatório** de login, refresh e logout após o deploy: a Onda 3 mexeu no
caminho de autenticação de todo o app e o refresh single-flight está coberto só por mock.

**Três gates precisam de mão humana**, especificados em `VITALI_HUMAN_APPLIED_GATES.md`. Armadilha:
aplicar o item 0.3 como está **derruba o CI**, porque o `core.E008` acusa catálogo vazio no runner
efêmero — mitigação no addendum do documento.

## Fora do repositório

- **Workaround AppArmor host-local** em `~/.vitali-compose-apparmor-fix.yml`, referenciado por
  `COMPOSE_FILE` no `.env`. Foi corrigido nesta sessão (usava `security_opt` duplicado; agora usa
  `!override`). **Não é versionado** — se a migração não levar o home junto, recriar.
- **Webhook do Alertmanager na bridge Hermes**: decidido (`deliver_only: true`, sem execução, via
  proxy ZeroTier em `172.29.147.53:9119`), **não criado** — falta `deliver_chat_id`. Nenhum `POST`
  foi emitido.
