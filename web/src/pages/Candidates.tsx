import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type Brand, type Candidate } from "../api";
import { Empty, ErrorBox, Loading, toast, useParam } from "../components/ui";
import { EVIDENCE_LABEL, fmtCompact, fmtDate } from "../format";

const LEVEL = {
  confirmed: { label: "Confirmed", cls: "good" },
  likely: { label: "Likely", cls: "warn" },
  possible: { label: "Possible", cls: "" },
} as const;

export default function CandidatesPage() {
  const qc = useQueryClient();
  const [brand, setBrand] = useParam("brand", "");
  const [status, setStatus] = useParam("status", "candidate");
  const brands = useQuery({ queryKey: ["brands"], queryFn: () => api.get<Brand[]>("/brands") });
  const list = useQuery({
    queryKey: ["candidates", brand, status],
    queryFn: () => api.get<Candidate[]>(`/candidates?status=${status}${brand ? `&brand_id=${brand}` : ""}`),
  });
  const decide = useMutation({
    mutationFn: ({ c, action }: { c: Candidate; action: "approve" | "hide" }) => api.post(`/candidates/${c.brand_id}/${c.user_pk}/${action}`),
    onSuccess: (_, { c, action }) => {
      toast(action === "approve" ? `@${c.username} добавлен к ${c.brand_name}, загружается вся история роликов` : `@${c.username} скрыт. Вернётся, только если появится сильный сигнал (≥ 50)`);
      qc.invalidateQueries();
    },
    onError: (e) => toast(e.message),
  });

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="head">
        <div>
          <h1>Кандидаты в креаторы</h1>
          <div className="sub">Аккаунты, где система нашла признаки связи с брендом: партнёрство, collab, отметки, хэштеги, название бренда в профиле</div>
        </div>
        <div className="row">
          <select value={brand} onChange={(e) => setBrand(e.target.value || null)} aria-label="Бренд">
            <option value="">Все бренды</option>
            {brands.data?.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
          <div className="seg">
            <button className={status === "candidate" ? "on" : ""} onClick={() => setStatus("candidate")}>Новые</button>
            <button className={status === "hidden" ? "on" : ""} onClick={() => setStatus("hidden")}>Скрытые</button>
          </div>
        </div>
      </div>

      <div className="notice">
        Уверенность = сумма весов сигналов / 100: партнёрство 60, collab 50, артикул 30, отметка 25, бренд в нике или био 20, хэштег 15.
        Confirmed ≥ 0,9 · Likely 0,6–0,89 · Possible &lt; 0,6. «Добавить» запускает загрузку всей истории роликов.
      </div>

      {list.isLoading && <Loading h={240} />}
      {list.error && <ErrorBox error={list.error} />}
      {list.data && list.data.length === 0 && <Empty>{status === "candidate" ? "Новых кандидатов нет." : "Скрытых нет."}</Empty>}
      {list.data && list.data.length > 0 && (
        <div className="stack" style={{ gap: 10 }}>
          {list.data.map((c) => {
            const lv = c.level ? LEVEL[c.level] : null;
            const conf = c.confidence === null ? 0 : Number(c.confidence);
            return (
              <div key={`${c.brand_id}-${c.user_pk}`} className="card" style={{ display: "grid", gridTemplateColumns: "minmax(200px, 1.2fr) minmax(160px, 0.8fr) minmax(220px, 2fr) auto", gap: 16, alignItems: "center" }}>
                <div className="stack" style={{ gap: 2 }}>
                  <Link to={`/accounts/${c.user_pk}`} style={{ fontWeight: 600 }}>@{c.username}</Link>
                  <span className="small muted">{c.full_name ?? ""}{c.followers ? ` · ${fmtCompact(c.followers)} подписчиков` : ""}</span>
                  <span className="small"><span className="tag">{c.brand_name}</span> <span className="muted">найден {fmtDate(c.first_seen)}</span></span>
                </div>
                <div className="stack" style={{ gap: 6 }}>
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    {lv && <span className={`tag ${lv.cls}`}>{lv.label}</span>}
                    <span className="num small">{conf.toFixed(2)}</span>
                  </div>
                  <div className="bar" aria-hidden><i style={{ width: `${conf * 100}%` }} /></div>
                </div>
                <div className="evidence">
                  {c.evidence.map((e, i) => (
                    <span key={i} className="tag" title={e.value}>
                      {EVIDENCE_LABEL[e.kind] ?? e.kind} <b>+{e.weight}</b>
                    </span>
                  ))}
                </div>
                <div className="row">
                  <button className="primary" disabled={decide.isPending} onClick={() => decide.mutate({ c, action: "approve" })}>Добавить</button>
                  {status === "candidate" && <button disabled={decide.isPending} onClick={() => decide.mutate({ c, action: "hide" })}>Скрыть</button>}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
