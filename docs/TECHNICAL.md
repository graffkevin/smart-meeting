# Smart Meeting: technical notes

How Smart Meeting works, its advanced settings and how to develop it. For using the app, see the
[README](../README.md); for the design choices (in French), [ARCHITECTURE.md](ARCHITECTURE.md).

## Stack

- **Backend**: Python 3.12, FastAPI, Whisper through the engine of the hardware (faster-whisper, MLX or OpenVINO),
  Silero VAD, ONNX Runtime, SQLite, managed by **uv**. Serves the API and the built interface on `127.0.0.1:8417`.
- **AI**: Ollama, started and stopped with the app. Two models, chosen in the settings: `qwen2.5:3b` (fast, the
  default) or `qwen2.5:7b` (precise, about three times slower). On an NVIDIA card, Whisper leaves the card to the AI
  outside meetings and imports, and takes it back when one starts (a 4 GB card cannot hold both).
- **Frontend**: React 19, TypeScript, Vite, Bun, TanStack Query and Form, a Mantine-based design system.

## What the launcher does

`./smart-meeting` (Linux, macOS) and `smart-meeting.cmd` (Windows, also used by `./smart-meeting` in Git Bash) install
uv if needed, then run `uv run --directory backend smart-meeting`, with the `cuda` extra when `nvidia-smi` finds a GPU, else the
`intel` extra (OpenVINO, used only when chosen) on Linux and Windows with an Intel CPU or GPU.
`make run` does the same. On first run, without admin rights:

| Component | How |
|---|---|
| uv, Python dependencies | automatic (CUDA libraries with an NVIDIA GPU, OpenVINO with Intel hardware, MLX on Apple Silicon) |
| Bun, web interface | Bun installed for the user (official build, works behind a proxy and on any x86-64 CPU); interface built on first run and after each update |
| Ollama | reused if already installed, otherwise downloaded to the user folder; started and stopped with the app |
| AI model (`qwen2.5:3b`, 1.9 GB; `qwen2.5:7b`, 4.7 GB, once chosen) | downloaded in the background, progress shown in the interface |
| Transcription model | chosen with the engine, see [Transcription engines](#transcription-engines) |
| Voice prints model | WeSpeaker ResNet34-LM (ONNX, 26 MB) |

The interface opens in a tab of the default browser. Launching again while it runs opens a new tab; a page left open
after a stop reloads itself on the next start. `--no-window` starts without a tab, `--port` changes the port,
`--install` adds the app to the system (Linux: `~/.local/share/applications/smart-meeting.desktop`; macOS:
`~/Applications/Smart Meeting.app`; Windows: a Start menu shortcut to `cmd.exe /c smart-meeting.cmd`, so that it can be
pinned). `make desktop` runs `--install`.

The app stops 10 seconds after its last page is closed, once no recording, import, AI answer or download is running.
The Quit button stops at once (a recording is stopped and its transcription finished first), like `Ctrl+C`.

## Audio capture

| System | What I hear | My microphone | Status |
|---|---|---|---|
| Linux | PipeWire monitor of the output (follows the call in automatic mode) | PipeWire (`pw-record`) | tested |
| Windows | WASAPI loopback of the chosen output | WASAPI | not tested yet |
| macOS | ScreenCaptureKit (whole system audio) | CoreAudio | not tested yet |

**Echo**: when the microphone hears the others (laptop speakers, or a virtual input carrying the call), the same
sentence is transcribed twice. A sentence of one source that overlaps a sentence of the other in time (give or take
4 s) with a similar text (at least 3 words, `difflib` ratio ≥ 0.6) is an echo: the microphone copy is dropped, or
removed if it was stored first (`meeting/echo.py`); the final check of the safety tracks recognizes it too. On macOS,
the automatic microphone skips virtual inputs (Microsoft Teams Audio, Zoom, Webex, BlackHole, Loopback…): taken as
the default input, the call itself was transcribed as "me".

If one source cannot be captured, the meeting goes on with the other one and the interface tells why. On macOS, a
capture blocked by the "Screen & System Audio Recording" permission is flagged (`permission_needed`): the interface
then offers a button that opens that pane of System Settings (`POST /api/audio/permission-settings`). In automatic
mode, the devices the applications actually use are followed during the meeting (a call starting later, a headset
plugged in).

## Transcription engines

The hardware is detected at startup (`hardware.py`, logged as `Hardware: …`) and Whisper runs on the best engine for it
(`transcription/engines.py`):

| Hardware | Engine | Model |
|---|---|---|
| Apple Silicon | MLX, on the GPU of the chip | `large-v3-turbo` |
| NVIDIA GPU | faster-whisper on CUDA | `large-v3-turbo`, `small` for the live draft |
| Anything else (Intel, AMD…) | faster-whisper on the CPU, one thread per physical core | `small` |

OpenVINO, Intel's engine, is only used when chosen (`SM_WHISPER_ENGINE=openvino`, with the `intel` extra the launcher
installs on Intel machines), on the CPU unless `SM_WHISPER_DEVICE=gpu`: on an integrated GPU it can be slower than
real time.

