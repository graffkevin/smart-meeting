# Smart Meeting : architecture

Application locale (Ubuntu 24.04 + PipeWire) qui capture une réunion (ce que j'entends dans le casque + mon micro), la
transcrit en temps réel avec faster-whisper et produit un compte rendu structuré avec un LLM local (Ollama).
**Aucun audio ni aucune transcription ne quitte la machine.**

## 1. Faisabilité (vérifiée sur le poste cible)

| Brique | Constat |
|---|---|
| PipeWire 1.0.5 | `pw-record` capture une source **ou le monitor d'une sortie** (`stream.capture.sink = true`) en PCM brut mono 16 kHz sur stdout. Rééchantillonnage et downmix faits par PipeWire. Pas besoin de `pactl`/`parec` (non installés). |
| Découverte | `pw-dump` (JSON) donne périphériques, défauts et liens applications → périphériques. |
| Whisper | `large-v3-turbo` en `int8_float16` sur la NVIDIA T600 (4 Go) : 15 s d'audio transcrites en ~2 s (≈ 7× temps réel), ~1,5 Go de VRAM. Nécessite cuBLAS 12 / cuDNN 9, installés via pip (extra `cuda`) et préchargés au démarrage. Repli CPU `int8` automatique. |
| Ollama | `qwen2.5:7b` (Q4, 4,7 Go) : partiellement sur GPU, le reste sur CPU (16 cœurs, 31 Go RAM). Analyse en une à quelques minutes pour une réunion d'une heure. |

## 2. Architecture

```
          ┌─────────────── machine locale ───────────────────────────────────────┐
 Casque ──┤ PipeWire ── pw-record (monitor sortie) ─┐                           │
 Micro ───┤          └─ pw-record (micro) ───────────┤                           │
          │                                          ▼                           │
          │  FastAPI (127.0.0.1)   audio/ : capture + VAD Silero → énoncés       │
          │   ├─ transcription/ : faster-whisper (1 thread GPU, file d'attente)  │
          │   ├─ meeting/ : cycle de vie, événements, compte rendu Markdown      │
          │   ├─ llm/ : Ollama (JSON schema) + garde-fous anti-invention         │
          │   └─ db.py : SQLite                                                  │
          │        │ REST + WebSocket                                            │
          │  React (servi par FastAPI, fenêtre d'application)                    │
          └──────────────────────────────────────────────────────────────────────┘
```

Monolithe Python + SPA React, pas de microservices. Un seul processus en usage normal (`./smart-meeting`).

Choix par rapport à la proposition initiale :

- **Capture par `pw-record` en sous-processus** plutôt qu'une bibliothèque Python : natif PipeWire, robuste, aucune
  dépendance C à compiler. `sounddevice`/PortAudio ne voit pas proprement les monitors. FFmpeg n'apporte rien ici.
- **Segmentation par pauses (VAD)** plutôt que des chunks fixes (voir §4).
- **SQLite via `sqlite3`** (sans ORM) : 4 tables, requêtes simples.
- **Pas de routeur ni de librairie d'état côté React** : deux écrans.

## 3. Capturer le micro et ce que j'entends dans le casque

- **Distant** : PipeWire expose pour chaque sortie (sink) un *monitor* : une copie de ce qui y est joué.
  `pw-record --target <sortie> -P '{ stream.capture.sink = true }'` l'enregistre en lecture seule : le casque, son
  volume et le routage des applications ne sont pas modifiés. C'est indépendant de Firefox : tout ce qui est joué dans
  le casque est capté (Teams desktop, Zoom, navigateur…).
- **Moi** : `pw-record --target <micro>` en parallèle. Le micro est partagé : Teams continue de l'utiliser.
- **Mode automatique (par défaut)** : le backend lit les liens PipeWire (`pw-dump`) pour trouver la sortie sur
  laquelle une application joue réellement et le micro qu'elle utilise (flux actifs prioritaires, défauts système en
  repli). Toutes les 2 s, il revérifie et bascule la capture si l'appel démarre après l'enregistrement ou si le casque
  change. Sur ce poste, la sortie par défaut est l'adaptateur Unitek et non le casque USB : le mode automatique évite
  de capter la mauvaise sortie.
- **Diarisation gratuite Moi / Interlocuteur** : deux flux séparés, donc chaque segment est étiqueté par sa source.
  Avec un casque, il n'y a pas d'écho du distant dans le micro.

