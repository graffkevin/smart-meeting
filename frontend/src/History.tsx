import { useEffect, useState } from "react";
import { type MeetingListItem, api } from "./api";
import { STATUS_LABELS, formatDate, formatDuration } from "./format";

const SEARCH_DELAY_MS = 250;

export function History({ onOpen }: { onOpen: (id: number) => void }) {
  const [query, setQuery] = useState("");
  const [meetings, setMeetings] = useState<MeetingListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = (q: string) =>
    api
      .meetings(q)
      .then((items) => {
        setMeetings(items);
        setError(null);
      })
      .catch((e) => setError(e.message));

  // Debounced search; an empty query lists everything.
  useEffect(() => {
    const timer = setTimeout(() => load(query), query ? SEARCH_DELAY_MS : 0);
    return () => clearTimeout(timer);
  }, [query]);

  async function remove(meeting: MeetingListItem) {
    if (!confirm(`Supprimer définitivement « ${meeting.title} » ?`)) return;
    try {
      await api.deleteMeeting(meeting.id);
      await load(query);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section className="card">
      <div className="history-header">
        <h2>Historique</h2>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Rechercher (titre, résumé, transcription)"
          aria-label="Rechercher dans l'historique"
        />
      </div>
      {error && <p className="error">{error}</p>}
      {meetings === null ? (
        <p className="muted">Chargement…</p>
      ) : meetings.length === 0 ? (
        <p className="muted">{query ? "Aucun résultat." : "Aucune réunion."}</p>
      ) : (
        <ul className="history">
          {meetings.map((m) => (
            <li key={m.id}>
              <div className="history-main">
                <button className="link title" onClick={() => onOpen(m.id)}>
                  {m.title}
                </button>
                <span className="muted">
                  {formatDate(m.started_at)}
                  {m.ended_at &&
                    !m.source_file &&
                    ` · ${formatDuration(
                      (new Date(m.ended_at).getTime() - new Date(m.started_at).getTime()) / 1000,
                    )}`}
                  {m.source_file && ` · import ${m.source_file}`}
                  {m.action_count > 0 &&
                    ` · ${m.action_count} action${m.action_count > 1 ? "s" : ""}`}
                </span>
                {m.summary && <p className="excerpt">{m.summary}</p>}
              </div>
              <span className={`badge ${m.status}`}>{STATUS_LABELS[m.status]}</span>
              <button
                className="icon"
                onClick={() => remove(m)}
                disabled={m.status === "recording"}
                title="Supprimer"
                aria-label={`Supprimer ${m.title}`}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
