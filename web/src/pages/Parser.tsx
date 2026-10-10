import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type ParserStatus } from "../api";
import { ErrorBox, Freshness, KpiTile, Loading, toast } from "../components/ui";
import { STATUS_LABEL, TASK_LABEL, fmtAgo, fmtDateTime, fmtInt, igUrl } from "../format";

const STATUSES = ["running", "pending", "retry", "deferred", "failed", "succeeded"];

export default function ParserPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["parser"], queryFn: () => api.get<ParserStatus>("/parser/status"), refetchInterval: 15_000 });
  const recompute = useMutation({
    mutationFn: () => api.post<{ media: number; seconds: number }>("/recompute"),
    onSuccess: (r) => {
      toast(`Пересчитано роликов: ${fmtInt(r.media)} за ${r.seconds} с`);
      qc.invalidateQueries();
    },
    onError: (e) => toast(e.message),
  });
  const resolve = useMutation({
    mutationFn: ({ id, action }: { id: number; action: "accept" | "reject" }) => api.post(`/quarantine/${id}/${action}`),
    onSuccess: () => {
      toast("Решение записано");
      qc.invalidateQueries({ queryKey: ["parser"] });
    },
  });

  if (q.isLoading) return <Loading h={400} />;
  if (q.error) return <ErrorBox error={q.error} />;
  if (!q.data) return null;
  const { summary: s, queue, tasks, quarantine, invalid_responses: invalid, problem_accounts: accounts } = q.data;
  const cov = s.coverage;
  const priorities = [0, 1, 2, 3];
  const cell = (status: string, p: number) => queue.find((x) => x.status === status && x.priority === p)?.n ?? 0;

  return (
    <div className="stack" style={{ gap: 20 }}>
      <div className="head">
        <div>
          <h1>Парсер</h1>
          <div className="sub row" style={{ gap: 12 }}><Freshness at={q.data.data_as_of} /> <span>обновляется каждые 15 с</span></div>
        </div>
        <button onClick={() => recompute.mutate()} disabled={recompute.isPending}>{recompute.isPending ? "Пересчитываю…" : "Пересчитать всплески"}</button>
      </div>

      <div className="grid-kpi">
        <KpiTile
          label="Покрытие за сутки"
          value={cov === null ? "—" : `${Math.round(cov * 100)}%`}
          delta={<span className={cov !== null && cov < 0.95 ? "down" : "muted"}>{cov !== null && cov < 0.95 ? "▼ ниже порога 95%" : `${s.covered_24h} из ${s.active_accounts} аккаунтов`}</span>}
        />
        <KpiTile label="В очереди / выполняется" value={`${s.queued} / ${s.running}`} />
        <KpiTile label="Ошибок за сутки" value={fmtInt(s.failed_24h)} delta={s.failed_24h ? <span className="down">есть упавшие задачи</span> : <span className="muted">всё в порядке</span>} />
        <KpiTile label="В карантине" value={fmtInt(s.quarantine)} delta={<span className="muted">снимки ждут проверки</span>} />
        <KpiTile label="Невалидных ответов" value={fmtInt(s.invalid_24h)} delta={s.invalid_24h ? <span className="down">возможно, изменился формат</span> : <span className="muted">за сутки</span>} />
      </div>

      <div className="card flush">
        <div className="card-head"><h2>Очередь по приоритетам</h2><span className="hint">P0 — ручное обновление, P1 — история, P2 — ежедневный сбор, P3 — фоновые</span></div>
        <table>
          <thead><tr><th>Статус</th>{priorities.map((p) => <th key={p} className="r">P{p}</th>)}</tr></thead>
          <tbody>
            {STATUSES.map((st) => (
              <tr key={st}>
                <td>{STATUS_LABEL[st]}</td>
                {priorities.map((p) => <td key={p} className="r">{cell(st, p) || <span className="muted">·</span>}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card flush">
        <div className="card-head"><h2>Активные и проблемные задачи</h2></div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>#</th><th>Задача</th><th>Аккаунт</th><th>Статус</th><th className="r">Попыток</th><th className="r">Страниц</th><th>Когда</th><th>Ошибка</th></tr></thead>
            <tbody>
              {tasks.map((t) => (
                <tr key={t.id}>
                  <td className="num muted">{t.id}</td>
                  <td>{TASK_LABEL[t.type] ?? t.type} <span className="muted small">P{t.priority}</span></td>
                  <td>{t.user_pk ? <Link to={`/accounts/${t.user_pk}`}>@{t.username}</Link> : t.username ? `@${t.username}` : "—"}</td>
                  <td><span className={`tag${t.status === "failed" ? " crit" : t.status === "deferred" || t.status === "retry" ? " warn" : ""}`}>{STATUS_LABEL[t.status] ?? t.status}</span></td>
                  <td className="r">{t.attempts}</td>
                  <td className="r">{t.pages_done ?? 0}</td>
                  <td className="small">
                    {t.status === "running" ? `аренда до ${fmtDateTime(t.lease_until)}` : t.status === "failed" ? fmtAgo(t.finished_at) : `запуск ${fmtAgo(t.run_after)}`}
                  </td>
                  <td className="small" style={{ color: "var(--bad)", maxWidth: 360 }}>{t.last_error ?? ""}</td>
                </tr>
              ))}
              {!tasks.length && <tr><td colSpan={8} className="muted">Нет активных задач</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid2">
        <div className="card flush">
          <div className="card-head"><h2>Карантин метрик</h2><span className="hint">падение просмотров &gt; 5% или рост ×1000</span></div>
          <table>
            <tbody>
              {quarantine.map((x) => (
                <tr key={x.id}>
                  <td>
                    <div>{x.shortcode ? <a href={igUrl(x.shortcode)} target="_blank" rel="noreferrer">ролик ↗</a> : x.media_pk} {x.username && <span className="muted">@{x.username}</span>}</div>
                    <div className="small" style={{ color: "var(--bad)" }}>{x.reason}</div>
                  </td>
                  <td className="r">{fmtInt(x.play_count)}</td>
                  <td>
                    <div className="row" style={{ gap: 4, justifyContent: "flex-end" }}>
                      <button className="small" title="Снимок верный — записать в базу" onClick={() => resolve.mutate({ id: x.id, action: "accept" })}>Принять</button>
                      <button className="small danger" title="Ошибка разбора — отбросить" onClick={() => resolve.mutate({ id: x.id, action: "reject" })}>Отклонить</button>
                    </div>
                  </td>
                </tr>
              ))}
              {!quarantine.length && <tr><td className="muted">Карантин пуст</td></tr>}
            </tbody>
          </table>
        </div>

        <div className="card flush">
          <div className="card-head"><h2>Невалидные ответы</h2><span className="hint">в базу не записаны, хранятся 90 дней</span></div>
          <table>
            <tbody>
              {invalid.map((r) => (
                <tr key={r.id}>
                  <td>
                    <div>{r.request_kind} · HTTP {r.http_status ?? "—"} <span className="muted small">{fmtAgo(r.received_at)}</span></div>
                    <div className="small" style={{ color: "var(--bad)" }}>{r.parse_error}</div>
                    <div className="small muted"><code>{r.s3_key}</code> отпечаток {r.shape_fingerprint}</div>
                  </td>
                </tr>
              ))}
              {!invalid.length && <tr><td className="muted">Нет</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card flush">
        <div className="card-head"><h2>Аккаунты, требующие внимания</h2><span className="hint">закрытые, не найденные или не обновлявшиеся больше суток</span></div>
        <table>
          <tbody>
            {accounts.map((a) => (
              <tr key={a.user_pk}>
                <td><Link to={`/accounts/${a.user_pk}`}>@{a.username}</Link></td>
                <td><span className={`tag${a.status === "active" ? " warn" : " crit"}`}>{a.status === "active" ? "давно не обновлялся" : a.status}</span></td>
                <td className="small muted">{fmtAgo(a.last_scraped_at)}</td>
              </tr>
            ))}
            {!accounts.length && <tr><td className="muted">Все аккаунты в порядке</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
