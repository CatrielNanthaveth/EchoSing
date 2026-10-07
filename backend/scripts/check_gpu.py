"""Smoke test for the ML stack: CUDA, GPU architecture, FFmpeg and ML packages.

Usage (from ``backend/``, after ``uv sync --group ml``)::

    uv run python -m scripts.check_gpu

Exits with code 0 when the machine is ready to run the ingestion pipeline and 1
otherwise. No model weights are downloaded.
"""

import importlib
import shutil
import sys

from pydantic import BaseModel

REQUIRED_ARCH = "sm_120"
ML_PACKAGES = ("demucs", "whisper", "torchcrepe")
BYTES_PER_GIB = 1024**3


class GpuReport(BaseModel):
    """Snapshot of the ML environment.

    Attributes:
        torch_version: Installed PyTorch version, or None if not importable.
        cuda_version: CUDA version PyTorch was built with, or None (CPU build).
        cuda_available: Whether PyTorch can use a CUDA device.
        device_name: Name of the first CUDA device.
        compute_capability: (major, minor) capability of the first CUDA device.
        compiled_archs: GPU architectures PyTorch was compiled for.
        vram_total_gib: Total memory of the first CUDA device, in GiB.
        vram_free_gib: Free memory of the first CUDA device, in GiB.
        matmul_ok: Whether a small matrix multiplication succeeded on the GPU.
        ffmpeg_path: Location of the ``ffmpeg`` executable, or None.
        missing_packages: ML packages that failed to import.
    """

    torch_version: str | None = None
    cuda_version: str | None = None
    cuda_available: bool = False
    device_name: str | None = None
    compute_capability: tuple[int, int] | None = None
    compiled_archs: list[str] = []
    vram_total_gib: float | None = None
    vram_free_gib: float | None = None
    matmul_ok: bool = False
    ffmpeg_path: str | None = None
    missing_packages: list[str] = []


def find_problems(report: GpuReport) -> list[str]:
    """Evaluate a report and list everything that prevents running the pipeline.

    Args:
        report: Environment snapshot to evaluate.

    Returns:
        Human-readable problems; empty when the environment is ready.
    """
    problems: list[str] = []
    if report.torch_version is None:
        problems.append("PyTorch is not installed (run `uv sync --group ml`).")
    elif report.cuda_version is None:
        problems.append("PyTorch is a CPU-only build; install the cu128 wheels.")
    elif not report.cuda_available:
        problems.append("CUDA is not available (check the NVIDIA driver).")
    else:
        if REQUIRED_ARCH not in report.compiled_archs:
            problems.append(f"PyTorch was not compiled for {REQUIRED_ARCH}.")
        if not report.matmul_ok:
            problems.append("A test matrix multiplication on the GPU failed.")
    if report.ffmpeg_path is None:
        problems.append("ffmpeg was not found on PATH.")
    problems.extend(
        f"Package {name!r} could not be imported." for name in report.missing_packages
    )
    return problems


def collect_report() -> GpuReport:
    """Probe the current machine.

    Side effects:
        Imports the ML packages and allocates a small tensor on the GPU.

    Returns:
        The collected environment snapshot.
    """
    report = GpuReport(
        ffmpeg_path=shutil.which("ffmpeg"),
        missing_packages=[name for name in ML_PACKAGES if not _can_import(name)],
    )
    try:
        import torch
    except ImportError:
        return report

    report.torch_version = torch.__version__
    report.cuda_version = torch.version.cuda
    report.cuda_available = torch.cuda.is_available()
    if not report.cuda_available:
        return report

    report.device_name = torch.cuda.get_device_name(0)
    report.compute_capability = torch.cuda.get_device_capability(0)
    report.compiled_archs = torch.cuda.get_arch_list()
    free_bytes, total_bytes = torch.cuda.mem_get_info(0)
    report.vram_free_gib = round(free_bytes / BYTES_PER_GIB, 2)
    report.vram_total_gib = round(total_bytes / BYTES_PER_GIB, 2)
    try:
        matrix = torch.rand((512, 512), device="cuda")
        product = matrix @ matrix
        torch.cuda.synchronize()
        report.matmul_ok = bool(torch.isfinite(product).all().item())
        del matrix, product
        torch.cuda.empty_cache()
    except RuntimeError:
        report.matmul_ok = False
    return report


def _can_import(module_name: str) -> bool:
    """Return whether ``module_name`` can be imported."""
    try:
        importlib.import_module(module_name)
    except ImportError:
        return False
    return True


def main() -> int:
    """Run the smoke test and print the results.

    Returns:
        Process exit code: 0 if the environment is ready, 1 otherwise.
    """
    report = collect_report()
    print(report.model_dump_json(indent=2))
    problems = find_problems(report)
    if problems:
        print("\nPROBLEMS:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nOK: the ML environment is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
