"""Texts the server shows to users (errors, install steps), in the interface language.

The language is the one chosen in the interface (preferences), read at each call so that a change
applies at once. The instructions given to the AI are not here: they stay in French, and the
language of its answers is set separately (llm/analysis.py).
"""

from smart_meeting.config import get_settings

MESSAGES: dict[str, dict[str, str]] = {
    # Meetings
    "meeting_not_found": {"fr": "Réunion introuvable", "en": "Meeting not found"},
    "meeting_in_progress": {
        "fr": "Une réunion est déjà en cours",
        "en": "A meeting is already being recorded",
    },
    "recording_in_progress": {
        "fr": "Une réunion est en cours d'enregistrement",
        "en": "A meeting is being recorded",
    },
    "not_recording": {
        "fr": "Cette réunion n'est pas en cours d'enregistrement",
        "en": "This meeting is not being recorded",
    },
    "already_stopping": {"fr": "Arrêt déjà en cours", "en": "Already stopping"},
    "meeting_busy": {"fr": "Réunion en cours", "en": "Meeting in progress"},
    "import_in_progress": {
        "fr": "Un import est déjà en cours",
        "en": "A file is already being imported",
    },
    "interrupted": {
        "fr": "Interrompue (redémarrage du serveur)",
        "en": "Interrupted (server restarted)",
    },
    "whisper_unavailable": {
        "fr": "Transcription indisponible : {detail}",
        "en": "Transcription unavailable: {detail}",
    },
    # Audio
    "audio_unavailable": {"fr": "Audio indisponible : {error}", "en": "Audio unavailable: {error}"},
    "no_audio_source": {
        "fr": "Aucune source audio capturée ({errors})",
        "en": "No audio source captured ({errors})",
    },
    "device_not_found": {
        "fr": "Périphérique introuvable : {device}",
        "en": "Device not found: {device}",
    },
    "default_device": {"fr": "par défaut", "en": "default"},
    "unsupported_system": {
        "fr": "Système non pris en charge : {system}",
        "en": "Unsupported system: {system}",
    },
    "system_audio": {
        "fr": "Audio système (toutes les sorties)",
        "en": "System audio (every output)",
    },
    "macos_permission": {
        "fr": "Autorisez « Enregistrement de l'écran et de l'audio système » pour votre terminal"
        " dans Réglages Système > Confidentialité et sécurité, puis relancez Smart Meeting.",
        "en": 'Allow "Screen & System Audio Recording" for your terminal in System Settings >'
        " Privacy & Security, then restart Smart Meeting.",
    },
    "macos_no_answer": {
        "fr": "ScreenCaptureKit ne répond pas.",
        "en": "ScreenCaptureKit does not answer.",
    },
    "system_audio_failed": {
        "fr": "Capture de l'audio système impossible",
        "en": "Cannot capture the system audio",
    },
    # Files
    "decoding_failed": {"fr": "Décodage impossible : {error}", "en": "Cannot decode: {error}"},
    "no_audio_track": {
        "fr": "Aucune piste audio dans ce fichier",
        "en": "No audio track in this file",
    },
    "no_readable_audio": {
        "fr": "Aucune piste audio lisible dans ce fichier",
        "en": "No readable audio track in this file",
    },
    # Local AI
    "ai_unreachable": {
        "fr": "L'IA locale ne répond pas : {error}",
        "en": "The local AI does not answer: {error}",
    },
    "empty_transcript": {
        "fr": "Transcription vide : rien à analyser",
        "en": "Empty transcript: nothing to analyze",
    },
    "nothing_transcribed": {
        "fr": "Rien n'a encore été transcrit : posez la question un peu plus tard.",
        "en": "Nothing has been transcribed yet: ask a little later.",
    },
    "analysis_failed": {"fr": "Analyse impossible : {error}", "en": "Analysis failed: {error}"},
    "analysis_not_possible": {
        "fr": "Analyse impossible dans l'état « {status} »",
        "en": 'Cannot analyze in the "{status}" state',
    },
    # First-run installs
    "installing_ollama": {"fr": "Installation d'Ollama", "en": "Installing Ollama"},
    "extracting_ollama": {
        "fr": "Installation d'Ollama (extraction)",
        "en": "Installing Ollama (extracting)",
    },
    "downloading_model": {
        "fr": "Téléchargement du modèle IA {name}",
        "en": "Downloading the {name} AI model",
    },
    "ollama_not_starting": {
        "fr": "Ollama ne démarre pas (voir {log})",
        "en": "Ollama does not start (see {log})",
    },
    "model_missing_after_download": {
        "fr": "Modèle {name} introuvable après téléchargement",
        "en": "Model {name} not found after download",
    },
    "bad_checksum": {
        "fr": "Somme de contrôle invalide pour {name}",
        "en": "Invalid checksum for {name}",
    },
    "ollama_binary_missing": {
        "fr": "{name} introuvable dans l'archive Ollama",
        "en": "{name} not found in the Ollama archive",
    },
    "unsupported_architecture": {
        "fr": "Architecture non prise en charge : {machine}",
        "en": "Unsupported architecture: {machine}",
    },
    # Launcher (terminal and desktop notifications)
    "pipewire_missing": {
        "fr": "PipeWire est requis (Ubuntu 22.10+). Installez-le : sudo apt install pipewire-bin",
        "en": "PipeWire is required (Ubuntu 22.10+). Install it: sudo apt install pipewire-bin",
    },
    "macos_too_old": {
        "fr": "macOS 13 (Ventura) ou plus récent est requis pour capturer l'audio système.",
        "en": "macOS 13 (Ventura) or later is required to capture the system audio.",
    },
    "bun_unavailable": {
        "fr": "Bun n'est pas disponible pour {system}",
        "en": "Bun is not available for {system}",
    },
    "bun_download_failed": {
        "fr": "Téléchargement de Bun impossible ({error}). Derrière un proxy, vérifiez"
        " HTTPS_PROXY ; sinon installez Bun à la main : https://bun.sh",
        "en": "Cannot download Bun ({error}). Behind a proxy, check HTTPS_PROXY; otherwise install"
        " Bun by hand: https://bun.sh",
    },
    "bun_not_starting": {
        "fr": "Bun a été installé dans {path} mais ne démarre pas sur cette machine.",
        "en": "Bun was installed in {path} but does not start on this machine.",
    },
    "build_failed": {
        "fr": "Construction de l'interface impossible (voir les messages ci-dessus).",
        "en": "Cannot build the interface (see the messages above).",
    },
    "port_unresponsive": {
        "fr": "Le port {port} est occupé mais rien n'y répond. Fermez l'application qui l'utilise,"
        " ou choisissez un autre port avec --port ou SM_PORT.",
        "en": "Port {port} is taken but nothing answers on it. Close the application using it, or"
        " choose another port with --port or SM_PORT.",
    },
    "starting_title": {"fr": "Smart Meeting démarre…", "en": "Smart Meeting is starting…"},
    "starting_detail": {
        "fr": "L'application s'ouvrira ici dans quelques secondes.",
        "en": "The app will open here in a few seconds.",
    },
    "starting_slow": {
        "fr": "C'est plus long que d'habitude : l'interface est peut-être en cours de mise à jour."
        " Si rien ne change d'ici une minute, relancez Smart Meeting.",
        "en": "This takes longer than usual: the interface may be updating. If nothing changes"
        " within a minute, start Smart Meeting again.",
    },
    "port_taken": {
        "fr": "Le port {port} est utilisé par une autre application. Choisissez-en un autre avec"
        " --port ou SM_PORT.",
        "en": "Port {port} is used by another application. Choose another one with --port or"
        " SM_PORT.",
    },
}


def tr(key: str, **params: object) -> str:
    """The message in the interface language (French when it is not translated)."""
    texts = MESSAGES[key]
    language = get_settings().ui_language
    return texts.get(language, texts["fr"]).format(**params)
