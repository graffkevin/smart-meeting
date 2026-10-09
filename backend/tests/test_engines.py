from types import SimpleNamespace

import numpy as np
import pytest

from smart_meeting.config import Settings
from smart_meeting.hardware import Hardware
from smart_meeting.transcription import engines
from smart_meeting.transcription.base import SAMPLE_RATE, Transcriber, blocks
from smart_meeting.transcription.openvino import pick_device, pieces

APPLE = Hardware("Apple M5", "apple", 4, False, (("apple", "Apple M5"),))
NVIDIA = Hardware("Intel Core i7", "intel", 8, True, (("nvidia", "RTX 4070"),))
INTEL = Hardware("Intel Core Ultra 7", "intel", 6, False, (("intel", "Arc Graphics"),))
AMD = Hardware("AMD Ryzen 7", "amd", 8, False, (("amd", "Radeon 780M"),))


@pytest.fixture
def everything_installed(monkeypatch):
    monkeypatch.setattr(engines, "_installed", lambda engine: True)


@pytest.mark.parametrize(
    ("hardware", "order"),
    [
        (APPLE, ["mlx", "faster-whisper"]),
        (NVIDIA, ["faster-whisper"]),  # CUDA, before the Intel CPU next to it
        (INTEL, ["faster-whisper"]),  # OpenVINO only when chosen
        (AMD, ["faster-whisper"]),
    ],
)
def test_engine_follows_the_hardware(everything_installed, hardware, order):
    assert engines.engine_order(Settings(), hardware) == order


def test_engine_not_installed_is_skipped(monkeypatch):
    monkeypatch.setattr(engines, "_installed", lambda engine: engine == "faster-whisper")
    assert engines.engine_order(Settings(), INTEL) == ["faster-whisper"]


def test_chosen_engine_wins_over_the_hardware(everything_installed):
    settings = Settings(whisper_engine="openvino")
    assert engines.engine_order(settings, APPLE) == ["openvino", "faster-whisper"]
    with pytest.raises(ValueError):
        engines.engine_order(Settings(whisper_engine="coreml"), APPLE)


class FakeEngine(Transcriber):
    def __init__(self, settings, name, fails):
        super().__init__(settings)
        self.name, self.fails = name, fails

    def load(self):
        if self.fails:
            raise RuntimeError("no GPU driver")
        self.model_name, self.device = "small", "cpu"

    def transcribe_partial(self, audio, language, previous_text=""):
        return self.name


def auto(failing: set[str], hardware=APPLE) -> engines.AutoTranscriber:
    return engines.AutoTranscriber(
        Settings(),
        hardware=lambda: hardware,
        factory=lambda name, settings: FakeEngine(settings, name, name in failing),
    )


def test_engine_failing_to_load_gives_way_to_the_next(everything_installed):
    transcriber = auto({"mlx"})
    transcriber.load()
    assert transcriber.engine == "faster-whisper"
    assert transcriber.transcribe_partial(None, "fr") == "faster-whisper"
    assert transcriber.device == "faster-whisper cpu"


def test_last_engine_failing_is_an_error(everything_installed):
    with pytest.raises(RuntimeError, match="no GPU driver"):
        auto({"mlx", "faster-whisper"}).load()


def test_calls_before_loading_fail_clearly():
    with pytest.raises(AttributeError):
        auto(set()).transcribe(None, None)


def test_long_file_cut_in_blocks_at_a_silence():
    rng = np.random.default_rng(0)
    audio = rng.uniform(-0.5, 0.5, 700 * SAMPLE_RATE).astype(np.float32)
    quiet = 295 * SAMPLE_RATE
    audio[quiet : quiet + SAMPLE_RATE // 5] = 0  # 200 ms of silence before the 300 s limit
    starts = list(blocks(audio))
    assert starts[0] == 0
    assert quiet <= starts[1] < quiet + SAMPLE_RATE // 5
    assert len(starts) == 3
    assert list(blocks(np.zeros(10 * SAMPLE_RATE, np.float32))) == [0]


def test_openvino_runs_on_the_cpu_unless_the_gpu_is_asked():
    def discrete(device):
        return device == "GPU.1"

    assert pick_device(["CPU", "GPU.0", "GPU.1"], discrete, "gpu") == "GPU.1"
    assert pick_device(["CPU", "GPU"], discrete, "gpu") == "GPU"
    assert pick_device(["CPU", "NPU"], discrete, "gpu") == "CPU"
    assert pick_device(["CPU", "GPU"], discrete, "npu") == "NPU"
    # By default the CPU: an integrated GPU can be slower than real time
    assert pick_device(["CPU", "GPU.0", "GPU.1"], discrete, "auto") == "CPU"


def test_openvino_sentences_get_their_words_and_the_block_offset():
    def word(start, end, text):
        return SimpleNamespace(start_ts=start, end_ts=end, word=text)

    def chunk(start, end, text):
        return SimpleNamespace(start_ts=start, end_ts=end, text=text)

    result = SimpleNamespace(
        chunks=[
            chunk(0.0, 1.0, " Bonjour."),
            chunk(1.0, 2.0, " Abonnez-vous !"),
            chunk(2.0, 3.0, " Merci."),
        ],
        words=[
            word(0.0, 0.8, " Bonjour."),
            word(1.1, 1.9, " Abonnez-vous"),
            word(2.1, 2.6, " Merci."),
        ],
    )
    found = pieces(result, offset=300.0)
    assert [p.text for p in found] == ["Bonjour.", "Merci."]  # hallucination dropped
    assert found[1].start_s == 302.0
    assert found[1].words == [(302.1, 302.6, " Merci.")]


class SizedEngine(FakeEngine):
    """Loads the model of its settings ("auto": large-v3-turbo, like on a GPU)."""

    def load(self):
        model = self.settings.whisper_model
        self.model_name = "large-v3-turbo" if model == "auto" else model
        self.device = self.settings.whisper_device


def test_falling_behind_lightens_the_model_then_the_engine(everything_installed):
    transcriber = engines.AutoTranscriber(
        Settings(),
        hardware=lambda: APPLE,
        factory=lambda name, settings: SizedEngine(settings, name, False),
    )
    transcriber.load()
    assert (transcriber.engine, transcriber.model_name) == ("mlx", "large-v3-turbo")
    assert transcriber.lighten() == "small (mlx auto)"  # same engine, small model
    assert transcriber.lighten() == "small (faster-whisper cpu)"  # then the CPU
    assert transcriber.settings.whisper_partial_model == "none"
    assert transcriber.lighten() is None  # nothing lighter


def test_unloading_gives_back_the_best_model_on_the_next_load(everything_installed):
    transcriber = engines.AutoTranscriber(
        Settings(whisper_device="cuda"),
        hardware=lambda: NVIDIA,
        factory=lambda name, settings: SizedEngine(settings, name, False),
    )
    transcriber.load()
    assert transcriber.on_gpu
    transcriber.lighten()
    assert transcriber.model_name == "small"
    transcriber.unload()
    assert transcriber.engine is None and not transcriber.on_gpu
    transcriber.load()
    assert transcriber.model_name == "large-v3-turbo"
