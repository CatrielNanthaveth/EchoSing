import { Link, Route, Routes } from "react-router";

import { CatalogPage } from "./pages/CatalogPage";
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
          <Route path="/" element={<CatalogPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>
    </div>
  );
}
