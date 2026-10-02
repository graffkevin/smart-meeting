from smart_meeting.audio.devices import parse_pw_dump


def node(name, description, media_class):
    return {
        "type": "PipeWire:Interface:Node",
        "info": {
            "props": {
                "node.name": name,
                "node.description": description,
                "media.class": media_class,
            }
        },
    }


def test_parse_pw_dump():
    dump = [
        node("alsa_output.headset", "USB Audio Casque", "Audio/Sink"),
        node("alsa_output.builtin", "Built-in Audio", "Audio/Sink"),
        node("alsa_input.headset", "USB Audio Casque", "Audio/Source"),
        node("v4l2_input.webcam", "Webcam", "Video/Source"),
        {
            "type": "PipeWire:Interface:Node",
            "info": {"props": {"media.class": "Stream/Output/Audio"}},
        },
        {
            "type": "PipeWire:Interface:Metadata",
            "props": {"metadata.name": "default"},
            "metadata": [
                {"key": "default.audio.sink", "value": {"name": "alsa_output.headset"}},
                {"key": "default.audio.source", "value": {"name": "alsa_input.headset"}},
            ],
        },
    ]
    devices = parse_pw_dump(dump)
    assert [d.name for d in devices.sinks] == ["alsa_output.headset", "alsa_output.builtin"]
    assert devices.sinks[0].is_default and not devices.sinks[1].is_default
    assert [d.name for d in devices.sources] == ["alsa_input.headset"]


def stream(node_id, name, media_class, state="running", app="Firefox", pid=None):
    return {
        "id": node_id,
        "type": "PipeWire:Interface:Node",
        "info": {
            "state": state,
            "props": {"node.name": name, "media.class": media_class, "application.name": app},
        },
    }


def device(node_id, name, media_class):
    obj = node(name, name, media_class)
    obj["id"] = node_id
    return obj


def link(out_id, in_id):
    return {
        "type": "PipeWire:Interface:Link",
        "info": {"output-node-id": out_id, "input-node-id": in_id},
    }


DEFAULTS = {
    "type": "PipeWire:Interface:Metadata",
    "props": {"metadata.name": "default"},
    "metadata": [
        {"key": "default.audio.sink", "value": {"name": "builtin-out"}},
        {"key": "default.audio.source", "value": {"name": "builtin-mic"}},
    ],
}


def test_resolve_in_use_follows_application_streams():
    from smart_meeting.audio.devices import resolve_in_use

    dump = [
        DEFAULTS,
        device(1, "builtin-out", "Audio/Sink"),
        device(2, "headset-out", "Audio/Sink"),
        device(3, "builtin-mic", "Audio/Source"),
        device(4, "headset-mic", "Audio/Source"),
        stream(10, "firefox-out", "Stream/Output/Audio"),
        stream(11, "firefox-in", "Stream/Input/Audio"),
        stream(12, "notifications", "Stream/Output/Audio", state="idle", app="libcanberra"),
        stream(13, "smart-meeting-remote", "Stream/Input/Audio"),
        link(12, 1),
        link(10, 2),
        link(4, 11),
        link(1, 13),  # our own capture must be ignored
    ]
    assert resolve_in_use(dump) == ("headset-mic", "headset-out")


def test_resolve_in_use_falls_back_to_defaults():
    from smart_meeting.audio.devices import resolve_in_use

    dump = [
        DEFAULTS,
        device(1, "builtin-out", "Audio/Sink"),
        device(3, "builtin-mic", "Audio/Source"),
    ]
    assert resolve_in_use(dump) == ("builtin-mic", "builtin-out")


def test_resolve_in_use_prefers_the_call_output_and_can_skip_defaults():
    from smart_meeting.audio.devices import resolve_in_use

    dump = [
        DEFAULTS,
        device(1, "builtin-out", "Audio/Sink"),
        device(2, "headset-out", "Audio/Sink"),
        device(4, "headset-mic", "Audio/Source"),
        stream(10, "music", "Stream/Output/Audio", app="Rhythmbox", pid=1),
        stream(11, "call-out", "Stream/Output/Audio", state="idle", app="Teams", pid=2),
        stream(12, "call-in", "Stream/Input/Audio", app="Teams", pid=2),
        link(10, 1),
        link(11, 2),
        link(4, 12),
    ]
    assert resolve_in_use(dump) == ("headset-mic", "headset-out")
    no_apps = [DEFAULTS, device(1, "builtin-out", "Audio/Sink")]
    assert resolve_in_use(no_apps, fallback_to_defaults=False) == (None, None)
