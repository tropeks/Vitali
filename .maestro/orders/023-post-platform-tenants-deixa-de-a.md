<!-- maestro-order v1
id: 023
ts: 2026-09-25T09:42:31-03:00
epoch: 1790340151
head: 82698baa5245a91e5400a78fb8578df225775342
branch: order/023-platform-tenants-auth
intent_version: 5
intent_hash: a6120b3c
author_session: desconhecido
-->
# Ordem 023 — POST platform/tenants deixa de aceitar anonimo: autenticacao de plataforma e throttle, antes da 022


> **Direção:** INTENT v5, **§Prioridade 1**: "Isolamento entre tenants antes de qualquer
> feature. [...] Mudança em auth, tenant, permissão ou migration passa por especialista e
> teste". **Vai na frente da 022** por decisão do Imediato (25/09): a 022 unifica os
> caminhos de criação de clínica, e esta fecha antes a porta que um anônimo alcança.
>
> **Execução headless, prova pelo CI.** A forge **não roda** compose do Vitali. Esta ordem
> não sobe stack, não toca staging nem produção e não faz `POST` em ambiente nenhum.

## O defeito, lido no código em 25/09

`TenantRegistrationView` (`apps/core/views.py:555`, rota `POST /api/v1/platform/tenants`
em `apps/core/urls_public.py`) declara:

```python
permission_classes = [permissions.AllowAny]
```

Qualquer requisição que chegue a ela cria `Tenant`, com schema e `migrate_schemas` inteiro,
mais `Domain`, papéis e um admin **com a senha escolhida por quem chamou**. O comentário da
rota diz "engineer/platform-admin flow". As vizinhas em `views_platform.py` usam
`_PLATFORM_PERMS = (IsAuthenticated, IsPlatformAdmin)`; esta não.

**Throttle:** a view não declara `throttle_classes`, então vale o padrão do DRF para
anônimo, `100/hour` por IP (`REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["anon"]`). São até
100 schemas por hora por IP. O signup self-serve, que é público de propósito, usa
`SignupRateThrottle` a `5/hour`, e o docstring dele explica por quê: cada chamada cria um
schema e roda todas as migrations.

**O teste existente afirma o defeito:** `apps/core/tests/test_auth.py:299`
(`TenantRegistrationTestCase`) posta com `APIClient()` **sem autenticação** e espera `201`.

## Exposição medida em 25/09, só por leitura

Sondagem por `GET` e `OPTIONS`, **nunca `POST`**, pelos hostnames públicos (Cloudflare):

```
host                  /api/v1/platform/tenants   controles
vitali.qtec.me        404 (página 404 do Django)  /health/ 200 · /api/v1/patients/ 401
vitali-demo.qtec.me   404 (página 404 do Django)  /api/v1/public/signup/ 404
                                                  /api/v1/platform/plans/ 404
```

Os dois hostnames resolvem para schema de **tenant**: as rotas de tenant respondem (401), e
as do URLconf público (`signup`, `platform/*`) dão 404. Então, **hoje, a rota não é
alcançável pelos hostnames públicos de staging**. Não existe produção: nenhum DNS para
`vitali.com.br` e variantes, e o `vulcan/docs/PUBLISH.md` só publica esses dois hostnames,
ambos da lab.

**Isso não fecha o defeito.** A rota passa a ser alcançável no dia em que algum `Domain`
apontar para o schema `public` (é o que o `bootstrap_beta --public-domain` cria, e é o que
a produção vai ter para o signup). A porta está trancada por acaso de roteamento, e não por
código.

## O trabalho (correção mínima)

1. **Teste vermelho primeiro.** Commit `test(core): ...` que **falha** no tip atual:
   * `POST` anônimo → `401`, e **nada** criado: nenhum `Tenant`, `Domain` ou `User`, nenhum
     schema novo em `pg_namespace`;
   * `POST` autenticado de usuário comum (admin de clínica, não operador) → `403`, nada
     criado;
   * `POST` de operador de plataforma (`is_platform_admin`) → `201`, com o mesmo contrato de
     resposta de hoje (`tenant`, `domain`, `admin_user`, `trial_ends_at`);
   * o throttle morde: a chamada seguinte ao teto devolve `429`, e nada é criado nela.
2. **O conserto:**
   * `permission_classes = [IsAuthenticated, IsPlatformAdmin]` (ou `_PLATFORM_PERMS`
     importado, se não criar ciclo de import);
   * `throttle_classes` com um throttle **dedicado**, com escopo próprio, chaveado no
     usuário. Teto de partida `5/hour`, o mesmo do signup, porque o custo por chamada é o
     mesmo;
   * nada mais muda na view. A duplicação de papéis e admin em relação ao serviço de
     provisionamento é da ordem 022, não desta.
3. **O teste antigo inverte.** `TenantRegistrationTestCase` passa a autenticar como
   operador para os casos de sucesso. Procure outro teste que poste anônimo nessa rota
   (`test_self_serve_signup.py` usa `platform/tenants/`, com barra, que é outra view:
   confira) e ajuste só a autenticação, sem afrouxar asserção.
4. **Docs:** a linha de `README.md` §Estado atual que cita a rota passa a dizer que ela
   exige operador de plataforma.

## Prova exigida

* O histórico do branch mostra o commit vermelho **antes** do conserto, e o CI desse commit
  vermelho falhando **nos testes novos**.
* Job `Backend — Tests` verde no tip do branch.
* **Recibo antes do merge:** com o PR aberto contra `onda0-perimetro-multitenant` e o CI
  verde no tip, rode
  `maestro evidence --record --label order-23 -- gh run watch <run-id> --exit-status`, com
  o `<run-id>` do workflow `CI` daquele tip.

## Ask-First

* Mudar `IsPlatformAdmin`, `is_platform_admin` ou `DEFAULT_THROTTLE_RATES`: pare e
  pergunte.
* Teto do throttle diferente de `5/hour`: pare e pergunte.
* Se algum consumidor real depender do `POST` anônimo, pare e reporte antes de adaptar.
  Em 25/09, nem `frontend/` nem o `ci.yml` chamam a rota.

## Fora desta ordem

* Unificar os caminhos de criação de clínica, apagar `provision_tenant.sh` e cuidar da
  partição de auditoria do tenant novo: é a ordem **022**, que vem depois desta.
* Conferir `NUM_PROXIES=1` atrás de Cloudflare Tunnel → nginx. Se o nginx enxerga o
  `cloudflared` como par, todo anônimo pode cair num balde só. É achado a medir em ordem
  própria, não a consertar aqui.
* Qualquer `POST` em staging ou produção, inclusive "para confirmar".

## Contrato de execução
- Trabalhe APENAS no branch `order/023-platform-tenants-auth`; NUNCA no main/master.
- Prove com o ledger: `maestro evidence --record --label order-23 -- <suíte>` no tip do branch.
- Direção vigente na criação: INTENT v5 (`.maestro/INTENT.md`) — o plano cita a seção da direção que autoriza esta ordem.
- Estourou Ask-First ou orçamento? PARE e reporte ao humano — não improvise.
- O aceite é do diretor: `maestro order --accept 023` (você não fecha a própria ordem).
accepted_at: 2026-09-25T17:14:13-03:00
accepted_session: desconhecido
accepted_tree: 9bbac31ac29308bb38469bf06beb4fa08b4b5fac
accepted_intent: 6
