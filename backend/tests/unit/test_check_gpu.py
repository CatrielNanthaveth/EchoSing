from scripts.check_gpu import REQUIRED_ARCH, GpuReport, find_problems


def healthy_report() -> GpuReport:
    return GpuReport(
        torch_version="2.11.0+cu128",
        cuda_version="12.8",
        cuda_available=True,
        device_name="NVIDIA GeForce RTX 5060",
        compute_capability=(12, 0),
        compiled_archs=["sm_90", REQUIRED_ARCH],
        vram_total_gib=7.96,
        vram_free_gib=7.0,
        matmul_ok=True,
        ffmpeg_path="C:/ffmpeg/bin/ffmpeg.exe",
    )


def test_healthy_environment_has_no_problems() -> None:
    assert find_problems(healthy_report()) == []


def test_missing_torch_is_reported() -> None:
    report = healthy_report().model_copy(update={"torch_version": None})

    assert find_problems(report) == [
        "PyTorch is not installed (run `uv sync --group ml`)."
    ]


def test_cpu_only_build_is_reported() -> None:
    report = healthy_report().model_copy(update={"cuda_version": None})

    assert find_problems(report) == [
        "PyTorch is a CPU-only build; install the cu128 wheels."
    ]


def test_unavailable_cuda_is_reported() -> None:
    report = healthy_report().model_copy(update={"cuda_available": False})

    assert find_problems(report) == ["CUDA is not available (check the NVIDIA driver)."]


def test_missing_arch_and_failed_matmul_are_reported() -> None:
    report = healthy_report().model_copy(
        update={"compiled_archs": ["sm_90"], "matmul_ok": False}
    )

    assert find_problems(report) == [
        f"PyTorch was not compiled for {REQUIRED_ARCH}.",
        "A test matrix multiplication on the GPU failed.",
    ]


def test_missing_ffmpeg_and_packages_are_reported() -> None:
    report = healthy_report().model_copy(
        update={"ffmpeg_path": None, "missing_packages": ["demucs", "whisper"]}
    )

    assert find_problems(report) == [
        "ffmpeg was not found on PATH.",
        "Package 'demucs' could not be imported.",
        "Package 'whisper' could not be imported.",
    ]
