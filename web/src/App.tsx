import { Link, NavLink, Route, Routes } from "react-router";

import { AdminSessionPage } from "./pages/AdminSessionPage";
import { CalibrationPage } from "./pages/CalibrationPage";
import { CatalogPage } from "./pages/CatalogPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ResultsPage } from "./pages/ResultsPage";
import { SongPage } from "./pages/SongPage";

export function App() {
  return (
    <div className="app">
      <header className="app-header">
        <Link to="/" className="brand">
          EchoSing
        </Link>
        <nav className="app-nav">
          <NavLink to="/calibrar">Calibrar latencia</NavLink>
        </nav>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<CatalogPage />} />
          <Route path="/songs/:songId" element={<SongPage />} />
          <Route path="/sessions/:sessionId/results" element={<ResultsPage />} />
          <Route path="/calibrar" element={<CalibrationPage />} />
          <Route path="/admin/sesiones/:sessionId" element={<AdminSessionPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>
    </div>
  );
}
