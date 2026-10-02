import { useEffect, useRef, useState } from "react";
import {
  type CapturedDevice,
  type MeetingAnalysis,
  type MeetingDetail,
  type MeetingEvent,
  type Segment,
  api,
  meetingSocket,
} from "./api";
import { STATUS_LABELS, formatDuration, wallClock } from "./format";

const LIVE_STATUSES = new Set(["recording", "transcribing", "analyzing"]);

export function MeetingPage({ id, onBack }: { id: number; onBack: () => void }) {
  const [detail, setDetail] = useState<MeetingDetail | null>(null);
  const [levels, setLevels] = useState<{ mic: number; remote: number; queue: number } | null>(
    null,
  );
  const [captured, setCaptured] = useState<Record<"mic" | "remote", CapturedDevice> | null>(
    null,
  );
  const [progress, setProgress] = useState<{ done: number; total: number | null } | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const status = detail?.meeting.status;
  const live = status !== undefined && LIVE_STATUSES.has(status);

  const reload = () =>
    api
      .meeting(id)
      .then((d) => {
        setDetail(d);
        setCaptured(d.captured);
      })
      .catch((e) => setError(e.message));

  useEffect(() => {
    reload();
  }, [id]);

  // Live events while the meeting is recording, transcribing or being analyzed.
  useEffect(() => {
    if (!live) return;
    const socket = meetingSocket(id);
    socket.onmessage = (message) => {
      const event: MeetingEvent = JSON.parse(message.data);
      if (event.type === "segment") {
        setDetail((d) => d && { ...d, segments: insertSegment(d.segments, event.segment) });
      } else if (event.type === "progress") {
        setProgress({ done: event.done_s, total: event.total_s });
      } else if (event.type === "devices") {
        setCaptured(event.devices);
      } else if (event.type === "levels") {
        setLevels({ ...event.levels, queue: event.queue });
      } else if (event.type === "status") {
        // Reload to get ended_at, the analysis, and segments possibly missed while connecting.
        reload();
      }
    };
    socket.onopen = () => reload();
    return () => socket.close();
  }, [id, live]);

  if (!detail) return <p className={error ? "error" : "muted"}>{error ?? "Chargement…"}</p>;
  const { meeting, segments, analysis } = detail;

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      await reload();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function copyMarkdown() {
    const markdown = await api.report(id);
    await navigator.clipboard.writeText(markdown);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  async function rename() {
    const title = prompt("Titre de la réunion", meeting.title);
    if (title !== null) await run(() => api.rename(id, title));
  }

  async function remove() {
    if (confirm("Supprimer définitivement cette réunion ?")) {
      await api.deleteMeeting(id);
      onBack();
    }
  }

  return (
    <>
      <div className="row">
        <button onClick={onBack}>← Réunions</button>
      </div>

      <section className="card">
        <div className="meeting-header">
          <h1 onDoubleClick={rename} title="Double-cliquer pour renommer">
            {meeting.title}
          </h1>
          {status === "recording" ? (
            <span className="recording">
              ● Enregistrement <Elapsed since={meeting.started_at} />
            </span>
          ) : (
            <span className={`badge ${meeting.status}`}>{STATUS_LABELS[meeting.status]}</span>
          )}
        </div>

        {status === "recording" && (
          <div className="row">
            <button className="danger" onClick={() => run(() => api.stop(id))}>
              ■ Stop
            </button>
            {levels && (
              <>
                <LevelMeter label="Moi" db={levels.mic} />
                <LevelMeter label="Interlocuteurs" db={levels.remote} />
                {levels.queue > 0 && <span className="muted">{levels.queue} en attente</span>}
              </>
            )}
          </div>
        )}

        {status === "recording" && captured && (
          <p className="muted hint">
            Capture : micro <code>{captured.mic.device ?? "défaut"}</code>
            {captured.mic.auto && " (auto)"} · sortie <code>{captured.remote.device ?? "défaut"}</code>
            {captured.remote.auto && " (auto)"}
          </p>
        )}
        {meeting.source_file && (
          <p className="muted hint">
            Fichier importé : <code>{meeting.source_file}</code>
          </p>
        )}
        {status === "transcribing" && progress && <Progress {...progress} />}
        {meeting.error && <p className="error">{meeting.error}</p>}
        {error && <p className="error">{error}</p>}

        {!live && (
          <div className="row">
            <button className="primary" onClick={copyMarkdown}>
              {copied ? "✓ Copié" : "Copier le compte rendu (Markdown)"}
            </button>
            {(status === "transcribed" || status === "done") && (
              <button onClick={() => run(() => api.analyze(id))}>
                {analysis ? "Relancer l'analyse IA" : "Lancer l'analyse IA"}
              </button>
            )}
            {detail.has_audio && (
              <button onClick={() => run(() => api.deleteAudio(id))}>Supprimer l'audio</button>
            )}
            <button className="danger" onClick={remove}>
              Supprimer
            </button>
          </div>
        )}
      </section>

      {analysis && <Report analysis={analysis} />}

      <section className="card">
        <h2>Transcription</h2>
        <Transcript
          startedAt={meeting.source_file ? null : meeting.started_at}
          segments={segments}
          follow={live}
        />
      </section>
    </>
  );
}

function insertSegment(segments: Segment[], segment: Segment): Segment[] {
  if (segments.some((s) => s.id === segment.id)) return segments;
  return [...segments, segment].sort((a, b) => a.start_s - b.start_s);
}

function Elapsed({ since }: { since: string }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return <>{formatDuration((now - new Date(since).getTime()) / 1000)}</>;
}

function LevelMeter({ label, db }: { label: string; db: number }) {
  // -60 dBFS (silence) .. 0 dBFS
  const percent = Math.min(100, Math.max(0, ((db + 60) / 60) * 100));
  return (
    <span className="level" title={`${db} dBFS`}>
      {label}
      <span className="meter">
        <span style={{ width: `${percent}%` }} />
      </span>
    </span>
  );
}

function Progress({ done, total }: { done: number; total: number | null }) {
  const percent = total ? Math.min(100, (done / total) * 100) : null;
  return (
    <div className="progress">
      <span className="meter wide">
        <span style={{ width: `${percent ?? 0}%` }} />
      </span>
      <span className="muted">
        {formatDuration(done)}
        {total ? ` / ${formatDuration(total)} (${Math.round(percent!)} %)` : ""}
      </span>
    </div>
  );
}

function Transcript({
  startedAt,
  segments,
  follow,
}: {
  /** Meeting start for wall-clock times; null shows positions in the file. */
  startedAt: string | null;
  segments: Segment[];
  follow: boolean;
}) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (follow) end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [segments.length, follow]);

  if (segments.length === 0)
    return <p className="muted">{follow ? "En attente de parole…" : "Transcription vide."}</p>;
  return (
    <div className="transcript">
      {segments.map((s) => (
        <p key={s.id} className={s.source}>
          <time>{startedAt ? wallClock(startedAt, s.start_s) : formatDuration(s.start_s)}</time>
          <strong>{s.speaker}</strong>
          <span>{s.text}</span>
        </p>
      ))}
      <div ref={end} />
    </div>
  );
}

