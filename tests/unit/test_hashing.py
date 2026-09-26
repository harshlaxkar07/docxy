import io
from app.utils.hashing import compute_sha256


def test_compute_sha256_bytes():
    data = b"Hello Antigravity PDF Pipeline"
    h1 = compute_sha256(data)
    assert len(h1) == 64
    assert h1 == compute_sha256(data)


def test_compute_sha256_stream():
    stream = io.BytesIO(b"Hello Stream Content")
    h1 = compute_sha256(stream)
    assert len(h1) == 64
    # Ensure stream position was reset
    assert stream.tell() == 0


def test_compute_sha256_file(tmp_path):
    f = tmp_path / "sample.txt"
    f.write_text("Testing file hashing")
    h1 = compute_sha256(f)
    assert len(h1) == 64
