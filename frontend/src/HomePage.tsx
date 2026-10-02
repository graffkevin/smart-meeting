import { type FormEvent, useEffect, useState } from "react";
import { type AudioDevice, type AudioDevices, type Health, type Meeting, api } from "./api";
import { STATUS_LABELS, formatDate } from "./format";

const AUTO = "";

function describe(devices: AudioDevice[] | undefined, name: string | null | undefined) {
  return devices?.find((d) => d.name === name)?.description ?? name ?? "aucun";
}

export function HomePage({ onOpen }: { onOpen: (id: number) => void }) {
  // undefined: first check pending; null: backend unreachable.
  const [health, setHealth] = useState<Health | null | undefined>(undefined);
  const [devices, setDevices] = useState<AudioDevices | null>(null);
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [title, setTitle] = useState("");
  const [mic, setMic] = useState(AUTO);
  const [remote, setRemote] = useState(AUTO);
  const [keepAudio, setKeepAudio] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const refreshDevices = () => api.devices().then(setDevices).catch((e) => setError(e.message));

  useEffect(() => {
    refreshDevices();
    api.meetings().then(setMeetings).catch((e) => setError(e.message));
    const poll = () => api.health().then(setHealth).catch(() => setHealth(null));
    poll();
    const timer = setInterval(poll, 5000);
    return () => clearInterval(timer);
  }, []);

  async function start(event: FormEvent) {
    event.preventDefault();
    setStarting(true);
    setError(null);
    try {
      const meeting = await api.start({
        title,
        mic_device: mic || null,
        remote_device: remote || null,
        keep_audio: keepAudio,
      });
      onOpen(meeting.id);
    } catch (e) {
      setError((e as Error).message);
      setStarting(false);
    }
  }

  const active = health?.active_meeting_id ?? null;

  return (
    <>
      <HealthBar health={health} />

      <section className="card">
        <h2>Nouvelle réunion</h2>
        {active !== null ? (
          <p>
            Une réunion est en cours.{" "}
            <button className="link" onClick={() => onOpen(active)}>
              La rejoindre
            </button>
          </p>
        ) : (
          <form onSubmit={start} className="form">
            <label>
              Titre
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Point projet JUNN"
                autoFocus
              />
            </label>
            <label>
              Mon microphone
              <select value={mic} onChange={(e) => setMic(e.target.value)}>
                <option value={AUTO}>
                  Automatique : celui utilisé ({describe(devices?.sources, devices?.in_use_source)})
                </option>
                {devices?.sources.map((d) => (
                  <option key={d.name} value={d.name}>
                    {d.description}
                    {d.is_default ? " (défaut)" : ""}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Ce que j'entends (sortie à écouter)
              <select value={remote} onChange={(e) => setRemote(e.target.value)}>
                <option value={AUTO}>
                  Automatique : celle utilisée ({describe(devices?.sinks, devices?.in_use_sink)})
                </option>
                {devices?.sinks.map((d) => (
                  <option key={d.name} value={d.name}>
                    {d.description}
                    {d.is_default ? " (défaut)" : ""}
                  </option>
                ))}
              </select>
            </label>
            <p className="muted hint">
              En automatique, la capture suit les périphériques réellement utilisés par vos
              applications (Teams, Firefox…), même si l'appel démarre après l'enregistrement.
            </p>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={keepAudio}
                onChange={(e) => setKeepAudio(e.target.checked)}
              />
              Conserver l'audio brut (sinon il n'est jamais écrit sur disque)
            </label>
            <div className="row">
              <button type="submit" className="primary" disabled={starting}>
                ● Démarrer l'enregistrement
              </button>
              <button type="button" onClick={refreshDevices}>
                Rafraîchir les périphériques
              </button>
            </div>
          </form>
        )}
        {error && <p className="error">{error}</p>}
      </section>

      <ImportCard disabled={active !== null} onOpen={onOpen} />

      <section className="card">
        <h2>Historique</h2>
        {meetings.length === 0 ? (
          <p className="muted">Aucune réunion.</p>
        ) : (
          <ul className="history">
            {meetings.map((m) => (
              <li key={m.id}>
                <button className="link" onClick={() => onOpen(m.id)}>
                  {m.title}
                </button>
                <span className="muted">{formatDate(m.started_at)}</span>
                <span className={`badge ${m.status}`}>{STATUS_LABELS[m.status]}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

function ImportCard({
  disabled,
  onOpen,
}: {
  disabled: boolean;
  onOpen: (id: number) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const meeting = await api.importFile(file, title);
      onOpen(meeting.id);
    } catch (e) {
      setError((e as Error).message);
      setUploading(false);
    }
  }

  return (
    <section className="card">
      <h2>Importer une vidéo ou un audio</h2>
      <form onSubmit={submit} className="form">
        <label>
          Fichier (mp4, mkv, webm, mp3, wav, m4a…)
          <input
            type="file"
            accept="video/*,audio/*"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
        <label>
          Titre
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={file ? file.name.replace(/\.[^.]+$/, "") : "Nom du fichier par défaut"}
          />
        </label>
        <p className="muted hint">
          Transcription plus rapide que le temps réel, puis compte rendu. Le fichier envoyé est
          supprimé dès qu'il est décodé.
        </p>
        <div className="row">
          <button type="submit" className="primary" disabled={!file || uploading || disabled}>
            {uploading ? "Envoi…" : "Transcrire le fichier"}
          </button>
          {disabled && <span className="muted">Indisponible pendant un enregistrement.</span>}
        </div>
      </form>
      {error && <p className="error">{error}</p>}
    </section>
  );
}

function HealthBar({ health }: { health: Health | null | undefined }) {
  if (health === undefined) return null;
  if (health === null) return <p className="banner error">Backend injoignable.</p>;
  const problems: string[] = [];
  if (health.whisper === "loading") problems.push("Chargement du modèle Whisper…");
  if (health.whisper === "error") problems.push(`Whisper en erreur : ${health.whisper_detail}`);
  if (!health.ollama) problems.push("Ollama ne répond pas : l'analyse IA sera indisponible.");
  else if (!health.ollama_model_available)
    problems.push(`Modèle Ollama absent : ollama pull ${health.ollama_model}`);
  if (problems.length === 0)
    return (
      <p className="banner ok">
        Whisper {health.whisper_detail} · Ollama {health.ollama_model} · 100 % local
      </p>
    );
  return (
    <div className="banner warn">
      {problems.map((p) => (
        <div key={p}>{p}</div>
      ))}
    </div>
  );
}
