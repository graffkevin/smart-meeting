# Smart Meeting

Transcription en direct et compte rendu automatique de réunions, **100 % local** (Ubuntu + PipeWire, faster-whisper,
Ollama).

Pendant une visio (Teams, Meet… dans Firefox ou une application), Smart Meeting écoute ce qui sort dans le casque et
ce qui entre dans le micro, affiche la transcription au fil de l'eau (« Moi » / « Interlocuteur ») puis génère un
compte rendu : résumé, décisions, actions, questions, risques. Le compte rendu se copie en Markdown.

Architecture et choix techniques : [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Installation

Linux, macOS et Windows : cloner le dépôt, puis `make run`. Le premier lancement installe tout le reste.

| Système | À installer une fois | Lancer |
|---|---|---|
| **Ubuntu** (22.10+, PipeWire) | `sudo apt install git make nodejs npm` (souvent déjà présents) | `make run`, `./smart-meeting` ou le menu (`make desktop`) |
| **macOS** (13 Ventura+) | `xcode-select --install` (git, make) et [Node.js](https://nodejs.org) | `make run` |
| **Windows** 10/11 | `winget install Git.Git ezwinports.make OpenJS.NodeJS.LTS` | `make run` |

```bash
git clone https://gitlab.ign.fr/kgraff/smart-meeting.git
cd smart-meeting
make run
```

`make run` détecte le système et installe sans droits administrateur :

| Élément | Installation |
|---|---|
| uv, dépendances Python | automatique (bibliothèques CUDA seulement si un GPU NVIDIA est présent) |
| Interface web | construite au premier lancement et après chaque mise à jour du code |
| Ollama | réutilisé s'il est déjà installé, sinon téléchargé dans le dossier utilisateur ; démarré et arrêté avec l'application |
| Modèle IA (`qwen2.5:7b`, 4,7 Go) | téléchargé en arrière-plan, progression affichée dans l'interface |
| Modèle de transcription | `large-v3-turbo` avec GPU NVIDIA, `small` sinon (Mac, PC sans GPU) |

> **Le premier lancement peut être long** : jusqu'à environ 8 Go à télécharger (Ollama 1,4 Go, modèle IA 4,7 Go,
> modèle de transcription 1,6 Go), soit de 10 à 30 minutes selon la connexion. Les lancements suivants prennent
> quelques secondes. Si Ollama est déjà installé avec le modèle, rien de tout cela n'est retéléchargé.

L'application est utilisable pendant les téléchargements : l'enregistrement fonctionne, l'analyse IA arrive à la fin.
`make info` affiche ce qui a été détecté.

### Capture audio selon le système

| Système | Ce que j'entends | Mon micro | État |
|---|---|---|---|
| Linux | monitor PipeWire de la sortie (suit l'appel en mode automatique) | PipeWire | testé |
| Windows | WASAPI loopback de la sortie choisie | WASAPI | **non testé** |
| macOS | ScreenCaptureKit (audio de tout le système) | CoreAudio | **non testé** |

Sur **macOS**, au premier enregistrement, le système demande l'autorisation « Enregistrement de l'écran et de l'audio
système » pour le terminal qui lance Smart Meeting : l'accorder dans Réglages Système > Confidentialité et sécurité,
puis relancer. Si une des deux sources ne peut pas être capturée, la réunion continue avec l'autre et l'interface
indique pourquoi ; l'import de fichiers fonctionne dans tous les cas.

## Utilisation

### Lancer

| Comment | Commande |
|---|---|
| **Menu des applications** (Linux) | touche Super, taper « Smart Meeting » (après `make desktop` ; épinglable dans le dock) |
| **Terminal** (tous systèmes) | `make run` dans le dossier du projet (ou `./smart-meeting` sous Linux et macOS) |
| **Navigateur**, si déjà lancée | http://127.0.0.1:8417 |

Le serveur local démarre, ainsi qu'Ollama s'il ne tourne pas déjà, et l'interface s'ouvre dans le navigateur.
L'application est cette page web locale, servie par votre machine : rien ne passe par Internet.

### Arrêter

Bouton **Quitter** en haut à droite de l'interface (arrête tout, Ollama compris ; une réunion en cours est d'abord
stoppée et sa transcription terminée), ou `Ctrl+C` dans le terminal si elle a été lancée depuis un terminal. Fermer
l'onglet ne l'arrête pas.

### Enregistrer une réunion

1. Titre (facultatif), puis **Démarrer l'enregistrement**. Par défaut, les périphériques sont en mode automatique :
   le micro et la sortie réellement utilisés par vos applications sont suivis, même si l'appel démarre après.
2. La transcription s'affiche en direct, avec la durée et un vumètre par source.
3. **Stop** : la transcription se termine, puis l'analyse IA démarre.
4. **Copier le compte rendu (Markdown)**.

### Importer une vidéo ou un audio

Bloc « Importer une vidéo ou un audio » de l'accueil (replay, webinaire, mp4/mkv/webm/mp3/wav…) : même chaîne,
plus rapide que le temps réel (≈ 6× sur GPU), horodatage en position dans le fichier. Le fichier envoyé est supprimé dès qu'il est décodé.
Une vidéo jouée dans le casque pendant un enregistrement fonctionne aussi.

### Historique

Les réunions sont conservées uniquement sur la machine, dans une base SQLite (jamais dans le dépôt) :

| Système | Dossier |
|---|---|
| Linux | `~/.local/share/smart-meeting/` |
| macOS | `~/Library/Application Support/smart-meeting/` |
| Windows | `%LOCALAPPDATA%\smart-meeting\` |

Il contient `smart-meeting.db` (réunions, transcriptions, résumés, décisions, actions), `audio/<id>/` si l'audio
brut a été conservé, et `ollama.log`. Pour sauvegarder l'historique, copier le `.db` application arrêtée ; pour le
déplacer, `SM_DATA_DIR=/chemin` dans `config.env`.

## Configuration

Variables `SM_*`, dans `config.env` du dossier de configuration (Linux : `~/.config/smart-meeting/`, macOS :
`~/Library/Application Support/smart-meeting/`, Windows : `%LOCALAPPDATA%\smart-meeting\`), ou `backend/.env` en
développement :

```bash
SM_USER_NAME=Kevin                  # libellé de mon micro dans la transcription et les actions
SM_REMOTE_NAME=Interlocuteur
SM_WHISPER_GLOSSARY="Réunion JUNN, Géoplateforme, IGN, API, 3D Tiles, IGN-MUT."  # vocabulaire métier
SM_WHISPER_MODEL=auto               # ou large-v3-turbo / medium / small
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
