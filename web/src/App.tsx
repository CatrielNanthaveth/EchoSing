import { Link, Route, Routes } from "react-router";

import { NotFoundPage } from "./pages/NotFoundPage";

export function App() {
  return (
    <div className="app">
      <header className="app-header">
        <Link to="/" className="brand">
          EchoSing
        </Link>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<p className="muted">Catálogo próximamente.</p>} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>
    </div>
  );
}
