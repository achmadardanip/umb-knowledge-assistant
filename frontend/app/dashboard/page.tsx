import { SystemDashboard } from "../components/SystemDashboard";

// Phase 19 P19.3 — operations / monitoring dashboard route (/dashboard).
export default function DashboardPage() {
  return (
    <main className="min-h-screen bg-background text-foreground">
      <SystemDashboard />
    </main>
  );
}
