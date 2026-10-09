# Samples for the benchmarks

- `reunion-test.mp4`: a made-up 67-second French meeting, three synthetic macOS voices (`say`), generated from
  `reunion-test-script.txt` ("voice|text" per line). No real person's voice, free of rights.
- `reference.txt`: its text with numbers as digits, as Whisper writes them, for `bench_transcription.py --reference`.
- `reunion-longue.txt`: a made-up 12-minute meeting transcript ("mm:ss|speaker|text"), with known decisions and
  actions, for `bench_analysis.py`.
