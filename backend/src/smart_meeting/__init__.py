import os

# numpy's OpenBLAS: one thread per call. Matrix products from two threads at once (Whisper, voice
# prints) deadlocked its own thread pool and froze the transcription of a meeting. Set before
# numpy is imported, which this package always is first.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
