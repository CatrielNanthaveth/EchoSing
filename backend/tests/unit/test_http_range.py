import pytest

from app.api.http_range import ByteRange, RangeNotSatisfiableError, parse_range

SIZE = 1000


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("bytes=0-499", (0, 500)),
        ("bytes=500-999", (500, 1000)),
        ("bytes=0-0", (0, 1)),  # first byte
        ("bytes=999-999", (999, 1000)),  # last byte
        ("bytes=500-", (500, 1000)),  # open-ended
        ("bytes=900-5000", (900, 1000)),  # end clamped
        ("bytes=-100", (900, 1000)),  # suffix
        ("bytes=-5000", (0, 1000)),  # suffix larger than the resource
        ("bytes= 10-19 ", (10, 20)),  # surrounding spaces
    ],
)
def test_satisfiable_ranges(header: str, expected: tuple[int, int]) -> None:
    result = parse_range(header, SIZE)

    assert result == ByteRange(start=expected[0], stop=expected[1])


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "items=0-10",  # not bytes
        "bytes=abc",  # malformed
        "bytes=-",  # empty range
        "bytes=10-5",  # end before start
        "bytes=0-10,20-30",  # several ranges
        "bytes=1.5-3",
    ],
)
def test_ignored_headers_mean_the_whole_resource(header: str | None) -> None:
    assert parse_range(header, SIZE) is None


@pytest.mark.parametrize(
    ("header", "size"),
    [
        ("bytes=1000-", SIZE),  # starts at the end
        ("bytes=5000-6000", SIZE),
        ("bytes=-0", SIZE),  # zero bytes
        ("bytes=0-10", 0),  # empty resource
        ("bytes=-10", 0),
    ],
)
def test_unsatisfiable_ranges(header: str, size: int) -> None:
    with pytest.raises(RangeNotSatisfiableError):
        parse_range(header, size)


def test_content_range_header() -> None:
    assert ByteRange(start=0, stop=500).content_range(1234) == "bytes 0-499/1234"
