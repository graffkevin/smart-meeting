import type { MeetingStatus } from "./api";

export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
}

/** Wall-clock time of a segment, from the meeting start and its offset in seconds. */
export function wallClock(startedAt: string, offsetSeconds: number): string {
  const date = new Date(new Date(startedAt).getTime() + offsetSeconds * 1000);
  return date.toLocaleTimeString("fr-FR");
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" });
}

export const STATUS_LABELS: Record<MeetingStatus, string> = {
  recording: "Enregistrement",
  transcribing: "Fin de transcription…",
  transcribed: "Transcrite",
  analyzing: "Analyse IA…",
  done: "Terminée",
  error: "Erreur",
};
