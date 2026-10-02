export type MeetingStatus =
  | "recording"
  | "transcribing"
  | "transcribed"
  | "analyzing"
  | "done"
  | "error";

export interface Meeting {
  id: number;
  title: string;
  status: MeetingStatus;
  started_at: string;
  ended_at: string | null;
  mic_device: string | null;
  remote_device: string | null;
  keep_audio: boolean;
  summary: string | null;
  error: string | null;
  source_file: string | null;
  created_at: string;
}

export interface MeetingListItem extends Meeting {
  action_count: number;
}

export interface Segment {
  id: number;
  source: "mic" | "remote";
  speaker: string | null;
  start_s: number;
  end_s: number;
  text: string;
}

export interface ActionItem {
  task: string;
  owner: string | null;
  deadline: string | null;
  quote: string | null;
  verified: boolean;
}

export interface MeetingAnalysis {
  summary: string;
  decisions: string[];
  actions: ActionItem[];
  questions: string[];
  risks: string[];
  technical_topics: string[];
}

export interface MeetingDetail {
  meeting: Meeting;
  segments: Segment[];
  analysis: MeetingAnalysis | null;
  has_audio: boolean;
  captured: Record<"mic" | "remote", CapturedDevice> | null;
}

export interface AudioDevice {
  name: string;
  description: string;
  is_default: boolean;
}

export interface AudioDevices {
  sources: AudioDevice[];
  sinks: AudioDevice[];
  in_use_source: string | null;
  in_use_sink: string | null;
}

export interface CapturedDevice {
  device: string | null;
  auto: boolean;
  error: string | null;
}

export interface SetupStep {
  label: string;
  progress: number | null;
  error: string | null;
  done: boolean;
}

export interface Health {
  whisper: "loading" | "ready" | "error";
  whisper_detail: string | null;
  ollama: boolean;
  ollama_model: string;
  ollama_model_available: boolean;
  active_meeting_id: number | null;
  setup: SetupStep[];
}

export interface StartMeetingRequest {
  title: string;
  mic_device: string | null;
  remote_device: string | null;
  keep_audio: boolean;
}

export type MeetingEvent =
  | { type: "segment"; segment: Segment }
  | { type: "status"; status: MeetingStatus; error: string | null }
  | { type: "levels"; levels: Record<"mic" | "remote", number>; queue: number }
  | { type: "devices"; devices: Record<"mic" | "remote", CapturedDevice> }
  | { type: "progress"; done_s: number; total_s: number | null };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    // FormData sets its own multipart content type.
    headers:
      typeof init?.body === "string" ? { "Content-Type": "application/json" } : undefined,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `${response.status} ${response.statusText}`);
  }
  if (response.status === 204 || response.status === 202) return undefined as T;
  const type = response.headers.get("content-type") ?? "";
  return (type.includes("json") ? response.json() : response.text()) as Promise<T>;
}

export const api = {
  health: () => request<Health>("/health"),
  shutdown: () => request<void>("/shutdown", { method: "POST" }),
  devices: () => request<AudioDevices>("/audio/devices"),
  meetings: (query = "") =>
    request<MeetingListItem[]>(`/meetings?q=${encodeURIComponent(query)}`),
  meeting: (id: number) => request<MeetingDetail>(`/meetings/${id}`),
  start: (body: StartMeetingRequest) =>
    request<Meeting>("/meetings", { method: "POST", body: JSON.stringify(body) }),
  importFile: (file: File, title: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("title", title);
    return request<Meeting>("/meetings/import", { method: "POST", body: form });
  },
  stop: (id: number) => request<Meeting>(`/meetings/${id}/stop`, { method: "POST" }),
  rename: (id: number, title: string) =>
    request<Meeting>(`/meetings/${id}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  analyze: (id: number) => request<void>(`/meetings/${id}/analyze`, { method: "POST" }),
  report: (id: number) => request<string>(`/meetings/${id}/report.md`),
  deleteAudio: (id: number) => request<void>(`/meetings/${id}/audio`, { method: "DELETE" }),
  deleteMeeting: (id: number) => request<void>(`/meetings/${id}`, { method: "DELETE" }),
};

export function meetingSocket(id: number): WebSocket {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  return new WebSocket(`${protocol}://${location.host}/api/meetings/${id}/ws`);
}