function List({ items }: { items: string[] }) {
  if (items.length === 0) return <p className="muted">Aucun.</p>;
  return (
    <ul>
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  );
}

function Report({ analysis }: { analysis: MeetingAnalysis }) {
  return (
    <section className="card report">
      <h2>Résumé</h2>
      <p>{analysis.summary}</p>

      <h2>Décisions prises</h2>
      <List items={analysis.decisions} />

      <h2>Actions</h2>
      {analysis.actions.length === 0 ? (
        <p className="muted">Aucune.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Action</th>
              <th>Responsable</th>
              <th>Échéance</th>
            </tr>
          </thead>
          <tbody>
            {analysis.actions.map((a, i) => (
              <tr key={i}>
                <td title={a.quote ?? undefined}>
                  {a.task}
                  {!a.verified && (
                    <span className="warn-icon" title="Citation introuvable dans la transcription">
                      {" "}
                      ⚠️
                    </span>
                  )}
                </td>
                <td>{a.owner ?? <span className="muted">Non défini</span>}</td>
                <td>{a.deadline ?? <span className="muted">Non définie</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Points techniques</h2>
      <List items={analysis.technical_topics} />

      <h2>Questions ouvertes</h2>
      <List items={analysis.questions} />

      <h2>Risques</h2>
      <List items={analysis.risks} />
    </section>
  );
}