An engine that fails to load (missing driver, old GPU) gives way to faster-whisper on the CPU; the engine in use is
logged (`Transcription engine: …`). `SM_WHISPER_ENGINE`, `SM_WHISPER_MODEL` and `SM_WHISPER_DEVICE` force a choice.
OpenVINO decodes greedily and gives no "no speech" score: only the known phrases are filtered as hallucinations there.

**Falling behind**: during a meeting, the seconds of speech waiting for Whisper are followed. Past 30 s, the
provisional text is turned off (it takes Whisper's time); past 90 s and still growing over a minute, a lighter
setting takes over, at most once a minute: the `small` model on the same engine, then faster-whisper `small` on the
CPU. The switch is logged (`Transcription lightened to …`), and `/api/health` gives the model now in use.

Measured on an Apple M5 with `scripts/bench_transcription.py` (67 s French meeting, three voices):

| Engine | Live | Imported file |
|---|---|---|
| faster-whisper `small`, CPU | 1.4× real time, 13.7 % word errors | 6.8×, 6.6 % |
| MLX `large-v3-turbo`, GPU | 3.9×, 9.8 % | 12.4×, 4.9 % |

Measured on an Intel i7-11800H (8 cores) with an Intel UHD (TigerLake GT1) GPU, without its NVIDIA card, on 4
minutes of a real French call (reference: `large-v3-turbo` on the NVIDIA GPU):

| Engine | Live | Imported file |
|---|---|---|
| faster-whisper `small`, CPU | 2.0× real time, 16.8 % word errors | 11.8×, 19.1 % |
| OpenVINO `small`, CPU | 3.4×, 20.1 % | 12.8×, 17.6 % |
| OpenVINO `small`, Intel UHD GPU | under 0.4× real time: a meeting falls behind for good | |

To compare engines on another machine (run from `backend/`):

```bash
SM_WHISPER_ENGINE=faster-whisper uv run python scripts/bench_transcription.py \
  scripts/samples/reunion-test.mp4 --reference scripts/samples/reference.txt
SM_WHISPER_ENGINE=openvino uv run --extra intel python scripts/bench_transcription.py \
  scripts/samples/reunion-test.mp4 --reference scripts/samples/reference.txt
```

The Ollama started by the app runs with flash attention and an 8-bit context cache (half the memory for long
meetings), and with Vulkan on Intel GPUs (`OLLAMA_VULKAN=1`).

## Transcription

- Audio is cut into sentences at pauses (Silero VAD, 700 ms of silence, forced cut at 20 s), each transcribed once
  by Whisper, so there is nothing to deduplicate. The sentence being spoken is shown as a grey draft (a smaller model
  next to a large one on a GPU, refreshed about every 1.5 s).
- The language is detected per source and sticky (a few foreign words do not switch it), or chosen.
- A vocabulary of names and acronyms (settings) is given to Whisper as a prompt: a clear difference on proper names.
- **Imported files** are decoded by PyAV and transcribed in batches by faster-whisper's batched pipeline: about 8×
  faster than real time on a modest GPU (147 s of audio in 19 s on an NVIDIA T600). MLX and OpenVINO transcribe them in
  5-minute blocks cut at a silence, so that the progress moves. The upload is deleted once decoded.

## Speakers

- One voice print per sentence (WeSpeaker ResNet34-LM in ONNX, Kaldi filterbanks computed in numpy, no PyTorch, about
  60 ms per sentence on the CPU, in the Whisper thread).
- Live, a sentence starts a new voice only when it lasts at least 2 s and its cosine similarity to every known voice
  of its source is under 0.35; otherwise it joins the closest one. When the meeting ends, voices closer than 0.40
  are merged; a voice heard less than 30 s in all joins the closest main voice if their similarity is at least 0.20,
  and always under 10 s; then every sentence goes to its closest final voice.
- Calibration: a 2-person call gave 11 voices with the former thresholds (a sentence started a voice under 0.45, from
  1 s), 10 of them under 25 s. On a real call mixed with the user's microphone (2 people, 1 709 s), the former
  thresholds found 17 voices, these ones 3, each one 99 % a single person; a 4-voice sample keeps its 4 voices.
- The microphone is "me", unless the **meeting room** setting is on. Voices of the two sources are never merged.
- Imported files: speech turns are cut at 300 ms pauses, and Whisper's sentences are split word by word where the voice
  changes.
- Renaming a speaker updates the transcript, the actions and the minutes; an existing name merges both speakers.

## Nothing said is lost

- **Safety tracks**: during a meeting, the raw sound of each source is written to `audio/<id>/<source>-<start ms>.wav`
  of the data folder, in meeting time (silence fills a device switch), header updated and buffer flushed at each write.
  When the meeting ends, and at the next start after a crash, the speech of these tracks with no transcribed sentence
  (at least 2 s, 1 s away from any sentence) is transcribed and put in its place. The tracks are then deleted, unless
  the audio is kept. A 3-hour meeting takes about 700 MB during the meeting.
- **Pending sentences**: every sentence waiting for Whisper is in `pending/<id>/` until it is transcribed.
- **Self-restart**: a Whisper computation longer than 90 s (`SM_STALL_RESTART_S`), or an event loop frozen for 60 s,
  during a meeting restarts the process, which goes on recording the same meeting about one second later
  (`resume.json`, known voices in `voices.json`). Minutes interrupted by a restart are written again at the next start.
- **Frozen server**: launching again replaces a server that no longer answers after about 15 seconds. The Python
  stacks of a frozen server are appended to `hang-traces.log` (on Linux and macOS, `kill -USR1 <pid>` writes them on
  demand, the pid being in `server.pid`).
- numpy's OpenBLAS is limited to one thread per call: its own thread pool deadlocked and froze Whisper in a meeting.

## AI

- The minutes are generated with a JSON schema enforced by Ollama (structured outputs), at temperature 0. Every action
  must quote the transcript; owners and deadlines that do not appear in it are reset, and actions whose quote cannot be
  found are flagged.
- **Long meetings**: beyond the context of the model (`SM_OLLAMA_NUM_CTX=16384`, about 45 minutes of transcript), the
  minutes are written part by part, lists merged without duplicates, then one call sums the summaries up. For a
  question, old parts become short dated notes, kept in the database and written again only if their text changes.
- **During a meeting**, every call keeps the model loaded for 30 minutes (`SM_OLLAMA_MEETING_KEEP_ALIVE`): Ollama's
  prompt cache makes the next question read only the new sentences. Measured on an i7-11800H with a 4 GB GPU (the 7B
  model mostly on the CPU, about 75 tokens/s read and 5 tokens/s written): first question on 30 minutes of meeting
  about 2 minutes, next ones 15 to 50 s.
- **Minutes prepared during the meeting**: every minute, when the transcription is up to date and no question is
  being answered, the next finished part (about 10 minutes of speech) is analyzed in the background, the AI on the
  processor only (`num_gpu: 0`: the graphics card stays the transcription's). It stops as soon as 20 s of speech wait,
  or when a question comes. At the end, only the last part is read, then the summaries are summed up: about 40 s for
  33 minutes on an i7-11800H with a T600, whatever the length. The parts are kept with the notes, by digest of their
  words: regrouped or renamed speakers get their new names, and generating the minutes again reuses them.
- **The AI reads a compact transcript**: the sentences of a speaker in a row on one line, one timestamp per turn
  (a fifth shorter). The stored and exported transcript keeps one line per sentence.
- The measured speeds are kept in `ai-speed.json`, for the progress bars.
- **Comparing models**: `scripts/bench_analysis.py` writes the minutes of `scripts/samples/reunion-longue.txt` (a
  made-up 12-minute meeting with known decisions and actions) and answers two questions with each model given, through
  the app's code, and saves the answers for judging their quality (from `backend/`:
  `uv run python scripts/bench_analysis.py scripts/samples/reunion-longue.txt qwen2.5:3b qwen2.5:7b`). On an Apple M5,
  before the bounds of the schema: `qwen2.5:7b` 100 s for the minutes, `ministral-3:3b` (3 GB) 61 s with the most
  accurate minutes (owners of the actions), `granite4:3b` as fast but with actions given to the wrong people,
  `qwen3:4b` answering questions with its reasoning in English, `qwen2.5:3b` repeating itself until the timeout.
- Without a description in the schema, models wrote the title of the meeting as its summary: every field is described,
  and the instructions ask for plain text, without the actions copied into the decisions.
- **Prompts** are Markdown files in `backend/src/smart_meeting/llm/prompts/`, read at each call: an edit applies at
  once. A file of the same name in `prompts/` of the configuration folder (Linux:
  `~/.config/smart-meeting/prompts/analysis_system.md`) replaces the default one.

## Data

| System | Data folder |
|---|---|
| Linux | `~/.local/share/smart-meeting/` |
| macOS | `~/Library/Application Support/smart-meeting/` |
| Windows | `%LOCALAPPDATA%\smart-meeting\` |

It holds `smart-meeting.db` (meetings, transcripts, minutes, questions, tags, notes of long meetings), `audio/<id>/`
(the sound of the meeting being recorded, or of a meeting whose audio is kept), `pending/<id>/`, `preferences.json`,
`ai-speed.json`, `hang-traces.log` and `ollama.log`. To back up the history, copy the `.db` while the app is stopped;
to move it, set `SM_DATA_DIR`.

## Advanced settings

`SM_*` variables in `config.env` of the configuration folder (Linux: `~/.config/smart-meeting/`, macOS:
`~/Library/Application Support/smart-meeting/`, Windows: `%LOCALAPPDATA%\smart-meeting\`), or `backend/.env` in
development:

```bash
SM_USER_NAME=Alex                   # label of my microphone in the transcript, "I" for the AI
SM_REMOTE_NAME=Interlocuteur        # label of the other participants when voices are not told apart
SM_WHISPER_GLOSSARY="Atlas, OAuth, Kubernetes."  # names and acronyms to recognize
SM_WHISPER_ENGINE=auto              # or faster-whisper / mlx / openvino
SM_WHISPER_MODEL=auto               # or large-v3-turbo / medium / small
SM_WHISPER_DEVICE=auto              # faster-whisper: cuda / cpu; OpenVINO: gpu / cpu / npu
SM_WHISPER_CPU_THREADS=0            # faster-whisper on CPU; 0: one per physical core
SM_WHISPER_PARTIAL_MODEL=auto       # live draft: small next to the main model on GPU, none to disable
SM_OLLAMA_FAST_MODEL=qwen2.5:3b     # "fast" AI model of the settings (the default)
SM_OLLAMA_PRECISE_MODEL=qwen2.5:7b  # "precise" AI model of the settings
SM_OLLAMA_MODEL=                    # forces a model whatever the choice in the settings
SM_OLLAMA_NUM_CTX=16384             # context of the AI; larger: fewer parts for long meetings, more memory
SM_OLLAMA_MEETING_KEEP_ALIVE=30m    # the model stays loaded between questions during a meeting
SM_OLLAMA_MEETING_THREADS=4         # AI threads during a meeting (default: chosen by Ollama)
SM_OLLAMA_BIN=/path/to/ollama       # if Ollama is not on the PATH
SM_STALL_RESTART_S=90               # a stuck transcription restarts the server after this long
SM_DATA_DIR=~/.local/share/smart-meeting
SM_PORT=8417                        # local port of the interface
```

## Updates

Every few hours, the server reads the latest release on GitHub (`GET /api/update`, `smart_meeting/update.py`), through
the proxy of the system. `POST /api/update` installs it the way this installation was made: `git pull --ff-only` in a
clone, the `.deb` of the release in `/opt/smart-meeting` (checked against the SHA-256 GitHub gives, installed with
`pkexec apt-get install`), and refused during a meeting, an import or the minutes. The browser version then restarts
through the launcher (new dependencies, new interface) and the page reloads itself; the Linux app stops the server and
restarts itself. The macOS app only shows the page of the release: its bundled server does not know its version, so
the app compares the release with its own. The Windows app shows the page too (its server knows its version, from the
package metadata bundled with it): the new installer goes over the current version.

## Privacy

The API only listens on `127.0.0.1`. Calls to Ollama ignore the proxy, a remote Ollama URL is refused, and the Ollama
started by the app runs with its cloud features disabled (`OLLAMA_NO_CLOUD=1`). Telemetry is disabled (Hugging Face
hub, FastAPI). The sound is only written to disk during the meeting and deleted once everything is transcribed,
unless kept.

## Develop

```bash
make dev     # backend with auto-reload (port 8417) + Vite (http://127.0.0.1:5173)
make check   # everything that must pass before a commit (lint + tests)
make api     # regenerates the frontend API client from the backend OpenAPI schema
```

Backend checked by **Ruff** and **pytest** (tests never touch the real data folder). The frontend (`frontend/`)
follows strict rules:

- **Bun** (never npm), **Biome**, **Vitest**; `bun run check:rules` checks the rules below (`frontend/scripts/`, Bun
  scripts so that they also run on Windows);
- a Mantine-based design system: its components rather than Mantine's, texts only through `Typography` variants,
  tokens rather than raw values, no CSS file;
- **i18next**: no hardcoded text, everything in `src/locales/fr.ts` (and `en.ts`);
- **TanStack Query** (`services/*QueryOptions.ts` factories) and **TanStack Form**; API client **generated by Orval**
  from the FastAPI OpenAPI schema (`src/api/generated/`, never edited by hand);
- one role per folder (`pages/`, `features/`, `components/`, `contexts/`, `hooks/`, `services/`, `types/`,
  `constants/`, `utils/`, `tests/`), one default export per file, arrow functions, no `let` nor loop, `@/…` imports,
  every type in `types/`, external data checked by type guards, no HTML tag in JSX.

The README screenshots come from a separate instance with fictional meetings (`SM_DATA_DIR` pointing to a demo
folder), never from real meetings.

## macOS app

`macos/` holds a native app (SwiftUI, macOS 14+) for people who do not use a terminal: the same server, bundled
inside it by PyInstaller (`packaging/macos/backend.spec`) and started with `--app`, behind a native interface
(sidebar, inspector, settings window, menu bar icon while recording) that talks to the same HTTP API and
WebSockets as the web interface.

```bash
make mac     # build/macos/Smart-Meeting-<version>.dmg, ad hoc signature (this Mac only)
DEVELOPER_ID="Developer ID Application: Name (TEAMID)" NOTARY_PROFILE=smart-meeting make mac   # to distribute
packaging/macos/build.sh --store   # build/macos/Smart-Meeting-<version>.pkg for the App Store (Transporter)
```

`NOTARY_PROFILE` names notarization credentials stored once with `xcrun notarytool store-credentials`. Ollama is
bundled (`packaging/macos/fetch-ollama.sh`: a pinned release, arm64 only, without its MLX engine) since the App Store
forbids downloading code; the models are still downloaded at first launch. The App Store build runs in the sandbox
(`SmartMeeting.appstore.entitlements`, the server and Ollama inheriting it) and needs the "Apple Distribution" and
"Mac Installer Distribution" certificates and a Mac App Store provisioning profile named "Smart Meeting App Store"
(`STORE_PROFILE`). To work on
the interface, `cd macos && xcodegen` then open `SmartMeeting.xcodeproj`: a Debug build without the bundled server
uses the one started with `./smart-meeting --no-window`. The server's log is in `~/Library/Logs/Smart Meeting/`.

**Windows app** (`windows/smart_meeting_win`, `packaging/windows`): `Smart Meeting.exe` opens a window (Edge
WebView2, through pywebview, part of Windows 10 and 11) on the web interface, served by the server: the same
executable started without a console (`--server`, PyInstaller bundle with the built interface), which writes to
`%LOCALAPPDATA%\smart-meeting\server.log` and stops with the window (closing during a recording asks first). A server
already answering (the browser version) is used and left running. The installer (Inno Setup, `smart-meeting.iss`)
installs for the user, without admin rights, in `%LOCALAPPDATA%\Programs\Smart Meeting`, with a Start menu shortcut
and an uninstaller. It is not signed (a code signing certificate is needed for that): SmartScreen asks to confirm the
first launch. The CUDA libraries are not bundled (over 1 GB): with an NVIDIA card, Whisper runs on the CPU. Build on
Windows with Git Bash, uv, Bun and Inno Setup 6: `packaging/windows/build.sh` (`make windows`); GitHub does it for
every release, and installs and starts the result before adding it.

**Releases, from any computer**: bump the version (`backend/pyproject.toml`, `frontend/package.json`,
`macos/project.yml`), commit, then `make release`: it tags `v<version>` and pushes it. The `Release` workflow
(`.github/workflows/release.yml`) then creates the release of the tag as a draft (unless there is one already), and
builds in parallel the `.deb` on Ubuntu, the Windows installer on a GitHub Windows machine (installed and started
there first) and the disk image on a GitHub Mac, signed with the Developer ID and notarized; the three are added to
the release. Write the notes and publish it:
`gh release edit v<version> --notes-file notes.md --draft=false`. The workflow also runs by hand on an existing tag
(`gh workflow run release.yml -f tag=v0.2.4`), or on `main` without a tag (files in the artifacts of the run only).

To sign and notarize the disk image on GitHub, store once the repository secrets, from the Mac holding the
certificate:

```bash
# 1. Keychain Access > My Certificates > "Developer ID Application: …" > right click, Export (.p12, with a password)
# 2. appleid.apple.com > Sign-In and Security > App-Specific Passwords: a new one
packaging/macos/ci-secrets.sh DeveloperID.p12   # asks the Apple ID and both passwords, checks the .p12
```

Without them, the image only has an ad hoc signature, which macOS refuses to open once downloaded: it stays in the
artifacts of the run and is never added to a release.

## Linux app

`linux/` holds a native GNOME app (Python, GTK 4 and libadwaita from the system: `python3-gi`, `gir1.2-gtk-4.0`,
`gir1.2-adw-1` ≥ 1.5, `gir1.2-soup-3.0`): the same features as the macOS app, on the same HTTP API and WebSockets
(history in the sidebar, live recording with levels and a confirmed stop, questions, minutes, transcript in a side
pane with named speakers, settings dialog, notification when minutes are ready). It starts the server with
`./smart-meeting --app` from a login shell (the user's PATH and proxy), or uses one already answering, and stops the
one it started when it quits, once the meeting being recorded is transcribed.

```bash
linux/smart-meeting-app      # from a clone (uses the server of ./smart-meeting --no-window if it runs)
make deb                     # build/linux/smart-meeting_<version>_all.deb
```

The package puts the project in `/opt/smart-meeting` (read-only: the Python environment goes to
`~/.local/share/smart-meeting/venv`, `UV_PROJECT_ENVIRONMENT`), the app in the applications menu
(`io.github.graffkevin.SmartMeeting`) and `smart-meeting-app` on the PATH. Nothing is compiled: uv, the Python
dependencies, Ollama and the models are installed for each user on first launch, like with `./smart-meeting`. The
server's log is in `~/.local/state/smart-meeting/server.log` (menu > Server log).
