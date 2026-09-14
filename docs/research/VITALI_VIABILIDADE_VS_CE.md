# Vitali × Vitali-CE — viabilidade e sequenciamento

**Data:** 2026-08-30 · **HEAD auditado:** `9584381` (`onda0-perimetro-multitenant`)
**Pergunta:** dá para fazer o Vitali-CE? E, se dá, antes ou depois de terminar a receita do Vitali?
**Consome:** `VITALI_READINESS_REPORT.md` (17/08), `VITALI_EXECUTION_WAVES.md`, `~/dev/vitali-ce/architecture/` v2.1

> **Como ler.** Mesma convenção do readiness report: **[E]** evidência (arquivo:linha ou comando
> lido nesta sessão), **[H]** hipótese, **[B]** bloqueio. Os cinco bloqueadores de receita da
> sondagem de 17/08 foram **reconferidos no código de hoje** — nenhum foi aceito como fechado com
> base em mensagem de commit.

---

## 1. Resposta

Os dois são viáveis. A pergunta que decide não é se dá para construir o CE — é que **o Vitali está
a três itens de faturar, e dois deles são de rodar, não de escrever**.

Das cinco travas de receita da sondagem, **quatro caíram** nas Ondas 0–4. A que sobrou é a mais
barata do quadro inteiro e a única que nenhuma onda tocou: **os catálogos nunca são carregados**.
Sem TUSS, CID-10 e CBHPM em produção, cada guia TISS sai com código inválido — o que torna inerte
todo o trabalho das Ondas 2 e 4. Existem 24 importers idempotentes prontos. Ninguém os chama.

**Recomendação:** terminar a receita do Vitali, e rodar em paralelo apenas as cinco stories do CE
que não tocam `apps.core`. Segurar S-001 e S-004 até a F19.

---

## 2. Os cinco bloqueadores, reconferidos

| Bloqueador (17/08) | Estado em 30/08 — evidência | Status |
|---|---|---|
| Isolamento de tenant desligado por padrão e ausente do compose | `ENFORCE_TENANT_MEMBERSHIP: "true"` em `docker-compose.prod.yml:64,101,150` e `.staging.yml:69,105,152` | **fechado** [E] |
| MFA inoperante — middleware lia `request.user` antes da auth do DRF | `apps/core/middleware.py:325` define `_resolve_user()`, chamado em `:349` | **fechado** [E] |
| Drill de restore consultava tabela inexistente | `scripts/restore_test.sh:128` consulta `core_tenant`; `:158` itera `emr_patient` por schema | **script correto, drill nunca executado** [E] |
| TISS: validação não-bloqueante, 0 testes chamando `validate_xml`, envelope sem `guiasTISS` | `validate_xml` chamado em `billing/views.py:1278` e `:1510`; **21 referências** em `tests/test_xml_engine.py`; `batch_envelope.xml.j2:37` tem `guiasTISS`; existem `sadt_guide.xml.j2` e `internacao_guide.xml.j2` | **fechado** [E] |
| Catálogos vazios em produção | 24 importers em `apps/core/management/commands/` + ETLs em `scripts/catalogs/`. `grep` por eles em `.github/workflows/`, `docker/`, `docker-compose*.yml`, `*/migrations/` → **zero** | **intocado** [E] |

Fechou também o que não estava entre os cinco: `validate_password` passou a ser chamado de verdade
(`apps/core/serializers.py:319`), PHI deixou de sair cru para provider externo, e a Onda 4 levou a
guia de internação de fachada a discriminar itens, emitir `valorTotal` com breakdown e falhar
rápido quando falta CNES do executante.

> **Correção ao registro anterior.** A memória de projeto dizia que `procedimentosExecutados` não
> era emitido e que esse era "o próximo trabalho real". Está desatualizada: o commit `80d2962`
> implementou, e a onda seguiu além, fechando `dadosSolicitante` (`5d29f6c`), `tipoFaturamento`
> (`55e9ec3`) e os procedimentos e total da SP/SADT (`305d9ec`). [E]

---

## 3. O que falta para faturar

