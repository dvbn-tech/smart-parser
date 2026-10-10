import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api, type ParserStatus } from "./api";
import { Freshness, ToastHost } from "./components/ui";
import AccountPage from "./pages/Account";
import AnomaliesPage from "./pages/Anomalies";
import BrandPage from "./pages/Brand";
import BrandsPage from "./pages/Brands";
import CandidatesPage from "./pages/Candidates";
import CreatorsPage from "./pages/Creators";
import InsightsPage from "./pages/Insights";
import OverviewPage from "./pages/Overview";
import ParserPage from "./pages/Parser";
import "./styles.css";

const client = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: true, retry: 1 } },
});

function Side() {
  const status = useQuery({ queryKey: ["parser"], queryFn: () => api.get<ParserStatus>("/parser/status"), refetchInterval: 60_000 });
  const cand = useQuery({ queryKey: ["candidates", ""], queryFn: () => api.get<unknown[]>("/candidates") });
  const s = status.data?.summary;
  const problems = s ? s.failed_24h + s.quarantine + s.invalid_24h : 0;
  const { search } = useLocation();
  // период и фильтры переносятся между экранами (F-13)
  const keep = new URLSearchParams(search).get("days");
  const q = keep ? `?days=${keep}` : "";
  return (
    <aside className="side">
      <div className="brandmark">
        Аномалии конкурентов
        <span>Reels · бренды и креаторы</span>
      </div>
      <nav className="nav stack" style={{ gap: 2 }}>
        <NavLink to={`/${q}`} end>Обзор</NavLink>
        <NavLink to={`/creators${q}`}>Креаторы</NavLink>
        <NavLink to={`/anomalies${q}`}>Аномалии</NavLink>
        <NavLink to="/insights">Что работает</NavLink>
        <NavLink to="/brands">Бренды и креаторы</NavLink>
        <NavLink to="/candidates">
          Кандидаты {cand.data && cand.data.length > 0 && <span className="count">{cand.data.length}</span>}
        </NavLink>
        <NavLink to="/parser">
          Парсер {problems > 0 && <span className="count" style={{ background: "var(--crit-bg)", color: "var(--crit-ink)" }}>{problems}</span>}
        </NavLink>
      </nav>
      <div className="side-foot stack" style={{ gap: 6 }}>
        <Freshness at={status.data?.data_as_of} />
        {s && <span>Покрытие за сутки: {s.coverage === null ? "—" : `${Math.round(s.coverage * 100)}%`}</span>}
      </div>
    </aside>
  );
}

function App() {
  return (
    <div className="app">
      <Side />
      <main className="main">
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/anomalies" element={<AnomaliesPage />} />
          <Route path="/creators" element={<CreatorsPage />} />
          <Route path="/insights" element={<InsightsPage />} />
          <Route path="/brands" element={<BrandsPage />} />
          <Route path="/brands/:id" element={<BrandPage />} />
          <Route path="/candidates" element={<CandidatesPage />} />
          <Route path="/accounts/:userPk" element={<AccountPage />} />
          <Route path="/parser" element={<ParserPage />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </main>
      <ToastHost />
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
