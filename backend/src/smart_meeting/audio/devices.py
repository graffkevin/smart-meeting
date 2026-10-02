"""PipeWire device discovery through `pw-dump` (no PulseAudio tools required)."""

import asyncio
import json
from typing import Any

from smart_meeting.models import AudioDevice, AudioDevices

OWN_NODE_PREFIX = "smart-meeting-"


async def pw_dump() -> list[dict[str, Any]]:
    proc = await asyncio.create_subprocess_exec(
        "pw-dump", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"pw-dump failed: {stderr.decode().strip()}")
    return json.loads(stdout)


async def list_devices() -> AudioDevices:
    objects = await pw_dump()
    in_use_source, in_use_sink = resolve_in_use(objects)
    return parse_pw_dump(objects).model_copy(
        update={"in_use_source": in_use_source, "in_use_sink": in_use_sink}
    )


def resolve_in_use(
    objects: list[dict[str, Any]], fallback_to_defaults: bool = True
) -> tuple[str | None, str | None]:
    """(microphone, output) currently used by applications, e.g. Teams or Firefox in a call.

    Follows PipeWire links: source -> application capture stream, application playback
    stream -> sink. Works for any application, not only browsers. Preference order for the
    output: played by the application that also uses the microphone (the call), then running
    streams. Without any application stream, the system defaults are returned if allowed.
    """
    nodes = {o["id"]: o for o in objects if o.get("type") == "PipeWire:Interface:Node"}
    devices = parse_pw_dump(objects)
    sink_names = {d.name for d in devices.sinks}
    source_names = {d.name for d in devices.sources}

    def props(node_id: int) -> dict[str, Any]:
        return nodes.get(node_id, {}).get("info", {}).get("props", {})

    def is_app_stream(node_id: int, media_class: str) -> bool:
        p = props(node_id)
        return (
            p.get("media.class") == media_class
            and not str(p.get("node.name", "")).startswith(OWN_NODE_PREFIX)
            and p.get("application.name") != "speech-dispatcher-dummy"
        )

    def running(node_id: int) -> bool:
        return nodes.get(node_id, {}).get("info", {}).get("state") == "running"

    def app(node_id: int) -> object:
        p = props(node_id)
        # Name rather than pid: browsers may play and record from different processes.
        return p.get("application.name") or p.get("application.process.binary")

    playing: list[tuple[int, str]] = []  # (stream id, sink)
    recording: list[tuple[int, str]] = []  # (stream id, source)
    for obj in objects:
        if obj.get("type") != "PipeWire:Interface:Link":
            continue
        out_id = obj["info"]["output-node-id"]
        in_id = obj["info"]["input-node-id"]
        out_name, in_name = props(out_id).get("node.name"), props(in_id).get("node.name")
        if in_name in sink_names and is_app_stream(out_id, "Stream/Output/Audio"):
            playing.append((out_id, in_name))
        if out_name in source_names and is_app_stream(in_id, "Stream/Input/Audio"):
            recording.append((in_id, out_name))

    mic_apps = {app(stream_id) for stream_id, _ in recording} - {None}
    mic = max(recording, key=lambda c: running(c[0]), default=None)
    sink = max(playing, key=lambda c: (app(c[0]) in mic_apps, running(c[0])), default=None)

    def default(candidates: list[AudioDevice]) -> str | None:
        if not fallback_to_defaults:
            return None
        return next((d.name for d in candidates if d.is_default), None)

    return (
        mic[1] if mic else default(devices.sources),
        sink[1] if sink else default(devices.sinks),
    )


def parse_pw_dump(objects: list[dict[str, Any]]) -> AudioDevices:
    defaults: dict[str, str] = {}
    nodes: list[dict[str, Any]] = []
    for obj in objects:
        if obj.get("type") == "PipeWire:Interface:Node":
            nodes.append(obj.get("info", {}).get("props", {}))
        elif (
            obj.get("type") == "PipeWire:Interface:Metadata"
            and obj.get("props", {}).get("metadata.name") == "default"
        ):
            for entry in obj.get("metadata") or []:
                value = entry.get("value")
                if isinstance(value, dict) and "name" in value:
                    defaults[entry["key"]] = value["name"]

    def devices(media_classes: set[str], default_key: str) -> list[AudioDevice]:
        default_name = defaults.get(default_key)
        return sorted(
            (
                AudioDevice(
                    name=props["node.name"],
                    description=props.get("node.description") or props["node.name"],
                    is_default=props["node.name"] == default_name,
                )
                for props in nodes
                if props.get("media.class") in media_classes and "node.name" in props
            ),
            key=lambda d: (not d.is_default, d.description),
        )

    return AudioDevices(
        # Virtual sources include filtered mics (noise suppression, EasyEffects...).
        sources=devices({"Audio/Source", "Audio/Source/Virtual"}, "default.audio.source"),
        sinks=devices({"Audio/Sink"}, "default.audio.sink"),
    )
