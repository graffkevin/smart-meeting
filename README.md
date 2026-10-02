# Smart Meeting

Transcription en direct et compte rendu automatique de réunions, **100 % local** (Ubuntu + PipeWire, faster-whisper,
Ollama).

Pendant une visio (Teams, Meet… dans Firefox ou une application), Smart Meeting écoute ce qui sort dans le casque et
ce qui entre dans le micro, affiche la transcription au fil de l'eau (« Moi » / « Interlocuteur ») puis génère un
compte rendu : résumé, décisions, actions, questions, risques. Le compte rendu se copie en Markdown.

Architecture et choix techniques : [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Prérequis

- Ubuntu 24.04 avec PipeWire (`pw-record`, `pw-dump` : paquet `pipewire-bin`, installé par défaut)
- [uv](https://docs.astral.sh/uv/), Node.js ≥ 18 et ffmpeg (import de fichiers)
- [Ollama](https://ollama.com) et un modèle : `ollama pull qwen2.5:7b`
- Optionnel : GPU NVIDIA. Les bibliothèques CUDA sont installées par `make install` ; sans GPU, Whisper tourne sur CPU.

## Installation

```bash
make install        # dépendances backend + frontend, build de l'interface
make desktop        # ajoute « Smart Meeting » au menu des applications GNOME
```

Au premier lancement, le modèle Whisper (~1,6 Go) est téléchargé une fois depuis Hugging Face.

## Utilisation

Lancer **Smart Meeting** depuis le menu, ou `./smart-meeting` (interface sur http://127.0.0.1:8417). Le serveur local démarre, ainsi qu'Ollama s'il ne
tourne pas déjà, et l'application s'ouvre dans une fenêtre.

1. Titre (facultatif), puis **Démarrer l'enregistrement**. Par défaut, les périphériques sont en mode automatique :
   le micro et la sortie réellement utilisés par vos applications sont suivis, même si l'appel démarre après.
2. La transcription s'affiche en direct, avec la durée et un vumètre par source.
3. **Stop** : la transcription se termine, puis l'analyse IA démarre.
4. **Copier le compte rendu (Markdown)**.

**Importer une vidéo ou un audio** (replay, webinaire, mp4/mkv/webm/mp3/wav…) : même chaîne, plus rapide que le temps
réel (≈ 6× sur GPU), horodatage en position dans le fichier. Le fichier envoyé est supprimé dès qu'il est décodé.
Une vidéo jouée dans le casque pendant un enregistrement fonctionne aussi.

## Configuration

Variables `SM_*`, dans `~/.config/smart-meeting/config.env` (ou `backend/.env` en développement) :

```bash
SM_USER_NAME=Kevin                  # libellé de mon micro dans la transcription et les actions
SM_REMOTE_NAME=Interlocuteur
SM_WHISPER_GLOSSARY="Réunion JUNN, Géoplateforme, IGN, API, 3D Tiles, IGN-MUT."  # vocabulaire métier
SM_WHISPER_MODEL=large-v3-turbo     # ou small / medium sur CPU
SM_OLLAMA_MODEL=qwen2.5:7b
SM_OLLAMA_BIN=/chemin/vers/ollama   # si Ollama n'est pas dans le PATH
SM_DATA_DIR=~/.local/share/smart-meeting
SM_PORT=8417                        # port local de l'interface
```

Le glossaire améliore nettement les termes techniques : sans lui, « JUNN » devient « June » et « Géoplateforme »
devient « jeu Petform ».

## Développement

```bash
make dev     # backend avec rechargement (port 8417) + Vite (http://127.0.0.1:5173)
make test    # tests backend + vérification TypeScript
make lint
```

## Confidentialité

Aucun audio ni aucune transcription ne quitte la machine. L'API écoute uniquement sur `127.0.0.1`, l'appel à Ollama
ignore le proxy, et une URL Ollama distante est refusée. Par défaut, l'audio brut n'est jamais écrit sur disque.
