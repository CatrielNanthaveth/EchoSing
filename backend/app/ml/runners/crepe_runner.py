"""Subprocess entry point running torchcrepe (black box) on a WAV file.

Runs in its own process so that PyTorch and its GPU memory never live in the
pipeline worker. Writes JSON: ``{"hop_ms", "frequency_hz": [...],
"confidence": [...]}`` with one value per frame; frame ``i`` is centered at
``i * hop_ms``.

Usage::

    python -m app.ml.runners.crepe_runner input.wav output.json [options]
"""

import argparse
import json
import sys
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(prog="python -m app.ml.runners.crepe_runner")
    parser.add_argument("audio", help="Mono WAV file")
    parser.add_argument("output", help="JSON file to write")
    parser.add_argument("--hop-ms", type=int, default=10)
    parser.add_argument("--model", default="full", choices=["full", "tiny"])
    parser.add_argument(
        "--decoder", default="viterbi", choices=["viterbi", "weighted_argmax", "argmax"]
    )
    parser.add_argument("--fmin", type=float, default=65.0)
    parser.add_argument("--fmax", type=float, default=1100.0)
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument("--device", default="cuda")
    parser.add_argument(
        "--silence-db",
        type=float,
        default=-60.0,
        help="Frames quieter than this get zero confidence",
    )
    parser.add_argument(
        "--median-frames",
        type=int,
        default=3,
        help="Median filter width applied to the confidence",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - GPU
    """Run torchcrepe and write its pitch and confidence as JSON.

    Args:
        argv: Arguments without the program name; defaults to ``sys.argv``.

    Returns:
        Process exit code.
    """
    args = build_parser().parse_args(argv)

    # Heavy imports stay inside the subprocess.
    import soundfile
    import torch
    import torchcrepe

    samples, sample_rate = soundfile.read(args.audio, dtype="float32")
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    audio = torch.from_numpy(samples).unsqueeze(0)
    hop_length = round(sample_rate * args.hop_ms / 1000)
    device = args.device if args.device == "cpu" else "cuda:0"

    with torch.inference_mode():
        pitch, periodicity = torchcrepe.predict(
            audio,
            sample_rate,
            hop_length,
            args.fmin,
            args.fmax,
            args.model,
            decoder=getattr(torchcrepe.decode, args.decoder),
            return_periodicity=True,
            batch_size=args.batch_size,
            device=device,
            pad=True,
        )
        periodicity = torchcrepe.filter.median(periodicity, args.median_frames)
        periodicity = torchcrepe.threshold.Silence(args.silence_db)(
            periodicity, audio, sample_rate, hop_length
        )

    result = {
        "hop_ms": args.hop_ms,
        "frequency_hz": pitch.squeeze(0).cpu().tolist(),
        "confidence": periodicity.squeeze(0).cpu().tolist(),
    }
    with open(args.output, "w", encoding="utf-8") as file:
        json.dump(result, file)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
