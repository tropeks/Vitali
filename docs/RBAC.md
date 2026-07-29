# RBAC — Controle de Acesso Baseado em Papéis (Vitali)

> Contrato de autorização do Vitali. Fonte da verdade em código:
> `backend/apps/core/permissions.py` (classes + conjuntos + `DEFAULT_ROLES`) e
> `frontend/lib/permissions.ts` + `frontend/components/layout/nav.tsx` (gates de UI).
> Este documento descreve como o RBAC **deve** ser. Se o código divergir, o código
> está errado — abra correção.

## 1. Princípios

1. **Autorização é por permissão de papel, nunca por nome de papel.** `role.name`
   é texto livre editável pelo usuário — usá-lo pra autorizar é vetor de escalonamento
   (finding histórico A01). Gate sempre na lista `role.permissions` (ou na capacidade
   `admin` não-forjável).
2. **Módulo ativo ≠ autorizado.** Ter o módulo do tenant ligado (`ModuleRequiredPermission`)
   só diz que o tenant *contratou* a funcionalidade. NÃO diz que *este usuário* pode usá-la.
   **Todo endpoint que lê ou escreve dado sensível gateia em uma permissão de papel real**,
   além do módulo. (Este foi exatamente o bug da Concessão: 16 viewsets só com
   `[IsAuthenticated, ConcessionModule]` → qualquer usuário do tenant, inclusive enfermeiro,
   acessava ativos/contratos/P&L.)
3. **Menos privilégio por padrão.** Papéis clínicos (enfermeiro, médico) NÃO recebem
   permissões administrativas/financeiras. Ao criar uma permissão nova, ela entra só nos
   papéis que precisam — nunca "por via das dúvidas".
4. **Defesa em profundidade.** O gate de UI (esconder item de menu) é UX, não segurança.
   A verdade é o backend. UI e backend devem gatear na **mesma** permissão.
5. **Fail-closed.** Sem papel, sem permissão → 403. Nunca fail-open.

## 2. Modelo

- **Usuário** (`core.User`) pertence a um tenant e tem um papel efetivo.
- **Multi-tenant:** o papel efetivo vem de `User.effective_role()`
  (`apps/core/models.py`) — sob o Modelo B, resolve o papel via
  `UserTenantMembership` do tenant atual; cai pro papel global quando não há
  membership. **Toda checagem usa `effective_role()`**, nunca o papel global cru.
- **Papel** (`core.Role`) carrega `permissions`: uma **lista JSON de strings**
  (`["emr.read", "emr.write", "billing.read", ...]`). É a única fonte de autorização
  do papel.
- **Platform admin** (operador Vitali/SaaS): `is_platform_admin(user)` — bypassa
  módulo e permissão. Política: operadores NUNCA são criados com `is_superuser=True`
  fora do contrato; `is_platform_admin` deriva disso de forma controlada.
- **Tenant admin:** `role_has_admin_capability(role)` — verdadeiro quando a lista
  tem a capability literal `"admin"` OU é o papel de sistema `is_system` chamado
  `"admin"`. Admin bypassa as checagens de permissão granular.

## 3. Convenção de nomes de permissão

Formato: **`<domínio>.<ação>`**, minúsculo, `snake_case`.

- **Domínios** = área funcional: `emr`, `billing`, `adt`, `beds`, `emergency`,
  `imaging`, `pharmacy`, `emar`, `hemoterapia`, `concession`, `ai`, `fhir`,
  `surgery`, `roster`, `hr`, `organization`, `integrations`, …
- **Ações canônicas:**
  - `read` — visualizar/listar.
  - `write` — criar/editar (use `partial_write` quando o papel só edita um subconjunto).
  - `delete` — remover (raro; append-only é preferível no clínico).
  - `manage` — administração do domínio (config, catálogos, ações privilegiadas).
  - `sign` — assinatura/validação (ex: `emr.sign`).
  - ações de domínio específicas quando fizer sentido: `adt.admit`/`discharge`/`transfer`,
    `emar.administer`, `emergency.classify`, `hemoterapia.transfuse`, `ai.use`/`ai.manage`.
- **Split read/write:** domínios sensíveis expõem `.read` (métodos seguros) e
  `.write`/`.manage` (mutação) separados, gateados por método (ver §5).

## 4. Papéis padrão (`DEFAULT_ROLES`)

Definidos em `apps/core/permissions.py`; materializados por tenant via
`create_default_roles`. Intenção de cada um (conjunto exato = código):

| Papel | Conjunto | Escopo |
|---|---|---|
| `admin` | `ADMIN_PERMISSIONS` | Tudo do tenant: clínico + back-office + financeiro + config + **concessão**. Carrega a capability `"admin"`. |
| `medico` / `dentista` | `CLINICAL_PRESCRIBER_PERMISSIONS` | Prescritor: EMR read/write/sign, prescrição, pedidos, agenda. Sem back-office/financeiro. |
| `enfermeiro` | `NURSING_PERMISSIONS` | Enfermagem: EMR read/partial, SAE, MAR/eMAR, beira-leito, hemoterapia clínica. **Sem** financeiro, **sem concessão**, sem admin. |
| `recepcao` / `recepcionista` | `RECEPTION_PERMISSIONS` | Cadastro de paciente, agenda, atendimento — sem clínico profundo nem financeiro. |
| `farmaceutico` | `PHARMACY_PERMISSIONS` | Farmácia/estoque/dispensação/interações. |
| `faturista` | `BILLING_PERMISSIONS` | Faturamento TISS/SUS, guias, glosas, financeiro. Sem clínico de escrita. |

