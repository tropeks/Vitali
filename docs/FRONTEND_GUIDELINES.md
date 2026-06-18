# Vitali EMR - Frontend Guidelines & Design System

Este documento define a arquitetura visual, estrutural e as diretrizes de código para o Frontend do Vitali EMR. Todos os novos módulos, componentes e páginas devem aderir estritamente a estas regras para manter a consistência com a identidade **Tasy Neumorphic**.

---

## 1. Identidade Visual (Tasy Neumorphic)

A interface do Vitali foi desenhada para altíssima densidade de dados e produtividade extrema (estilo ERP Médico Corporativo), combinada com dicas visuais premium (Neumorfismo Suave) para reduzir a fadiga ocular.

### 1.1 Cores Principais (Tailwind Palette)
- **Primary Brand (Corporate Blue):** `#0066A1` (Utilizado para CTAs primários, cabeçalhos, steps ativos e branding).
  - Variações: `from-[#0066A1] to-[#005282]` para gradientes suaves em botões primários.
- **Success (Green):** `#2DA44E` (Utilizado para confirmações e status positivos).
- **Destructive/Error (Red):** `#CF222E` (Utilizado para deletar dados e alertas críticos).
- **Backgrounds (Estrutura):**
  - **App Background:** `#DFE5EB` (Cinza-azulado sólido, base da aplicação).
  - **Main Container / Outer Neumorphic:** `#EBF0F5` (Onde flutuam os contêineres principais).
  - **Panels / Content Area:** `#F8FAFC` ou `#F4F7FA` (Áreas de conteúdo denso e tabelas).
  - **Input Background:** `#E8EDF2` (Cinza escavado para gerar o efeito de relevo interno).
- **Typography:**
  - Textos Principais: `#1f2937` ou `#24292F`.
  - Textos Secundários / Labels: `#57606A`.
  - Textos Desabilitados: `#8C959F`.

### 1.2 Estilo Neumórfico (Sombras e Relevos)
O visual premium é alcançado através de sombras precisas (box-shadows) para simular materiais "esculpidos".
- **Inputs e Áreas de "Escavação" (Inner Shadows):**
  - `shadow-[inset_0_2px_4px_rgba(0,0,0,0.06)]` (Usado em inputs, selects e textareas vazados).
- **Botões e Cartões Interativos (Outer Shadows Soft):**
  - Secundários: `shadow-[inset_0_1px_1px_rgba(255,255,255,0.5),_0_2px_4px_rgba(0,0,0,0.05)]`.
  - Primários: `shadow-[0_3px_10px_rgba(0,102,161,0.3)]`.
- **Painéis Maiores (Elevação Estrutural):**
  - Elevado: `shadow-[0_10px_30px_rgba(0,0,0,0.1),_inset_0_2px_4px_rgba(255,255,255,0.8)]`.

### 1.3 Densidade e Tipografia
O Vitali é uma ferramenta de trabalho. A informação precisa ser densa.
- **Fontes Base:** Familia `sans` padrão (Inter, Roboto ou system-fonts).
- **Tamanhos Base:** `text-xs` (12px) e `text-sm` (14px). **Não utilize textos maiores que `text-base`**, exceto para cabeçalhos de altíssimo nível.
- **Paddings e Margens:** Extremamente controlados.
  - Inputs: `px-2 py-1.5 h-8`.
  - Botões Secundários: `px-4 py-1.5 h-8`.
- **Bordas:** Majoritariamente `rounded-md` ou `rounded-lg`. Não utilize `rounded-full` ou `rounded-2xl` excessivamente para não passar impressão de aplicativo B2C infantil.

---

## 2. Componentes e Classes Tailwind Base

### Inputs & Selects
Todo input e select deve utilizar esta base de classes para garantir o efeito neumórfico escavado:
```tsx
const inputClasses = "w-full px-2 py-1.5 bg-[#E8EDF2] border-transparent rounded-md text-xs shadow-[inset_0_2px_4px_rgba(0,0,0,0.06)] focus:outline-none focus:bg-white focus:ring-2 focus:ring-[#0066A1]/50 transition-all h-8 text-[#24292F]"
```

### Labels
```tsx
const labelClasses = "block text-[11px] font-bold text-[#57606A] mb-1.5 uppercase tracking-wide"
```

### Botões Primários (Salvar, Avançar)
```tsx
<button className="px-6 py-2 text-xs font-bold text-white bg-gradient-to-b from-[#0066A1] to-[#005282] rounded-lg border-t border-[#3385b5] shadow-[0_3px_10px_rgba(0,102,161,0.3)] hover:shadow-[0_5px_15px_rgba(0,102,161,0.4)] transition-all">
  Ação Primária
</button>
```

### Botões Secundários (Cancelar, Voltar, Opções)
```tsx
<button className="px-4 py-1.5 text-xs rounded-lg font-bold bg-[#E8EDF2] text-[#57606A] shadow-[inset_0_1px_1px_rgba(255,255,255,0.5),_0_2px_4px_rgba(0,0,0,0.05)] hover:bg-[#dfe5ea] transition-all">
  Ação Secundária
</button>
```

### Painéis Internos e Cartões de Conteúdo
```tsx
<div className="bg-[#F4F7FA] p-4 rounded-xl shadow-[inset_0_1px_2px_rgba(255,255,255,0.8),_0_2px_8px_rgba(0,0,0,0.03)] border border-white">
  {/* Conteúdo denso e grids aqui */}
</div>
```

---

## 3. Padrões de Layout

### Grids Responsivos
Utilize estritamente CSS Grid (`grid-cols-12`) para formulários complexos. Evite empilhar inputs verticais (Flexbox column) em telas largas, aproveite a largura da tela para densidade.
```tsx
<div className="grid grid-cols-12 gap-4">
  <div className="col-span-12 md:col-span-4"> Input 1 </div>
  <div className="col-span-12 md:col-span-4"> Input 2 </div>
  <div className="col-span-12 md:col-span-4"> Input 3 </div>
</div>
```

### Modais e Drawers
Devem saltar à frente da tela escura utilizando uma variação de borda e sombra mais agressiva para foco:
`bg-[#EBF0F5] shadow-[0_20px_50px_rgba(0,0,0,0.2),_inset_0_2px_4px_rgba(255,255,255,0.8)]`

---

## 4. Regras de Arquitetura Next.js

1. **Uso do `use client`:** Apenas em componentes na pasta `/components/` ou em views folha que dependam estritamente de interatividade React (useState, onClick, hooks). Páginas (`page.tsx`) de roteamento devem, por padrão, ser Server Components caso façam apenas fetcheamento.
2. **Icons:** Utilize sempre a biblioteca `lucide-react`. Tamanhos preferenciais: `size={14}` ou `size={16}` para alinhar com a densidade do texto base.
3. **Analytics:** Módulos chave e ações críticas devem disparar eventos utilizando `trackPilotEvent` localizado em `@/lib/analytics`.
4. **Fetch API:** Para interação com o backend Django, direcione para `/api/v1/...` que o rewrite do `next.config.js` fará o proxy automaticamente.

---

## 5. Exemplo de Referência
Para um exemplo completo "pixel-perfect" de como orquestrar esses elementos em uma View, refira-se ao arquivo `frontend/app/setup/page.tsx` que serve como o **Golden Standard** da arquitetura visual Tasy Neumorphic.
