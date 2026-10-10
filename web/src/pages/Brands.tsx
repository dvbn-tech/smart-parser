import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, type Brand } from "../api";
import { Empty, ErrorBox, Loading, SortTable, toast } from "../components/ui";
import { fmtInt } from "../format";

interface ImportRow {
  line: number;
  status: string;
  username?: string;
  message?: string;
}

export default function BrandsPage() {
  const qc = useQueryClient();
  const brands = useQuery({ queryKey: ["brands"], queryFn: () => api.get<Brand[]>("/brands") });
  const [form, setForm] = useState({ name: "", instagram: "", hashtags: "", is_own: false });
  const [report, setReport] = useState<ImportRow[] | null>(null);

  const create = useMutation({
    mutationFn: () =>
      api.post<{ id: number; shop: { status: string } | null }>("/brands", {
        name: form.name.trim(),
        instagram: form.instagram.trim() || null,
        hashtags: form.hashtags.split(/[\s,]+/).filter(Boolean),
        is_own: form.is_own,
      }),
    onSuccess: (r) => {
      toast(r.shop?.status === "queued" ? "Бренд добавлен. Аккаунт поставлен в очередь: парсер найдёт его и привяжет." : "Бренд добавлен");
      setForm({ name: "", instagram: "", hashtags: "", is_own: false });
      qc.invalidateQueries();
    },
    onError: (e) => toast(e.message),
  });

  const upload = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return api.post<{ rows: ImportRow[] }>("/import", fd);
    },
    onSuccess: (r) => {
      setReport(r.rows);
      qc.invalidateQueries();
    },
    onError: (e) => toast(e.message),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (form.name.trim()) create.mutate();
  };

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="head">
        <div>
          <h1>Бренды и креаторы</h1>
          <div className="sub">Список 1 — бренды (конкуренты и наш). Креаторов бренда система находит сама; их можно добавить и вручную.</div>
        </div>
      </div>

      <div className="card flush">
        {brands.isLoading && <div style={{ padding: 16 }}><Loading /></div>}
        {brands.error && <div style={{ padding: 16 }}><ErrorBox error={brands.error} /></div>}
        {brands.data && brands.data.length === 0 && <Empty>Брендов пока нет — добавьте первый ниже или загрузите CSV.</Empty>}
        {brands.data && brands.data.length > 0 && (
          <SortTable<Brand>
            rows={brands.data}
            rowKey={(b) => b.id}
            columns={[
              { key: "name", label: "Бренд", sort: (b) => b.name, render: (b) => <span className="row" style={{ gap: 8 }}><Link to={`/brands/${b.id}`} style={{ fontWeight: 600 }}>{b.name}</Link>{b.is_own && <span className="tag own">наш</span>}</span> },
              {
                key: "shop",
                label: "Официальный аккаунт",
                render: (b) =>
                  b.shop_username ? (
                    <Link to={`/accounts/${b.shop_user_pk}`}>@{b.shop_username}</Link>
                  ) : b.pending_shop ? (
                    <span className="ink2">@{b.pending_shop} <span className="tag warn">ждёт сбора</span></span>
                  ) : (
                    <span className="muted">не указан</span>
                  ),
              },
              { key: "tags", label: "Хэштеги", render: (b) => <span className="ink2">{b.hashtags.map((t) => `#${t}`).join(" ") || "—"}</span> },
              { key: "creators", label: "Креаторов", right: true, sort: (b) => b.creators ?? 0, render: (b) => fmtInt(b.creators) },
              { key: "pending", label: "Ждут сбора", right: true, title: "аккаунты из списка, по которым ещё не собран профиль", sort: (b) => b.pending ?? 0, render: (b) => (b.pending ? <span className="tag warn">{b.pending}</span> : <span className="muted">0</span>) },
              { key: "masks", label: "Маски ников", render: (b) => <span className="ink2 small">{(b.username_masks ?? []).join("  ") || "—"}</span> },
              { key: "cand", label: "Кандидатов", right: true, sort: (b) => b.candidates ?? 0, render: (b) => (b.candidates ? <Link to={`/candidates?brand=${b.id}`}>{b.candidates}</Link> : <span className="muted">0</span>) },
              { key: "thr", label: "Порог всплеска", right: true, render: (b) => `${fmtInt(b.spike_min_views)} просм.` },
            ]}
          />
        )}
      </div>

      <div className="grid2">
        <form className="card stack" style={{ gap: 12 }} onSubmit={submit}>
          <h2>Добавить бренд</h2>
          <label className="field">Название<input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="WAISTLINE" /></label>
          <label className="field">Официальный аккаунт в Instagram<input value={form.instagram} onChange={(e) => setForm({ ...form, instagram: e.target.value })} placeholder="ссылка или @ник" /></label>
          <label className="field">Хэштеги бренда<input value={form.hashtags} onChange={(e) => setForm({ ...form, hashtags: e.target.value })} placeholder="waistline wline" /></label>
          <label className="check"><input type="checkbox" checked={form.is_own} onChange={(e) => setForm({ ...form, is_own: e.target.checked })} /> Это наш бренд</label>
          <div><button className="primary" disabled={create.isPending}>{create.isPending ? "Сохраняю…" : "Добавить"}</button></div>
        </form>

        <div className="card stack" style={{ gap: 12 }}>
          <h2>Загрузить из CSV</h2>
          <div className="hint">
            Колонки: <code>brand</code>, <code>is_own</code>, <code>instagram</code>, <code>role</code> (<code>shop</code> или <code>creator</code>), <code>hashtags</code>, <code>own_creator</code>. Разделитель — запятая или точка с запятой.
            Ник вместо user_pk достаточно: система сама найдёт аккаунт.
          </div>
          <pre className="small" style={{ margin: 0, background: "var(--surface-2)", padding: 10, borderRadius: 8, overflowX: "auto" }}>
{`brand;is_own;instagram;role;hashtags;own_creator
WAISTLINE;0;waistline_shop;shop;waistline wline;
WAISTLINE;0;https://instagram.com/anna_k;creator;;
Munique Base;1;munique.base_;shop;muniquebase;
Munique Base;1;@our_creator;creator;;1`}
          </pre>
          <label className="btn" style={{ alignSelf: "flex-start" }}>
            {upload.isPending ? "Загружаю…" : "Выбрать файл"}
            <input type="file" accept=".csv,text/csv" hidden onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])} />
          </label>
          {report && (
            <div className="stack" style={{ gap: 4 }}>
              <div className="small">
                Строк: {report.length} · привязано: {report.filter((r) => r.status === "linked").length} · в очереди: {report.filter((r) => r.status === "queued").length} · ошибок: {report.filter((r) => r.status === "error").length}
              </div>
              {report.filter((r) => r.status === "error").map((r) => (
                <div key={r.line} className="small" style={{ color: "var(--bad)" }}>строка {r.line}: {r.message}</div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
