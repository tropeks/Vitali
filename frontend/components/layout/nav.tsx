/**
 * Canonical domain-grouped navigation (UI_NAVIGATION_IA.md §2), extracted from
 * DashboardShell so the sidebar, the ⌘K command palette and the persona presets
 * all consume ONE source of truth.
 *
 * Each item carries its own visibility gate (`module` / `permissions` /
 * `superuser`) evaluated by {@link canSee} (see UI_NAVIGATION_IA.md §6). The menu
 * is UX only — the backend `permission_classes` remains the real barrier.
 */
import {
  LayoutDashboard,
  Users,
  Calendar,
  ClipboardList,
  Stethoscope,
  Activity,
  ScanLine,
  ScanBarcode,
  BedDouble,
  Scissors,
  FlaskConical,
  CalendarX,
  CalendarClock,
  Pill,
  PackageOpen,
  Receipt,
  BarChart2,
  Settings,
  Building2,
  Landmark,
  ShoppingCart,
  Server,
  BookMarked,
  Gauge,
  Fingerprint,
  CheckSquare,
} from "lucide-react";
import type { UserDTO } from "@/lib/auth";
import { PERMISSIONS, canSee, type NavGate } from "@/lib/permissions";

export interface NavItem extends NavGate {
  label: string;
  href: string;
  icon: React.ElementType;
  /** Sub-items rendered as an indented group beneath this item. */
  children?: { label: string; href: string }[];
}

export interface NavGroup {
  /** Domain label (pt-BR) — rendered as a collapsible section header. */
  label: string;
  items: NavItem[];
}

/**
 * Home launcher — always visible, outside the collapsible groups.
 */
export const HOME_ITEM: NavItem = {
  label: "Dashboard",
  href: "/dashboard",
  icon: LayoutDashboard,
};

/**
 * Domain-grouped navigation (UI_NAVIGATION_IA.md §2). Each item carries its own
 * visibility gate (`module` / `permissions` / `superuser`) evaluated by
 * {@link canSee}. `adminOnly` (role_name-based) is RETIRED — items now gate on a
 * real backend permission (see §6). Permissions come from `@/lib/permissions`.
 */
