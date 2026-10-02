import { useEffect, useState } from "react";
import { HomePage } from "./HomePage";
import { MeetingPage } from "./MeetingPage";

// Two screens only: a hash route is enough, no router dependency.
function currentMeetingId(): number | null {
  const match = location.hash.match(/^#\/meetings\/(\d+)$/);
  return match ? Number(match[1]) : null;
}

export function App() {
  const [meetingId, setMeetingId] = useState(currentMeetingId);

  useEffect(() => {
    const onChange = () => setMeetingId(currentMeetingId());
    addEventListener("hashchange", onChange);
    return () => removeEventListener("hashchange", onChange);
  }, []);

  return (
    <main>
      <header className="app-header">
        <a href="#/">Smart Meeting</a>
      </header>
      {meetingId === null ? (
        <HomePage onOpen={(id) => (location.hash = `#/meetings/${id}`)} />
      ) : (
        <MeetingPage key={meetingId} id={meetingId} onBack={() => (location.hash = "#/")} />
      )}
    </main>
  );
}