**Regra:** ao adicionar uma permissão nova, decida explicitamente em quais desses
conjuntos ela entra. Clínico ≠ financeiro ≠ administrativo ≠ concessão.

## 5. Como gatear um endpoint (backend)

Classes em `apps/core/permissions.py` (todas com `__call__` retornando `self` pra
funcionar como instância pré-construída em `permission_classes`):

- `ModuleRequiredPermission('<módulo>')` — tenant tem o módulo ativo. **Nunca use sozinho**
  em dado sensível.
- `HasPermission('<domínio>.<ação>')` — o papel efetivo tem a string na lista. Platform-admin
  e capability `admin` bypassam.
- `IsTenantAdmin` / `IsPlatformAdmin` — administração/gestão de papéis e usuários privilegiados.

**Padrão canônico — módulo + permissão, com split read/write por método:**

```python
from rest_framework.permissions import BasePermission, SAFE_METHODS
from apps.core.permissions import is_platform_admin, role_has_admin_capability

class HasConcessionAccess(BasePermission):
    def __call__(self):
        return self

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if is_platform_admin(u):
            return True
        role = u.effective_role()
        if not role:
            return False
        if role_has_admin_capability(role):
            return True
        needed = "concession.read" if request.method in SAFE_METHODS else "concession.manage"
        return needed in role.permissions
```

```python
# No viewset — módulo E permissão, sempre:
permission_classes = [IsAuthenticated, ConcessionModule, HasConcessionAccess]
```

Notas:
- Em `permission_classes` **de atributo**, use a **classe** (sem `()`) — mypy rejeita
  instância ali; o DRF instancia (a classe não tem args de `__init__`). Em
  `get_permissions()` retorne **instâncias**: `[IsAuthenticated(), ConcessionModule(), HasConcessionAccess()]`.
- Para gate de permissão única sem split, `HasPermission('<domínio>.<ação>')` basta.
- Endpoints de administração de papéis/usuários privilegiados → `IsTenantAdmin`.

## 6. Gate de UI (frontend)

Cada item de nav em `frontend/components/layout/nav.tsx` carrega seu gate, avaliado
por `canSee(user, item, activeModules)` (`frontend/lib/permissions.ts`):

- `module: "<chave>"` — só aparece se o tenant tem o módulo ativo.
- `permissions: [PERMISSIONS.X, ...]` — só aparece se o papel tem **alguma** delas.
- `superuser: true` — só platform admin (grupo Plataforma).

**Regra:** o item de UI deve gatear na **mesma** permissão que o backend exige. Módulo
sem `permissions` num item administrativo = bug (foi o caso da Concessão). `PERMISSIONS`
espelha as strings do backend; mantenha em sincronia.

## 7. Checklist — adicionar um módulo/permissão novo

1. **Backend:** definir a(s) permissão(ões) `<domínio>.<ação>`; criar/usar a permission
   class (módulo + `HasPermission`/split); aplicar a **TODOS** os viewsets do domínio.
2. **Papéis:** adicionar a permissão só aos conjuntos que precisam em `DEFAULT_ROLES`
   (nunca a todos). Clínico não ganha financeiro/administrativo por padrão.
3. **Teste:** provar que um papel sem a permissão recebe **403** (read e write) e que o
   papel autorizado passa; que platform-admin/admin bypassam.
4. **Frontend:** adicionar a constante em `PERMISSIONS` e o gate `permissions:[...]` no
   item de nav.
5. **Deploy:** `create_default_roles --overwrite --schema <tenant>` por tenant (ver §8).

## 8. Deploy / propagação

`DEFAULT_ROLES` é o molde. Papéis **já provisionados** por tenant não recebem permissões
novas automaticamente — é preciso materializar:

```bash
python manage.py create_default_roles --schema <tenant> --overwrite
```

- Rode **por tenant** após qualquer mudança em `DEFAULT_ROLES`.
- **Admin não quebra** se você esquecer: `HasPermission`/split bypassam via
  `role_has_admin_capability` (o admin tem `"admin"` na lista). O `--overwrite` só
  materializa as strings explícitas. Papéis não-admin ficam bloqueados imediatamente
  (não têm a permissão nem `"admin"`).

## 9. Anti-padrões (não faça)

- ❌ Gatear só em `ModuleRequiredPermission` dado sensível (bug Concessão).
- ❌ Autorizar por `role.name == "admin"` (forjável — A01). Use `role_has_admin_capability`.
- ❌ Adicionar permissão nova a `ADMIN_PERMISSIONS` **e** a papéis clínicos "por garantia".
- ❌ Confiar no gate de UI como segurança. Backend é a verdade.
- ❌ `is_superuser=True` pra operador de SaaS. Use a política `is_platform_admin`.
- ❌ Endpoint sem nenhum gate de permissão além de `IsAuthenticated`.

## 10. Auditoria contínua

Varredura recomendada (a mesma classe de bug pode existir em outros apps):

```bash
# viewsets que gateiam SÓ em módulo/IsAuthenticated, sem HasPermission:
grep -rnE 'permission_classes' backend/apps/*/views*.py \
  | grep -viE 'HasPermission|HasConcessionAccess|IsTenantAdmin|IsPlatformAdmin|HasRole'
```

Todo hit que exponha dado sensível sem permissão de papel é candidato a correção
(módulo + permissão, como §5).