### 3.1 Carregar os catálogos `[P0 · horas de operação]`

O item de maior alavancagem do quadro, e o único dos cinco que nenhuma onda tocou.

Não há nada a construir. O motor (`core.terminology_base.CatalogImporter`) é idempotente, faz
upsert por código, registra proveniência e tem `--dry-run`. Os ETLs baixam e transformam a fonte
oficial do DATASUS. Existe até um `verify_catalogs.py`. [E]

```
apps/core/management/commands/  → import_tuss, import_cid10, import_sigtap, import_cbhpm,
                                  import_cbo, import_cnes, import_loinc, import_anvisa_cmed,
                                  import_manchester, import_nanda, import_nic, import_noc,
                                  import_ucum, import_cido, import_insurances, … (24)
scripts/catalogs/               → etl_cid10_datasus.py, etl_sigtap.py, etl_cido.py
```

**O trabalho é duplo:** rodar uma vez (resolve hoje) e amarrar num passo automático — bootstrap ou
migration de dados (resolve o próximo tenant). Sem a segunda metade, o bloqueador volta no
primeiro cliente novo.

### 3.2 Template da guia de honorários `[P1 · tamanho P]`

`apps/billing/templates/tiss/` tem quatro arquivos: `consulta_guide`, `sadt_guide`,
`internacao_guide` e `batch_envelope`. Honorários não tem template, e o motor cai no default — ou
seja, emite honorário com a forma de guia de consulta. [E]

Com `validate_xml` agora rodando nos testes, dá para fechar medindo, do mesmo jeito que a Onda 4
fechou a internação.

### 3.3 Fazer produção existir uma vez `[P0 para entrega · tamanho G]`

A **Onda 4 do plano era "Operação real"** (`VITALI_EXECUTION_WAVES.md` §Onda 4): `deploy.sh`
idempotente com backup pré-migration e rollback automático, exercitar produção ponta a ponta num
host descartável a partir de `gen_secrets.sh` + `docker-compose.prod.yml` puros, e fazer
`release-deploy.yml` rodar ao menos uma vez.

Ela foi preterida em favor do TISS. **Foi a escolha certa na hora** — TISS destranca receita,
deploy destranca entrega, e receita sem produto validado não vale nada. Mas agora é a única coisa
entre o código e um cliente.

Junto vêm os três gates de mão humana do `VITALI_HUMAN_APPLIED_GATES.md`, todos pendentes:

| Item | O quê | Efeito de não aplicar |
|---|---|---|
| 0.3 | `manage.py check --deploy` bloqueante no CI | nada impede desligar o isolamento multi-tenant de novo |
| 1.8 | job de teste unitário do frontend no CI | ~700 testes podem quebrar sem bloquear merge |
| 1.3 | timer do drill de restore | backup de dado clínico segue **nunca restaurado** |

O 1.3 é o que eu não adiaria: o script foi consertado, mas script consertado não é drill executado.

---

## 4. O que o Vitali-CE custa

Pacote de arquitetura v2.1 em `~/dev/vitali-ce/`, gate G0. E-0 é o único epic autorizado.

| Story | O que é | Tam. | Bloqueio |
|---|---|---|---|
| S-000 | Ler o repo do Vitali | S | ✅ concluída 30/08 |
| S-000b | Decidir `concession`: generalizar ou modelar do zero | S | livre |
| S-002 | Esqueleto standalone, compose, healthz, import-linter | M | livre |
| S-003 | Tenancy `django-tenants` + 6 gates de CI | M | livre |
| S-006 | AuditLog append-only + `request_id` | S | livre |
| S-007 | `Sequencia` + teste de concorrência | S | livre |
| S-005 | Anexos MinIO — greenfield inteiro | M→L | **F5** |
| S-004 | Auth JWT + membership | M | **F19** · `apps.core` |
| S-001 | Extrair `vitali-core` | L→XL | **F19** · `apps.core` |

