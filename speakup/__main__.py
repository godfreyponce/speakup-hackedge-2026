"""python3 -m speakup: serve the screening session (#5)."""

import argparse
import sys
import threading
from pathlib import Path

from speakup import arti, bank, llm, replay
from speakup.demo_model import check_script, demo_listen
from speakup.fake_model import fake_listen
from speakup.recorder import ArecordRecorder, FakeRecorder, VoiceRecorder
from speakup.server import make_server
from speakup.words import load_words


def main() -> None:
    parser = argparse.ArgumentParser(prog="python3 -m speakup", description="Serve the Speak Up screening session.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--arecord", action="store_true", help="record on this machine's mic with arecord (the board)")
    parser.add_argument("--device", help="ALSA capture device for arecord -D, such as plughw:1,0")
    parser.add_argument("--seconds", type=int, default=3,
                        help="with --fixed: clip length; without --arecord: how long the fake mic waits")
    parser.add_argument("--fixed", action="store_true",
                        help="with --arecord: record a fixed --seconds clip instead of listening for the voice")
    parser.add_argument("--rate", type=int, default=48000,
                        help="mic sample rate in Hz (48000; Arti still hears a 16 kHz copy). Use 16000 for the old clips")
    parser.add_argument("--start-peak", type=int, default=300,
                        help="voice-activated recording: loudest sample (of 32767) that counts as a voice")
    parser.add_argument("--silence", type=float, default=2.0,
                        help="voice-activated recording: seconds of quiet that end it (2; the SLP can also press Stop)")
    parser.add_argument("--demo", action="store_true", help="answer from the fixed script in speakup/demo_model.py")
    parser.add_argument("--sample-clip", metavar="WAV", type=Path,
                        help="without --arecord: use this WAV as every recording (to try the sound analysis on a laptop)")
    parser.add_argument("--arti", metavar="PATH", help="run the Arti ONNX model; needs --arecord or --replay")
    parser.add_argument("--replay", metavar="FOLDER", type=Path,
                        help="instead of the mic, each recording is the next saved clip for the word on screen, "
                             "listed in FOLDER/manifest.csv (header file,word); needs --arti")
    parser.add_argument("--llm-model", metavar="PATH",
                        help="GGUF model for the end screen's note and the practice lines, run with llama.cpp; "
                             "without it the end screen shows the tally and the fixed family notes, and practice uses the fixed lines")
    parser.add_argument("--llm-bin", default="llama-completion", help="llama.cpp completion binary")
    args = parser.parse_args()
    if args.replay and not args.arti:
        parser.error("--replay needs --arti: replay mode shows Arti's real answers only")
    if args.replay and (args.arecord or args.sample_clip):
        parser.error("--replay can't run with --arecord or --sample-clip: the clips come from the folder")
    if args.arti and not (args.arecord or args.replay):
        parser.error("--arti needs --arecord or --replay: the fake recorder writes no clip for the model to read")
    if args.arti and args.demo:
        parser.error("--arti and --demo can't run together")
    if not 0.5 <= args.silence <= 10:
        parser.error("--silence: give a number of seconds from 0.5 to 10")
    if args.rate < arti.RATE:
        parser.error(f"--rate: give {arti.RATE} Hz or more; Arti and the sound analysis need at least {arti.RATE} Hz")

    words = load_words()
    listen = lambda word, path: fake_listen(word)
    if args.demo:
        try:
            check_script(words)
        except ValueError as e:
            sys.exit(f"--demo: {e}")
        listen = demo_listen
    clips = None
    if args.replay:
        try:
            clips = replay.load(args.replay, [w.word for w in words])
        except replay.ReplayError as e:
            sys.exit(f"--replay: {e}")
    if args.arti:
        listen = arti.load(Path(args.arti))

    generate = None
    if args.llm_model:
        try:
            generate = llm.load(args.llm_bin, Path(args.llm_model))
        except llm.LlmError as e:
            print(f"--llm-model: {e}. The end screen shows the tally and the fixed family notes.", file=sys.stderr, flush=True)

    if clips is not None:
        recorder = replay.ReplayRecorder(args.replay, clips)
    elif args.arecord and args.fixed:
        recorder = ArecordRecorder(args.seconds, args.device, rate=args.rate)
    elif args.arecord:
        recorder = VoiceRecorder(args.device, gate={"start_peak": args.start_peak, "trailing": args.silence}, rate=args.rate)
    else:
        recorder = FakeRecorder(args.seconds, args.sample_clip)
    server = make_server(
        args.host, args.port,
        words=words,
        listen=listen,
        recorder=recorder,
        recordings_dir=Path("recordings"),
        db_path=Path("data/speakup.db"),
        generate=generate,
        workers=3 if args.arecord or args.replay else 0,  # the board: three cores for the analysis, one for the app and Arti
    )
    if generate is not None and server.bank is not None:
        # Start-up never waits on llama.cpp: practice uses the fixed lines until Qwen's bank is in (#21).
        def fill_bank() -> None:
            server.bank = bank.fill(generate, words, server.bank)

        threading.Thread(target=fill_bank, daemon=True).start()
    print(f"Speak Up on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
