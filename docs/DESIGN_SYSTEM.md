# Vitali — Convenção de Identidade Visual

> Fonte da verdade: `frontend/tailwind.config.ts` (tokens `neu.*` + `shadow-neu-*`) e `frontend/app/globals.css`
> (classes utilitárias + tokens shadcn em `hsl(var(--*))`). Telas **não rolam wrapper/estilo à mão** — usam os tokens e
> os componentes base de `components/shared/`. Estética: **neumorfismo corporativo de saúde** — superfícies claras
> escavadas/elevadas, azul corporativo, densidade de dashboard operacional.

## 1. Paleta (`neu.*` — namespace principal)

### Superfícies (fundo, do mais escuro pro mais claro)
| Token | Hex | Uso |
|---|---|---|
| `neu-app` | `#DFE5EB` | Base da aplicação (fundo raiz) |
| `neu-outer` | `#EBF0F5` | Container externo neumórfico |
| `neu-panel` | `#F4F7FA` | Painéis / área de conteúdo |
| `neu-panelAlt` | `#F8FAFC` | Variação clara de painel |
| `neu-input` | `#E8EDF2` | Fundo **escavado** de inputs |

### Texto (tinta)
| Token | Hex | Uso |
|---|---|---|
| `neu-ink` | `#24292F` | Texto principal |
| `neu-inkSoft` | `#57606A` | Secundário / labels |
| `neu-inkMuted` | `#8C959F` | Desabilitado / placeholder |

### Marca + semânticas
| Token | Hex | Uso |
|---|---|---|
| `neu-brand` | `#0066A1` | Azul corporativo — CTAs, branding |
| `neu-brandDeep` | `#005282` | Fim do gradiente primário |
| `neu-brandEdge` | `#3385b5` | Border-top dos botões primários |
| `neu-success` | `#2DA44E` | Verde — ok/concluído |
| `neu-warning` | `#9A6700` | Âmbar — atenção |
| `neu-danger` | `#CF222E` | Vermelho — erro/crítico |
| `neu-dangerDeep` / `neu-dangerEdge` | `#A61B25` / `#D94E58` | Gradiente/borda de botões danger |

> Escala `brand.50→900` (azul, `#eff6ff`…`#1e3a5f`) e os tokens shadcn (`background`/`primary`/`accent`/`muted`/…
> via `hsl(var(--*))`) existem para primitivos shadcn; **a UI de produto usa `neu.*`**.

## 2. Tipografia
- **Sans**: `Inter` (system-ui fallback) — corpo e títulos.
- **Mono**: `JetBrains Mono` — códigos, ids, valores tabulares.
- **Labels**: `uppercase`, `font-bold`, `text-[11px]`, `tracking-wide`, cor `neu-inkSoft` (classe `.neu-label`).
- Corpo padrão em `text-xs`/`text-sm` (densidade operacional). `body` = `font-sans antialiased`.

## 3. Forma & elevação
- **Raio**: `--radius: 0.5rem` → `rounded-lg` (lg) / `md` (`-2px`) / `sm` (`-4px`); painéis usam `rounded-xl`.
- **Sombras neumórficas** (`shadow-neu-*`):
  - `neu-inset` — escavado (inputs).
  - `neu-btn` — botão secundário (leve relevo).
  - `neu-btn-primary` / `-hover` — CTA azul com glow.
  - `neu-btn-danger` / `-hover` — CTA vermelho.
  - `neu-panel` — painel (inset claro + sombra suave + `border border-white`).
  - `neu-elevated` — card elevado.
  - `neu-modal` — modal.

## 4. Classes utilitárias (`globals.css`) — use, não recrie
| Classe | O que é |
|---|---|
| `.neu-input` | Input escavado (`h-8`, `bg-neu-input`, `shadow-neu-inset`, foco `ring-neu-brand/50` + fundo branco) |
| `.neu-label` | Label uppercase/bold/11px |
| `.neu-btn-primary` | CTA azul (gradiente `neu-brand→neu-brandDeep`, border-top `neu-brandEdge`) |
| `.neu-btn-secondary` | Botão secundário (`bg-neu-input`, `shadow-neu-btn`) |
| `.neu-panel` | Painel de conteúdo (`bg-neu-panel`, `rounded-xl`, `shadow-neu-panel`) |

## 5. Componentes base (`components/shared/`) — obrigatórios, não hand-roll
- **`PageShell`** `variant`: `workbench` (telas de trabalho) | `operational` (dashboards/filas full-bleed). Toda tela escolhe um variant; ninguém escreve o wrapper na mão.
- **`SectionState`** — estados vazio/loading/erro. `tone`: `neutral | success | warning | critical`. **Regra: o texto de status é obrigatório e explícito** — o `tone` só reforça a cor, nunca substitui a mensagem.
- **`StatusBadge`** — a pílula bordada de status de workflow. Rótulo vem de `lib/operational-ui` (ex.: `appointmentBadgeLabel(status, status_display)` — canônico pra status conhecido, display do servidor só pra desconhecido). **Nunca** jogar `status_display` cru direto.
- **`Badge`** — label autônomo (não-status). `variant`: `neutral | brand | success | warning | danger`.
- **`KpiTile`** — bloco de KPI (dashboards/censo/ocupação).
- **`RemoteCombobox`** — autocomplete remoto paginado/debounced (pickers de paciente/profissional/etc.).

## 6. Regras de uso (convenção)
1. **pt-BR** em toda copy de UI.
2. **Cor semântica** = `success`/`warning`/`danger` (separada da marca `brand`); não usar a marca pra significar estado.
3. **Status sempre em texto** — a cor acompanha, não carrega sozinha o significado (acessibilidade).
4. **Não relabelar status canônico** — passar sempre pelo `lib/operational-ui`.
5. **Tokens, não hex solto** — usar `neu-*` (e `shadow-neu-*`), nunca cores cruas nos componentes.
6. **Dark mode** por classe (`darkMode: ["class"]`) via tokens shadcn; a camada `neu.*` é o tema claro corporativo.
7. **Densidade operacional** — `text-xs`/`text-sm`, `h-8` em inputs, tabelas/filas priorizam scan; números alinhados com `tabular-nums` quando em coluna.

## 7. Aplicação nos módulos novos (referência)
- **Mapa de leitos** (`/internacao`) e **mapa cirúrgico** (`/centro-cirurgico`): células coloridas por **status** via mapa de meta (`*_STATUS_META`), acento de **prioridade** só como reforço; KPIs via `KpiTile`; ações gated por permissão (`canSee`/`hasPermission` de `lib/permissions.ts`).
- Estados sempre por `SectionState`; pílulas de status por `StatusBadge`; formulários com `.neu-input`/`.neu-label` e CTAs `.neu-btn-primary`/`.neu-btn-secondary`.