Cinco stories livres, todas S ou M. **É pouco, e é enganoso:** E-0 entrega fundação, não produto.
Depois dela vêm ordem de serviço com máquina de estados, calibração com certificado rastreável,
laudo assinado, alertas de vencimento, indicadores de acreditação e o pacote de auditoria do
hospital. Nada disso tem epic escrito, e não vai ter enquanto o brief for rascunho e as Open
Questions de porte, escopo, offline e exportação seguirem sem resposta. [E]

---

## 5. Onde os dois colidem

Não é disputa de tempo. É disputa de arquivo.

**`apps.core`.** S-001 e S-004 do CE mexem exatamente na superfície onde o Vitali acabou de fechar
um furo cross-tenant CRITICAL (`docs/plans/TENANT-MEMBERSHIP.md`, enforce ativado na branch
`looper/115-…`). Pelo contrato de fronteira do próprio repo (`docs/ARCH_SERVICE_LAYER.md`, regra
2), `apps.core` é o hub que **todos** os domínios podem importar e o único que pode — o nó mais
acoplado, não uma folha. Extrair é o refactor mais caro que existe aqui, e enquanto rodar, o gate
de CI do Vitali para o trabalho do Vitali. [E]

**O que não colide:** S-000b, S-002, S-003, S-006 e S-007 não tocam este repo em nada. Sobem um
projeto separado com o `core` pinado como dependência de leitura.

**Velocidade observada, com ressalva:** entre 17 e 21 de agosto entraram **45 commits cobrindo
cinco ondas**, incluindo o fechamento do perímetro multi-tenant e a guia de internação inteira.
[E] É rajada com assistência de IA, não regime sustentado. Serve para dizer que os três itens
restantes cabem numa janela curta; **não** serve para prometer calendário do CE, que não tem
escopo travado.

---

## 6. Sequência recomendada

1. **Carregar os catálogos.** Destrava valor já construído em vez de construir valor novo. ETL e
   importer já existem e são idempotentes.
2. **Amarrar a carga num passo automático** — bootstrap ou migration de dados. Sem isso o
   bloqueador volta no primeiro tenant novo.
3. **Fechar a guia de honorários**, medindo com `validate_xml` como a internação foi fechada.
4. **Rodar a Onda 4 do plano — Operação real**, com os três gates humanos. O drill de restore é o
   que não adiaria.
5. **Em paralelo, sem custar um commit a este repo:** S-000b, S-002, S-003, S-006 e S-007 do CE.
6. **Segurar S-001 e S-004 até a F19** — extração do core só depois que a onda de membership
   fechar e o produto principal estiver faturando.

**A pergunta que nenhuma leitura de código responde:** a demandante do CE paga antes do primeiro
cliente de TISS? Se paga, os itens 1 e 5 invertem. Se não, a ordem acima está certa — terminar um
produto que já existe custa menos do que começar o segundo, e o Vitali está mais perto do fim do
que a sondagem de agosto sugeria. [B — decisão comercial, fora do alcance do repo]

---

## 7. Reprodução

```sh
cd ~/dev/vitali

# bloqueador 1 — isolamento
grep -rn "ENFORCE_TENANT_MEMBERSHIP" backend/vitali/settings/*.py docker-compose*.yml

# bloqueador 2 — MFA
grep -n "_resolve_user" backend/apps/core/middleware.py

# bloqueador 3 — drill de restore
grep -n "core_tenant\|emr_patient" scripts/restore_test.sh

# bloqueador 4 — TISS
grep -rn "validate_xml" backend/apps/billing/views.py
grep -rn "validate_xml" backend/apps/billing/tests/ | wc -l
grep -n "guiasTISS" backend/apps/billing/templates/tiss/batch_envelope.xml.j2
ls backend/apps/billing/templates/tiss/            # honorarios ausente

# bloqueador 5 — catalogos
ls backend/apps/core/management/commands/ | grep ^import_ | wc -l
grep -rn "import_tuss\|import_cid10\|import_sigtap" \
     .github/workflows/ docker/ docker-compose*.yml backend/apps/*/migrations/
# ^ vazio = nenhum caminho automatico de carga

# velocidade
git log --since=2026-08-17 --oneline | wc -l
```