export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Atendimento",
    items: [
      {
        label: "Pacientes",
        href: "/patients",
        icon: Users,
        module: "emr",
        permissions: [PERMISSIONS.PATIENTS_READ, PERMISSIONS.PATIENTS_LIMITED_READ],
      },
      {
        label: "Agenda",
        href: "/appointments",
        icon: Calendar,
        module: "emr",
        permissions: [PERMISSIONS.SCHEDULE_READ],
        children: [{ label: "Lista de espera", href: "/appointments/waitlist" }],
      },
      {
        label: "Sala de Espera",
        href: "/waiting-room",
        icon: ClipboardList,
        module: "emr",
        permissions: [PERMISSIONS.EMR_READ, PERMISSIONS.SCHEDULE_READ],
      },
      {
        label: "Consultas",
        href: "/encounters",
        icon: Stethoscope,
        module: "emr",
        permissions: [PERMISSIONS.EMR_READ],
      },
      {
        label: "Deterioração",
        href: "/deterioracao",
        icon: Activity,
        module: "emr",
        permissions: [PERMISSIONS.EMR_READ],
      },
      {
        // BCMA bedside "5 certos" checagem (N5) — gated emar.administer
        // (técnico/enfermeiro à beira-leito). Backend EmarCheck is the real gate.
        label: "Checagem (MAR)",
        href: "/enfermagem/checagem",
        icon: ScanBarcode,
        module: "emr",
        permissions: [PERMISSIONS.EMAR_ADMINISTER],
      },
      {
        // Painel de Internação / mapa de leitos + censo (ADT L4). Gated beds.read;
        // ações de transferência/alta gated adt.* dentro do painel. Admissão pelo
        // prontuário (aba Internação, L5).
        label: "Internação",
        href: "/internacao",
        icon: BedDouble,
        module: "emr",
        permissions: [PERMISSIONS.BEDS_READ],
      },
      {
        // Mapa cirúrgico / Centro Cirúrgico (C4). Gated surgery.read; agendar/
        // confirmar/cancelar gated surgery.schedule dentro do painel. Fluxo intra-op
        // (checklist/tempos/equipe) pelo prontuário (aba Cirurgia, C5).
        label: "Centro Cirúrgico",
        href: "/centro-cirurgico",
        icon: Scissors,
        module: "emr",
        permissions: [PERMISSIONS.SURGERY_READ],
      },
      {
        label: "Faltas",
        href: "/faltas",
        icon: CalendarX,
        module: "emr",
        permissions: [PERMISSIONS.SCHEDULE_READ],
      },
    ],
  },
  {
    label: "Apoio Diagnóstico",
    items: [
      {
        label: "Laboratório",
        href: "/laboratorio",
        icon: FlaskConical,
        module: "emr",
        permissions: [PERMISSIONS.EMR_READ],
      },
      {
        label: "Vitali Imagem",
        href: "/imagens",
        icon: ScanLine,
        module: "imaging",
        permissions: [PERMISSIONS.IMAGING_READ],
      },
    ],
  },
  {
    label: "Pessoas & Operações",
    items: [
      {
        label: "RH",
        href: "/rh/funcionarios",
        icon: Users,
        module: "rh",
        // HRAccessPermission: admin capability OR hr.manage (apps/hr/views.py).
        permissions: [PERMISSIONS.HR_MANAGE, PERMISSIONS.ADMIN],
        children: [
          { label: "Funcionários", href: "/rh/funcionarios" },
          { label: "Lotação", href: "/rh/lotacoes" },
          { label: "Ponto", href: "/rh/ponto" },
          { label: "Afastamentos", href: "/rh/afastamentos" },
          { label: "ASO", href: "/rh/aso" },
          { label: "Cargos", href: "/rh/cargos" },
          { label: "Dependentes", href: "/rh/dependentes" },
        ],
      },
    ],
  },
  {
    // Supervisor/coordinator surface, scoped by unit — escala/plantão
    // ownership moved here from RH (UI_NAVIGATION_IA.md §3, S-IA2). RBAC gates
    // on `roster.manage`, with `hr.manage`/`admin` kept as transition
    // fallbacks until every tenant has roster.manage assigned.
    //
    // Future (S-IA2+, once their routes exist): Dimensionamento, Trocas &
    // folgas, Requisição de insumos, Indicadores (see UI_NAVIGATION_IA.md §2).
    label: "Painel de Setor",
    items: [
      {
        label: "Escalas",
        href: "/painel-setor/escalas",
        icon: CalendarClock,
        permissions: [PERMISSIONS.ROSTER_MANAGE, PERMISSIONS.HR_MANAGE, PERMISSIONS.ADMIN],
      },
    ],
  },
  {
    label: "Financeiro",
    items: [
      {
        label: "Faturamento",
        href: "/billing",
        icon: Receipt,
        module: "billing",
        permissions: [PERMISSIONS.BILLING_READ],
        children: [
          { label: "Guias", href: "/billing/guides" },
          { label: "Glosas", href: "/billing/glosas" },
          { label: "Lotes", href: "/billing/batches" },
          { label: "Tabelas de preço", href: "/billing/price-tables" },
        ],
      },
      {
        label: "Análise",
        href: "/billing/analytics",
        icon: BarChart2,
        module: "billing",
        permissions: [PERMISSIONS.BILLING_READ, PERMISSIONS.REPORTS_READ],
      },
      {
        label: "Financeiro",
        href: "/administracao/resultado-financeiro",
        icon: Landmark,
        // Contas a pagar/receber, DRE, conciliação — financial management.
        permissions: [PERMISSIONS.BILLING_FULL, PERMISSIONS.ADMIN],
        children: [
          { label: "Resultado (DRE)", href: "/administracao/resultado-financeiro" },
          { label: "Conciliação", href: "/administracao/conciliacao-financeira" },
          { label: "Contas a pagar", href: "/billing/contas-a-pagar" },
          { label: "Contas a receber", href: "/billing/contas-a-receber" },
          { label: "Tesouraria", href: "/billing/tesouraria" },
          { label: "Repasses médicos", href: "/billing/settlements" },
        ],
      },
    ],
  },
  {
    label: "Suprimentos & Farmácia",
    items: [
      {
        label: "Farmácia",
        href: "/farmacia",
        icon: Pill,
        module: "pharmacy",
        permissions: [PERMISSIONS.PHARMACY_READ],
        children: [
          { label: "Cockpit", href: "/farmacia" },
          { label: "Dispensar", href: "/farmacia/dispense" },
          { label: "Estoque", href: "/farmacia/stock" },
          { label: "Risco de estoque", href: "/farmacia/risco-estoque" },
          { label: "Catálogo", href: "/farmacia/catalog" },
          { label: "Compras", href: "/farmacia/compras" },
          { label: "Controlados", href: "/farmacia/controlados" },
        ],
      },
      {
        label: "Compras",
        href: "/administracao/compras",
        icon: ShoppingCart,
        permissions: [PERMISSIONS.PHARMACY_STOCK_MANAGE, PERMISSIONS.ADMIN],
        children: [{ label: "Entradas NF-e", href: "/administracao/compras/entradas-nfe" }],
      },
    ],
  },
  {
    label: "Concessão",
    items: [
      {
        label: "Concessão",
        href: "/concessao",
        icon: PackageOpen,
        module: "diagnostic_concession",
        children: [
          { label: "Ativos", href: "/concessao/ativos" },
          { label: "Contratos", href: "/concessao/contratos" },
          { label: "Logística", href: "/concessao/logistica" },
          { label: "Manutenção", href: "/concessao/manutencao" },
          { label: "P&L", href: "/concessao/pnl" },
        ],
      },
    ],
  },
  {
    label: "Administração",
    items: [
      {
        label: "Estrutura organizacional",
        href: "/administracao/organizacao",
        icon: Building2,
        permissions: [PERMISSIONS.ORGANIZATION_READ],
      },
      {
        label: "Identidade de pacientes",
        href: "/administracao/mpi",
        icon: Fingerprint,
        permissions: [PERMISSIONS.MPI_READ],
      },
      {
        label: "Aprovações",
        href: "/administracao/aprovacoes",
        icon: CheckSquare,
        permissions: [PERMISSIONS.WORKFLOW_READ, PERMISSIONS.WORKFLOW_APPROVE],
      },
      {
        label: "Configurações",
        href: "/configuracoes/assinatura",
        icon: Settings,
        permissions: [PERMISSIONS.ADMIN],
        children: [
          { label: "Assinatura", href: "/configuracoes/assinatura" },
          { label: "WhatsApp", href: "/configuracoes/whatsapp" },
          { label: "Inteligência Artificial", href: "/configuracoes/ai" },
          { label: "Profissionais", href: "/configuracoes/profissionais" },
          { label: "Formulário (doses)", href: "/configuracoes/farmacia/formulario" },
          { label: "Interações", href: "/configuracoes/farmacia/interacoes" },
          { label: "Suprimentos", href: "/configuracoes/farmacia/suprimentos" },
          { label: "Privacidade (LGPD)", href: "/configuracoes/privacidade" },
        ],
      },
    ],
  },
  {
    label: "Plataforma",
    items: [
      { label: "Tenants", href: "/platform/tenants", icon: Server, superuser: true },
      { label: "Terminologia", href: "/platform/terminology", icon: BookMarked, superuser: true },
      { label: "Monitor", href: "/platform/monitor", icon: Gauge, superuser: true },
      { label: "Valor (wedge)", href: "/platform/wedge-value", icon: BarChart2, superuser: true },
      { label: "Telemetria", href: "/wedges/telemetry", icon: Activity, superuser: true },
    ],
  },
];

/** A flattened, navigable destination for the command palette. */
export interface NavDestination {
  label: string;
  href: string;
}

/**
 * Flatten NAV_GROUPS to the destinations the current user can actually see,
 * reusing the SAME {@link canSee} gate as the sidebar (module + RBAC +
 * superuser). Children inherit their parent's visibility. HOME_ITEM is always
 * included. This is the command palette's "Navegação" source — it can never
 * surface anything the sidebar would hide.
 */
export function visibleNavDestinations(
  user: Pick<UserDTO, "permissions" | "is_superuser">,
  activeModules: string[] | null,
): NavDestination[] {
  const out: NavDestination[] = [{ label: HOME_ITEM.label, href: HOME_ITEM.href }];
  for (const group of NAV_GROUPS) {
    for (const item of group.items) {
      if (!canSee(user, item, activeModules)) continue;
      out.push({ label: item.label, href: item.href });
      for (const child of item.children ?? []) {
        out.push({ label: `${item.label} · ${child.label}`, href: child.href });
      }
    }
  }
  return out;
}
