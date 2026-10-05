# Smart Meeting

Live transcription and automatic minutes for your meetings, **100% local** (faster-whisper, Ollama). Nothing you say
or hear ever leaves your computer.

During a video call (Teams, Meet, Zoom… in a browser or an app), Smart Meeting listens to what plays in your headset
and to your microphone, transcribes both live (you on one side, the other participants on the other), lets you ask
the local AI anything about the meeting ("what do I have to do?"), and writes the minutes: summary, decisions,
actions, open questions, risks. Everything can be copied as Markdown.

The interface is in French and English (FR | EN switch in the header; the AI answers, the minutes and the default
meeting names follow it). Architecture and design choices: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
(in French).

## Install

Linux, macOS and Windows: clone the repository, then `make run`. The first run installs everything else.

| System | Install once | Run |
|---|---|---|
| **Ubuntu** (22.10+, PipeWire) | `sudo apt install git make` (often already there) | `make run`, `./smart-meeting` or the app menu (`make desktop`) |
| **macOS** (13 Ventura+) | `xcode-select --install` (git, make) | `make run` |
| **Windows** 10/11 | `winget install Git.Git ezwinports.make` | `make run` |

```bash
git clone https://github.com/graffkevin/smart-meeting.git
cd smart-meeting
make run
```

`make run` detects the system and installs, without admin rights:

| Component | How |
|---|---|
| uv, Python dependencies | automatic (CUDA libraries only with an NVIDIA GPU) |
| Bun, web interface | Bun installed for the user (official build, works behind a proxy and on any x86-64 CPU); interface built on first run and after each update |
| Ollama | reused if already installed, otherwise downloaded to the user folder; started and stopped with the app |
| AI model (`qwen2.5:7b`, 4.7 GB) | downloaded in the background, progress shown in the interface |
| Transcription model | `large-v3-turbo` with an NVIDIA GPU, `small` otherwise (Mac, PC without GPU) |

> **The first run can take a while**: up to about 8 GB to download (Ollama 1.4 GB, AI model 4.7 GB, transcription
> model 1.6 GB), 10 to 30 minutes depending on the connection. Later runs start in seconds. If Ollama and the model are
> already installed, none of this is downloaded again.

The app is usable during the downloads: recording works, the AI features arrive at the end. `make info` shows what
was detected.

### Audio capture per system

| System | What I hear | My microphone | Status |
|---|---|---|---|
| Linux | PipeWire monitor of the output (follows the call in automatic mode) | PipeWire | tested |
| Windows | WASAPI loopback of the chosen output | WASAPI | **not tested yet** |
| macOS | ScreenCaptureKit (whole system audio) | CoreAudio | **not tested yet** |

On **macOS**, the first recording asks for the "Screen & System Audio Recording" permission for the terminal that runs
Smart Meeting: grant it in System Settings > Privacy & Security, then restart. If one of the two sources cannot be
captured, the meeting goes on with the other one and the interface tells why; importing a file works in every case.

## Use

### Start

| How | Command |
|---|---|
| **Applications menu** (Linux) | Super key, type "Smart Meeting" (after `make desktop`; can be pinned to the dock) |
| **Terminal** (any system) | `make run` in the project folder (or `./smart-meeting` on Linux and macOS) |
| **Browser**, if already running | http://127.0.0.1:8417 |

The local server starts, with Ollama if it is not running yet, and the interface opens in a tab of the default
browser. An already open Smart Meeting page is reused, and a page left open after a stop reloads itself on the next
start. The app is this local web page, served by your own machine: nothing goes through the Internet.

### Stop

**Closing the tab is enough**: the app stops 10 seconds after its last page is closed (time for a reload). A
recording, an import, an AI answer or a download in progress is finished first: a recording goes on with the tab
closed, and reopening the page finds it again. The **Quit** button stops at once (a recording is stopped and its
transcription finished first), like `Ctrl+C` in the terminal.

### Record a meeting

1. Optionally a name and tags, then start recording. By default the devices are automatic: the microphone and the
   output your apps actually use are followed, even if the call starts later. A meeting without a name is named after
   its date and time.
2. The transcript appears live, word by word: the sentence being spoken shows in grey (fast draft, refreshed about
   every 1.5 s), then its final, more accurate version replaces it at the pause. The transcript scrolls in a panel on
   the right.
