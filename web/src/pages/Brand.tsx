import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type Brand, type CreatorRow, type MediaRow, type PendingAccount } from "../api";
import { Empty, ErrorBox, Loading, MediaCard, SortTable, toast } from "../components/ui";
import { LINK_LABEL, STATUS_LABEL, fmtAgo, fmtCompact, fmtInt, fmtRatio } from "../format";

export default function BrandPage() {
  const id = Number(useParams().id);
  const qc = useQueryClient();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["brand", id], queryFn: () => api.get<{ brand: Brand; creators: CreatorRow[]; pending: PendingAccount[] }>(`/brands/${id}`) });
  const top = useQuery({
    queryKey: ["anomalies", "brand", id],
    queryFn: () => api.get<{ items: MediaRow[] }>(`/anomalies?days=90&brand_id=${id}&limit=8`),
  });
  const [tab, setTab] = useState<"creators" | "settings">("creators");
  const [newCreator, setNewCreator] = useState({ instagram: "", own: false });

  const add = useMutation({
    mutationFn: () => api.post<{ status: string; username: string }>(`/brands/${id}/creators`, { instagram: newCreator.instagram, is_own_creator: newCreator.own }),
    onSuccess: (r) => {
      toast(r.status === "queued" ? `@${r.username} в очереди: после сбора профиля появится в списке и загрузится вся история` : `@${r.username} добавлен, загружается история роликов`);
      setNewCreator({ instagram: "", own: false });
      qc.invalidateQueries();
    },
    onError: (e) => toast(e.message),
  });
  const remove = useMutation({
    mutationFn: (pk: number) => api.del(`/brands/${id}/creators/${pk}`),
    onSuccess: () => {
      toast("Связь убрана, собранные данные сохранены");
      qc.invalidateQueries();
    },
  });

  if (q.isLoading) return <Loading h={400} />;
  if (q.error) return <ErrorBox error={q.error} />;
  if (!q.data) return null;
  const { brand, creators, pending } = q.data;
  const people = creators.filter((c) => c.role !== "shop");
  const shop = creators.find((c) => c.role === "shop");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (newCreator.instagram.trim()) add.mutate();
  };

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="head">
        <div>
          <div className="small"><Link to="/brands">← Бренды</Link></div>
          <h1 className="row" style={{ gap: 10, marginTop: 4 }}>{brand.name}{brand.is_own && <span className="tag own">наш бренд</span>}</h1>
          <div className="sub">
            {shop ? <>Официальный аккаунт <Link to={`/accounts/${shop.user_pk}`}>@{shop.username}</Link> · </> : "Официальный аккаунт не указан · "}
            {brand.hashtags.map((t) => `#${t}`).join(" ") || "хэштеги не заданы"}
          </div>
        </div>
        <div className="row">
          <Link className="btn" to={`/creators?brands=${id}&cols=all`}>Все показатели креаторов</Link>
          <Link className="btn" to={`/insights?brands=${id}`}>Что работает у бренда</Link>
          <Link className="btn" to={`/anomalies?brands=${id}&days=90`}>Аномалии бренда</Link>
          <Link className="btn" to={`/candidates?brand=${id}`}>Кандидаты</Link>
        </div>
      </div>

      <div className="tabs">
        <button className={tab === "creators" ? "on" : ""} onClick={() => setTab("creators")}>Креаторы ({people.length})</button>
        <button className={tab === "settings" ? "on" : ""} onClick={() => setTab("settings")}>Настройки</button>
      </div>

      {tab === "creators" && (
        <>
          <form className="card row" style={{ gap: 12, alignItems: "flex-end" }} onSubmit={submit}>
            <label className="field" style={{ flex: "1 1 260px" }}>
              Добавить креатора
              <input value={newCreator.instagram} onChange={(e) => setNewCreator({ ...newCreator, instagram: e.target.value })} placeholder="ссылка на Instagram или @ник" />
            </label>
            <label className="check"><input type="checkbox" checked={newCreator.own} onChange={(e) => setNewCreator({ ...newCreator, own: e.target.checked })} /> наш креатор</label>
            <button className="primary" disabled={add.isPending}>Добавить</button>
          </form>

          <div className="card flush">
            {people.length === 0 ? (
              <Empty>Креаторов пока нет. Добавьте вручную или подтвердите <Link to={`/candidates?brand=${id}`}>кандидатов</Link>.</Empty>
            ) : (
              <SortTable<CreatorRow>
                rows={people}
                rowKey={(c) => c.user_pk}
                initial="median"
                columns={[
                  {
                    key: "user",
                    label: "Креатор",
                    sort: (c) => c.username,
                    render: (c) => (
                      <span className="stack" style={{ gap: 2 }}>
                        <span className="row" style={{ gap: 6 }}>
                          <Link to={`/accounts/${c.user_pk}`} style={{ fontWeight: 600 }}>@{c.username}</Link>
                          {c.is_own_creator && <span className="tag own">наш</span>}
                          {c.account_status !== "active" && <span className="tag crit">{c.account_status}</span>}
                        </span>
                        <span className="small muted">{c.link_type ? LINK_LABEL[c.link_type] ?? c.link_type : ""}</span>
                      </span>
                    ),
                  },
                  { key: "followers", label: "Подписчики", right: true, sort: (c) => c.followers, render: (c) => fmtCompact(c.followers) },
                  { key: "reels", label: "Роликов", right: true, sort: (c) => c.reels, render: (c) => fmtInt(c.reels) },
                  { key: "median", label: "Медиана 20 последних", right: true, sort: (c) => c.median_views, render: (c) => fmtCompact(c.median_views) },
                  { key: "avg", label: "Среднее (20)", right: true, sort: (c) => c.avg_views_20 ?? null, render: (c) => fmtCompact(c.avg_views_20) },
                  { key: "vpd", label: "В сутки", right: true, title: "в среднем просмотров в сутки за 30 дней", sort: (c) => c.views_per_day_30d ?? null, render: (c) => fmtCompact(c.views_per_day_30d) },
                  { key: "er", label: "ER", right: true, sort: (c) => (c.er_median_20 === null || c.er_median_20 === undefined ? null : Number(c.er_median_20)), render: (c) => (c.er_median_20 === null || c.er_median_20 === undefined ? "—" : `${(Number(c.er_median_20) * 100).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`) },
                  { key: "ppw", label: "В неделю", right: true, title: "роликов в неделю за 90 дней", sort: (c) => (c.posts_per_week_90d === null || c.posts_per_week_90d === undefined ? null : Number(c.posts_per_week_90d)), render: (c) => (c.posts_per_week_90d === null || c.posts_per_week_90d === undefined ? "—" : Number(c.posts_per_week_90d).toLocaleString("ru-RU", { maximumFractionDigits: 1 })) },
                  {
                    key: "trend",
                    label: "Тренд",
                    right: true,
                    title: "медиана последних 20 / медиана предыдущих 20",
                    sort: (c) => c.trend,
                    render: (c) => (c.trend === null ? <span className="muted">—</span> : <span className={c.trend >= 1 ? "up" : "down"}>{c.trend >= 1 ? "▲" : "▼"} {fmtRatio(c.trend, 2)}</span>),
                  },
                  { key: "spikes", label: "Всплесков", right: true, sort: (c) => c.spikes, render: (c) => fmtInt(c.spikes) },
                  { key: "hit", label: "Hit rate", right: true, sort: (c) => (c.reels ? (c.spikes ?? 0) / c.reels : null), render: (c) => (c.reels ? `${Math.round(((c.spikes ?? 0) / c.reels) * 100)}%` : "—") },
                  { key: "max", label: "Макс. всплеск", right: true, sort: (c) => c.max_ratio, render: (c) => fmtRatio(c.max_ratio) },
                  { key: "last", label: "Последний ролик", sort: (c) => c.last_reel_at, render: (c) => <span className="ink2">{fmtAgo(c.last_reel_at)}</span> },
                  {
                    key: "x",
                    label: "",
                    render: (c) => (
                      <button className="ghost small" title="Убрать из креаторов бренда" onClick={() => confirm(`Убрать @${c.username} из креаторов ${brand.name}? Собранные данные останутся.`) && remove.mutate(c.user_pk)}>
                        Убрать
                      </button>
                    ),
                  },
                ]}
              />
            )}
          </div>

          {pending.length > 0 && (
            <div className="card flush">
              <div className="card-head">
                <h2>Ожидают первого сбора ({pending.length})</h2>
                <span className="hint">аккаунты из списка заказчика: после сбора профиля появятся в рейтинге и загрузится вся история роликов</span>
              </div>
              <div className="table-wrap">
                <table className="compact">
                  <thead>
                    <tr><th>Аккаунт</th><th>Роль</th><th>ФИ</th><th>Куратор</th><th>Статус</th><th>Последняя ошибка</th></tr>
                  </thead>
                  <tbody>
                    {pending.map((p) => (
                      <tr key={p.task_id}>
                        <td>
                          <a href={`https://www.instagram.com/${p.username}/`} target="_blank" rel="noreferrer">@{p.username}</a>
                          {p.is_own_creator && <span className="tag own" style={{ marginLeft: 6 }}>наш</span>}
                        </td>
                        <td className="ink2">{p.role === "shop" ? "официальный аккаунт" : p.link_type === "reviewer" ? "обзорный аккаунт" : p.link_type === "public" ? "паблик" : "креатор"}</td>
                        <td className="ink2">{p.person_name ?? "—"}</td>
                        <td className="ink2">{p.curator ?? "—"}</td>
                        <td><span className={`tag${p.status === "failed" ? " crit" : p.status === "deferred" || p.status === "retry" ? " warn" : ""}`}>{STATUS_LABEL[p.status] ?? p.status}</span></td>
                        <td className="small" style={{ color: "var(--bad)" }}>{p.last_error ?? ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="card">
            <h2>Сильнейшие всплески за 90 дней</h2>
            {top.data && top.data.items.length > 0 ? (
              <div className="media-grid">{top.data.items.map((m) => <MediaCard key={m.media_pk} m={m} />)}</div>
            ) : top.isLoading ? <Loading /> : <Empty>Всплесков пока нет.</Empty>}
          </div>
        </>
      )}

      {tab === "settings" && <BrandSettings brand={brand} onDeleted={() => nav("/brands")} />}
    </div>
  );
}

function BrandSettings({ brand, onDeleted }: { brand: Brand; onDeleted: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ name: brand.name, hashtags: brand.hashtags.join(" "), instagram: "", spike_min_views: brand.spike_min_views, rocket_views: brand.rocket_views, is_own: brand.is_own, masks: (brand.username_masks ?? []).join(" "), domains: (brand.domains ?? []).join(" ") });
  useEffect(() => {
    setF((s) => ({ ...s, name: brand.name, hashtags: brand.hashtags.join(" ") }));
  }, [brand.name, brand.hashtags]);
  const save = useMutation({
    mutationFn: () =>
      api.patch(`/brands/${brand.id}`, {
        name: f.name,
        hashtags: f.hashtags.split(/[\s,]+/).filter(Boolean),
        spike_min_views: Number(f.spike_min_views),
        rocket_views: Number(f.rocket_views),
        is_own: f.is_own,
        username_masks: f.masks.split(/\s+/).filter(Boolean),
        domains: f.domains.split(/\s+/).filter(Boolean),
        ...(f.instagram.trim() ? { instagram: f.instagram.trim() } : {}),
      }),
    onSuccess: () => {
      toast("Сохранено");
      qc.invalidateQueries();
    },
    onError: (e) => toast(e.message),
  });
  const del = useMutation({
    mutationFn: () => api.del(`/brands/${brand.id}`),
    onSuccess: () => {
      qc.invalidateQueries();
      onDeleted();
    },
  });
  return (
    <form className="card stack" style={{ gap: 14, maxWidth: 720 }} onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <div className="panel-form">
        <label className="field">Название<input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
        <label className="field">Сменить официальный аккаунт<input value={f.instagram} onChange={(e) => setF({ ...f, instagram: e.target.value })} placeholder={brand.shop_username ? `сейчас @${brand.shop_username}` : "ссылка или @ник"} /></label>
      </div>
      <label className="field">Хэштеги бренда (через пробел)<input value={f.hashtags} onChange={(e) => setF({ ...f, hashtags: e.target.value })} /></label>
      <label className="field">Маски ников креаторов (через пробел)<input value={f.masks} onChange={(e) => setF({ ...f, masks: e.target.value })} placeholder="*.base *_mela *onefive*" /></label>
      <div className="hint">«*» — любые символы, «[._]» — точка или подчёркивание. Ник по маске даёт кандидату +20 к уверенности.</div>
      <label className="field">Сайт бренда (домены через пробел)<input value={f.domains} onChange={(e) => setF({ ...f, domains: e.target.value })} placeholder="waistline.shop" /></label>
      <div className="hint">Ссылка на сайт или @аккаунт бренда в шапке профиля даёт кандидату +40.</div>
      <div className="panel-form">
        <label className="field">Порог всплеска, просмотров<input type="number" min={0} value={f.spike_min_views} onChange={(e) => setF({ ...f, spike_min_views: Number(e.target.value) })} /></label>
        <label className="field">Порог «ракеты», просмотров<input type="number" min={0} value={f.rocket_views} onChange={(e) => setF({ ...f, rocket_views: Number(e.target.value) })} /></label>
      </div>
      <div className="hint">Ролик получает категорию high / strong / viral, только если набрал не меньше порога всплеска.</div>
      <label className="check"><input type="checkbox" checked={f.is_own} onChange={(e) => setF({ ...f, is_own: e.target.checked })} /> Это наш бренд</label>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <button className="primary" disabled={save.isPending}>Сохранить</button>
        <button type="button" className="danger" onClick={() => confirm(`Удалить бренд ${brand.name}? Связи с креаторами будут удалены, собранные ролики останутся.`) && del.mutate()}>
          Удалить бренд
        </button>
      </div>
    </form>
  );
}