## 4. Difficultés techniques et choix

**Temps réel Whisper.** Whisper traite des fenêtres de 30 s et n'est pas un modèle streaming. Des chunks fixes de
quelques secondes coupent les mots, puis demandent du recouvrement et une déduplication fragile. Le choix retenu :

- VAD Silero (fourni par faster-whisper) en flux, fenêtres de 32 ms, sur chaque source ;
- un énoncé se termine après **700 ms de silence** ; il est forcé à **20 s** au point le plus calme du dernier tiers ;
  300 ms de pré-roll et 200 ms de post-roll ;
- chaque énoncé est transcrit **une seule fois** : pas de doublon ni de recouvrement à fusionner ;
- contexte : le glossaire (`SM_WHISPER_GLOSSARY`) et la fin du texte précédent de la même source sont passés en
  `initial_prompt`. Mesuré : avec le glossaire, « June / jeu Petform / la pi » deviennent « JUNN / Géoplateforme / API » ;
- latence observée : environ 1 à 2 s après la fin de la phrase.

**Hallucinations Whisper** (« Sous-titres réalisés par la communauté d'Amara.org » sur du silence) : le VAD ne laisse
passer que de la parole, et les phrases connues ou les segments `no_speech_prob > 0.6` à faible confiance sont filtrés.

**Diarisation fine** (distinguer plusieurs interlocuteurs distants) : nécessite pyannote (modèles HF à accepter,
GPU partagé, moins fiable en temps réel). Repoussée en étape 2, en post-traitement sur l'audio distant conservé.

**PipeWire.** Les noms de nœuds (`node.name`) sont stables, contrairement aux ids. Un casque Bluetooth change de nœud
en passant en profil « appel » : le mode automatique suit. Un `pw-record` qui meurt (périphérique débranché) se voit
sur le vumètre ; la reprise automatique ne couvre que le mode auto.

**VRAM 4 Go.** Whisper (~1,5 Go) reste chargé ; Ollama ajuste lui-même le nombre de couches mises sur le GPU.

**LLM qui invente.** Sortie contrainte par un JSON Schema (structured outputs Ollama) à température 0. Le prompt
impose `null` pour tout ce qui n'a pas été dit, puis le backend vérifie :

- responsable et échéance doivent apparaître dans la transcription, sinon ils passent à `null` ;
- chaque action doit citer la transcription ; une citation introuvable est signalée (⚠️) dans le compte rendu.

## 5. Arborescence

```
smart-meeting/
├── smart-meeting                 # lanceur (serveur + fenêtre)
├── Makefile                      # install, build, run, dev, test, desktop
├── packaging/smart-meeting.desktop
├── docs/ARCHITECTURE.md
├── backend/                      # Python 3.12, uv
│   ├── pyproject.toml
│   ├── src/smart_meeting/
│   │   ├── main.py               # app FastAPI, lifespan
│   │   ├── launcher.py           # commande `smart-meeting`
│   │   ├── provision.py          # installation d'Ollama et du modèle au premier lancement
│   │   ├── config.py             # réglages SM_*
│   │   ├── models.py             # modèles Pydantic (API + LLM)
│   │   ├── db.py                 # SQLite
│   │   ├── api/routes.py         # REST + WebSocket
│   │   ├── audio/                # devices.py (pw-dump), capture.py (pw-record), decode.py (ffmpeg), segmenter.py (VAD)
│   │   ├── transcription/whisper.py
│   │   ├── llm/analysis.py       # Ollama, prompt, garde-fous
│   │   └── meeting/              # service.py (orchestration), events.py, report.py (Markdown)
│   └── tests/
└── frontend/                     # React 19 + TypeScript + Vite
    └── src/  api.ts, App.tsx, HomePage.tsx, MeetingPage.tsx, format.ts, styles.css
```

## 6. Données et API

### SQLite (`~/.local/share/smart-meeting/smart-meeting.db`)

| Table | Colonnes |
|---|---|
| `meetings` | id, title, status, started_at, ended_at, mic_device, remote_device, keep_audio, transcript, summary, analysis_json, error, source_file, created_at |
| `segments` | id, meeting_id, source (`mic`/`remote`), speaker, start_s, end_s, text |
| `decisions` | id, meeting_id, text |
| `actions` | id, meeting_id, task, owner, deadline, quote, verified |

`start_s`/`end_s` sont en secondes depuis le début de la réunion. L'heure affichée vaut `started_at + start_s`.
`analysis_json` garde l'analyse complète (questions, risques, points techniques). Décisions et actions sont aussi
normalisées pour de futures requêtes transverses.

Statuts : `recording → transcribing → transcribed → analyzing → done` (ou `error`). Une analyse en échec revient à
`transcribed` avec un message, et peut être relancée.

**Audio** : par défaut, il n'est **jamais écrit sur disque** (traité en mémoire). Avec l'option « Conserver l'audio »,
deux WAV 16 kHz sont écrits dans `~/.local/share/smart-meeting/audio/<id>/`, supprimables depuis l'interface.

### Endpoints (`/api`)

| Méthode | Chemin | Rôle |
|---|---|---|
| GET | `/health` | état de Whisper, d'Ollama et du modèle, réunion active |
| POST | `/shutdown` | bouton Quitter : arrête la réunion en cours, termine sa transcription puis arrête le serveur |
| GET | `/audio/devices` | micros, sorties, et périphériques actuellement utilisés |
| GET | `/meetings?q=` | historique, du plus récent au plus ancien, avec nombre d'actions ; `q` cherche dans titres, résumés et transcriptions (insensible à la casse et aux accents, tous les mots requis) |
| POST | `/meetings` | crée et démarre l'enregistrement `{title, mic_device?, remote_device?, keep_audio}` (`null` = auto) |
| GET | `/meetings/{id}` | réunion, segments, analyse, périphériques capturés |
| PATCH | `/meetings/{id}` | renommer |
| POST | `/meetings/import` | multipart `file` (+ `title`) : transcrit et analyse un fichier audio/vidéo |
| POST | `/meetings/{id}/stop` | arrête la capture, termine la transcription puis lance l'analyse |
| POST | `/meetings/{id}/analyze` | (re)lance l'analyse IA |
| GET | `/meetings/{id}/report.md` | compte rendu Markdown |
| DELETE | `/meetings/{id}/audio` | supprime l'audio brut |
| DELETE | `/meetings/{id}` | supprime la réunion |
| WS | `/meetings/{id}/ws` | événements `segment`, `status`, `levels` (vumètres + file d'attente), `devices`, `progress` (import) |

## 7. Étapes

1. ✅ Capture PipeWire des deux sources, segmentation VAD, transcription Whisper GPU, WebSocket.
2. ✅ SQLite, historique, compte rendu Markdown copiable.
3. ✅ Analyse Ollama avec JSON Schema et garde-fous.
4. ✅ Interface : démarrer, durée, stop, vumètres, transcription en direct, compte rendu.
5. ✅ Lanceur unique, entrée de menu GNOME, mode périphériques automatique.
6. ✅ Installation « plug & play » : `./smart-meeting` installe uv, les dépendances et l'interface ; l'application
   provisionne Ollama (`provision.py` : binaire dans `~/.local/opt/ollama`, modèle téléchargé depuis le registre
   Ollama avec reprise et vérification sha256, compatible proxy) et affiche la progression dans `/api/health`.
7. ✅ Import de fichiers audio/vidéo : ffmpeg décode en flux vers le même découpage VAD + Whisper (le pipe régule
   ffmpeg pendant que Whisper travaille). `meetings.source_file` est renseigné ; horodatage relatif au fichier.
8. À venir, une fois la chaîne validée en réunion réelle :
   - réglage du VAD et du glossaire sur de vraies réunions ;
   - découpage map-reduce pour les réunions qui dépassent le contexte du LLM ;
   - diarisation pyannote du flux distant ;
   - édition du compte rendu ;
   - recherche dans l'historique.

## Confidentialité

- API liée à `127.0.0.1` uniquement.
- L'appel à Ollama ignore les variables proxy (`trust_env=False`). Une URL Ollama non locale est refusée au démarrage,
  sauf `SM_ALLOW_REMOTE_LLM=true`.
- Les seuls accès réseau sont le téléchargement unique des modèles (Whisper depuis Hugging Face, télémétrie HF
  désactivée ; modèle Ollama). Après ce premier téléchargement, `HF_HUB_OFFLINE=1` rend Whisper totalement hors ligne.
- Le frontend n'a aucune dépendance externe à l'exécution (ni CDN, ni police distante, ni analytics).