3. **Ask the meeting**, during or after: summary, my actions, decisions in one click, or any question ("what do I
   have to do?"). The local AI answers from the transcript only, gives the time of the passages, and says when the
   information is not there. Questions and answers are kept with the meeting; recent questions are suggested.
4. **Stop**: the transcription finishes, then the AI writes the minutes.
5. **Copy the minutes (Markdown)**, or the whole transcript.

### Import a video or an audio file

From the home page (call replay, webinar, voice note; mp4, mkv, webm, mp3, wav…): the file is decoded at once and
transcribed in batches, several passages in parallel, the language detected once (unless chosen): about 8× faster than
real time on a modest laptop GPU (147 s of audio in 19 s on an NVIDIA T600), times relative to the file. The uploaded file is deleted as soon as it is decoded. A video played
in the headset during a recording works too.

### Tabs, tags and history

- Each open meeting has its tab under the header, like in a browser: switch, close, rename (double click), delete. The
  "+" reopens a recent meeting or starts a new one. Tabs are remembered between sessions.
- Meetings can be **tagged** (when starting, or on the meeting page). The history lists them newest first or
  **grouped by tag**, and the search covers titles, tags, summaries and transcripts.
- Meetings are only kept on your machine, in a SQLite database (never in the repository):

| System | Folder |
|---|---|
| Linux | `~/.local/share/smart-meeting/` |
| macOS | `~/Library/Application Support/smart-meeting/` |
| Windows | `%LOCALAPPDATA%\smart-meeting\` |

It holds `smart-meeting.db` (meetings, transcripts, minutes, questions, tags), `audio/<id>/` if the raw audio was
kept, and `ollama.log`. To back up the history, copy the `.db` while the app is stopped; to move it, set
`SM_DATA_DIR=/path` in `config.env`.

## Settings

The **⚙ settings** button of the header sets, without restarting: your name (your sentences, and "I" for the AI),
a vocabulary of names and acronyms that helps the transcription, the default language, the microphone, the headset,
and whether the raw audio is kept. The **AI - model** dot of the header tells whether the local AI runs (green,
orange, red), with a button to restart it when it is not green.

Advanced settings: `SM_*` variables in `config.env` of the configuration folder (Linux: `~/.config/smart-meeting/`,
macOS: `~/Library/Application Support/smart-meeting/`, Windows: `%LOCALAPPDATA%\smart-meeting\`), or `backend/.env`
in development:

```bash
SM_USER_NAME=Alex                   # label of my microphone in the transcript, "I" for the AI
SM_REMOTE_NAME=Interlocuteur        # label of the other participants
SM_WHISPER_GLOSSARY="Atlas, OAuth, Kubernetes."  # names and acronyms to recognize
SM_WHISPER_MODEL=auto               # or large-v3-turbo / medium / small
SM_WHISPER_PARTIAL_MODEL=auto       # live draft: small next to the main model on GPU, none to disable
SM_OLLAMA_MODEL=qwen2.5:7b
SM_OLLAMA_BIN=/path/to/ollama       # if Ollama is not on the PATH
SM_DATA_DIR=~/.local/share/smart-meeting
SM_PORT=8417                        # local port of the interface
```

The vocabulary makes a clear difference on proper names and acronyms, which Whisper otherwise often mishears.

## Develop

```bash
make dev     # backend with auto-reload (port 8417) + Vite (http://127.0.0.1:5173)
make check   # everything that must pass before a commit (lint + tests)
make api     # regenerates the frontend API client from the backend OpenAPI schema
```

Backend: Python, FastAPI, faster-whisper, Ollama, SQLite, managed by **uv**, checked by **Ruff** and **pytest**.

The frontend (`frontend/`) follows strict rules:

- **Bun** (never npm), **Biome**, **Vitest**; `bun run check:rules` checks the rules below (`frontend/scripts/`, Bun
  scripts so that they also run on Windows);
- a Mantine-based design system: its components rather than Mantine's, texts only through `Typography` variants,
  tokens rather than raw values, no CSS file;
- **i18next**: no hardcoded text, everything in `src/locales/fr.ts`;
- **TanStack Query** (`services/*QueryOptions.ts` factories) and **TanStack Form**; API client **generated by Orval**
  from the FastAPI OpenAPI schema (`src/api/generated/`, never edited by hand);
- one role per folder (`pages/`, `features/`, `components/`, `contexts/`, `hooks/`, `services/`, `types/`,
  `constants/`, `utils/`, `tests/`), one default export per file, arrow functions, no `let` nor loop, `@/…` imports,
  every type in `types/`, external data checked by type guards, no HTML tag in JSX.

## Privacy

No audio and no transcript ever leaves the machine. The API only listens on `127.0.0.1`, calls to Ollama ignore the
proxy, a remote Ollama URL is refused, and the Ollama started by the app runs with its cloud features disabled
(`OLLAMA_NO_CLOUD=1`). By default, the raw audio is never written to disk. Downloads only fetch software and model
weights.

## License

[MIT](LICENSE)
