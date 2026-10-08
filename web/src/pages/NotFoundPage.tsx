import { Link } from "react-router";

export function NotFoundPage() {
  return (
    <section className="empty-state">
      <h1>Página no encontrada</h1>
      <Link to="/">Volver al catálogo</Link>
    </section>
  );
}
