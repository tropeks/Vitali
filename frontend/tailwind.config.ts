import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./pages/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./app/**/*.{ts,tsx}",
    "./src/**/*.{ts,tsx}",
  ],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: { "2xl": "1400px" },
    },
    extend: {
      colors: {
        // HealthOS brand — clinical blue + clean white
        brand: {
          50:  "#eff6ff",
          100: "#dbeafe",
          500: "#3b82f6",
          600: "#2563eb",
          700: "#1d4ed8",
          900: "#1e3a5f",
        },
        // Tasy Neumorphic token layer — valores canônicos em docs/FRONTEND_GUIDELINES.md
        neu: {
          app: "#DFE5EB",      // App background (base da aplicação)
          outer: "#EBF0F5",    // Main container / outer neumorphic
          panel: "#F4F7FA",    // Painéis / content area
          panelAlt: "#F8FAFC", // Variação clara de painel
          input: "#E8EDF2",    // Fundo escavado de inputs
          ink: "#24292F",      // Texto principal
          inkSoft: "#57606A",  // Texto secundário / labels
          inkMuted: "#8C959F", // Texto desabilitado
          brand: "#0066A1",    // Corporate blue (CTAs, branding)
          brandDeep: "#005282", // Fim do gradiente primário
          brandEdge: "#3385b5", // Border-top dos botões primários
          success: "#2DA44E",
          warning: "#9A6700",  // Âmbar de atenção (Primer attention fg, harmoniza com success/danger)
          danger: "#CF222E",
          dangerDeep: "#A61B25", // Fim do gradiente danger (danger ×0.8, como brandDeep deriva de brand)
          dangerEdge: "#D94E58", // Border-top dos botões danger (danger +20% branco, como brandEdge)
        },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
      },
      boxShadow: {
        // Sombras Tasy Neumorphic — composições exatas de docs/FRONTEND_GUIDELINES.md
        "neu-inset": "inset 0 2px 4px rgba(0,0,0,0.06)",
        "neu-btn": "inset 0 1px 1px rgba(255,255,255,0.5), 0 2px 4px rgba(0,0,0,0.05)",
        "neu-btn-primary": "0 3px 10px rgba(0,102,161,0.3)",
        "neu-btn-primary-hover": "0 5px 15px rgba(0,102,161,0.4)",
        "neu-btn-danger": "0 3px 10px rgba(207,34,46,0.3)",
        "neu-btn-danger-hover": "0 5px 15px rgba(207,34,46,0.4)",
        "neu-panel": "inset 0 1px 2px rgba(255,255,255,0.8), 0 2px 8px rgba(0,0,0,0.03)",
        "neu-elevated": "0 10px 30px rgba(0,0,0,0.1), inset 0 2px 4px rgba(255,255,255,0.8)",
        "neu-modal": "0 20px 50px rgba(0,0,0,0.2), inset 0 2px 4px rgba(255,255,255,0.8)",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
