import { useEffect, useState } from "react";
import { api } from "./api";
import { HomePage } from "./HomePage";
import { MeetingPage } from "./MeetingPage";

// Two screens only: a hash route is enough, no router dependency.
function currentMeetingId(): number | null {
  const match = location.hash.match(/^#\/meetings\/(\d+)$/);
  return match ? Number(match[1]) : null;
}

export function App() {
  const [meetingId, setMeetingId] = useState(currentMeetingId);
  const [quitState, setQuitState] = useState<"running" | "quitting" | "stopped">("running");

  // Presence: an open WebSocket tells the server this page exists. The launcher then reuses it
  // instead of opening another one, and the app stops once the last page is closed. If the
  // server comes back after a stop or restart, reload so this page is reused.
  useEffect(() => {
    let lost = false;
    let unmounted = false;
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const connect = () => {
      const protocol = location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${protocol}://${location.host}/api/presence`);
      socket.onopen = () => {
        if (lost) location.reload();
      };
      socket.onclose = () => {
        lost = true;
        if (!unmounted) retry = setTimeout(connect, 2000);
      };
    };
    connect();
    return () => {
      unmounted = true;
      clearTimeout(retry);
      socket?.close();
    };
  }, []);

  useEffect(() => {
    const onChange = () => setMeetingId(currentMeetingId());
    addEventListener("hashchange", onChange);
    return () => removeEventListener("hashchange", onChange);
  }, []);

  async function quit() {
    const health = await api.health().catch(() => null);
    const warning = health?.active_meeting_id
      ? "Une réunion est en cours : elle sera arrêtée et sa transcription terminée " +
        "(l'analyse IA pourra être relancée plus tard).\n\n"
      : "";
    if (!confirm(`${warning}Quitter Smart Meeting ?`)) return;
    setQuitState("quitting");
    try {
      await api.shutdown();
    } finally {
      setQuitState("stopped");
    }
  }

  if (quitState !== "running") {
    return (
      <main>
        <header className="app-header">
          <span>Smart Meeting</span>
        </header>
        <section className="card">
          {quitState === "quitting" ? (
            <p>Arrêt en cours… (fin de la transcription si une réunion était en cours)</p>
          ) : (
            <p>
              Smart Meeting est arrêté. Vous pouvez fermer cet onglet, ou le garder : il se
              rechargera tout seul au prochain lancement.
            </p>
          )}
        </section>
      </main>
    );
  }

  return (
    <main>
      <header className="app-header">
        <a href="#/">Smart Meeting</a>
        <button onClick={quit} title="Arrêter Smart Meeting (serveur et Ollama)">
          Quitter
        </button>
      </header>
      {meetingId === null ? (
        <HomePage onOpen={(id) => (location.hash = `#/meetings/${id}`)} />
      ) : (
        <MeetingPage key={meetingId} id={meetingId} onBack={() => (location.hash = "#/")} />
      )}
    </main>
  );
}
