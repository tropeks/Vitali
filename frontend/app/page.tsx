export default function Home() {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center bg-background">
      <div className="text-center space-y-4">
        <div className="flex items-center justify-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-brand-600 flex items-center justify-center">
            <span className="text-white font-bold text-lg">H</span>
          </div>
          <h1 className="text-3xl font-bold text-foreground">HealthOS</h1>
        </div>
        <p className="text-muted-foreground text-lg max-w-md">
          Plataforma Hospitalar SaaS · ERP + EMR + AI
        </p>
        <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-secondary">
            <span className="w-2 h-2 rounded-full bg-green-500" />
            Sprint 0 — Foundation
          </span>
        </div>
      </div>
    </main>
  );
}
