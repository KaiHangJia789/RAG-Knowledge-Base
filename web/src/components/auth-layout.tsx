import Link from "next/link";
import type { ReactNode } from "react";

export function AuthLayout({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="auth-title" style={{ display: "grid", gap: 28 }}>
        <header style={{ display: "grid", gap: 28 }}>
          <Link href="/" className="auth-brand-link" style={{ display: "inline-flex", alignItems: "center", gap: 10, justifySelf: "start" }}>
            <span className="auth-brand" aria-hidden="true">知</span>
            <span>知序 · RAG</span>
          </Link>
          <div style={{ display: "grid", gap: 8 }}>
            <h1 id="auth-title" className="page-heading">{title}</h1>
            <p className="muted">{subtitle}</p>
          </div>
        </header>
        {children}
      </section>
    </main>
  );
}
