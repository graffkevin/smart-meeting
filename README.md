# Smart Meeting

Transcription en direct et compte rendu automatique de réunions, **100 % local** (Ubuntu + PipeWire, faster-whisper,
Ollama).

Pendant une visio (Teams, Meet… dans Firefox ou une application), Smart Meeting écoute ce qui sort dans le casque et
ce qui entre dans le micro, affiche la transcription au fil de l'eau (« Moi » / « Interlocuteur ») puis génère un
compte rendu : résumé, décisions, actions, questions, risques. Le compte rendu se copie en Markdown.

Architecture et choix techniques : [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Installation

Rien à installer à la main : cloner le dépôt et lancer.

```bash
git clone https://gitlab.ign.fr/kgraff/smart-meeting.git && cd smart-meeting
./smart-meeting     # premier lancement : installe ce qui manque, puis ouvre l'application
make desktop        # optionnel : ajoute « Smart Meeting » au menu des applications GNOME
```

Au premier lancement, sans sudo :

| Élément | Installation |
|---|---|
| uv, dépendances Python | automatique (bibliothèques CUDA seulement si un GPU NVIDIA est présent) |
| Interface web | construite au premier lancement et après chaque mise à jour du code |
| Ollama | téléchargé dans `~/.local/opt/ollama` s'il n'est pas déjà installé, démarré et arrêté avec l'application |
| Modèle IA (`qwen2.5:7b`, 4,7 Go) | téléchargé en arrière-plan, progression affichée dans l'interface |
| Modèle de transcription (1,6 Go) | téléchargé au premier chargement |

L'application est utilisable pendant les téléchargements : l'enregistrement fonctionne, l'analyse IA arrive à la
fin. Seuls quelques paquets système nécessitent sudo ; s'il en manque, le lanceur affiche la commande exacte
(`sudo apt install pipewire-bin ffmpeg zstd nodejs npm`, déjà présents sur un Ubuntu 24.04 de développement).

Sans GPU NVIDIA, Whisper tourne sur CPU : choisir alors un modèle plus léger (`SM_WHISPER_MODEL=small`).

## Utilisation

Lancer **Smart Meeting** depuis le menu, ou `./smart-meeting` (interface sur http://127.0.0.1:8417). Le serveur local démarre, ainsi qu'Ollama s'il ne
tourne pas déjà, et l'application s'ouvre dans une fenêtre.

1. Titre (facultatif), puis **Démarrer l'enregistrement**. Par défaut, les périphériques sont en mode automatique :
   le micro et la sortie réellement utilisés par vos applications sont suivis, même si l'appel démarre après.
2. La transcription s'affiche en direct, avec la durée et un vumètre par source.
3. **Stop** : la transcription se termine, puis l'analyse IA démarre.
4. **Copier le compte rendu (Markdown)**.
5. **Quitter** (en haut à droite) arrête tout, Ollama compris. Une réunion en cours est d'abord stoppée et sa
   transcription terminée. Depuis un terminal, `Ctrl+C` fait la même chose.

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
