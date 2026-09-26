"""S3 storage mode, exercised against a mocked S3 via moto.

The suite otherwise forces AWS_ENABLED=false, leaving the upload, download and
presigned-URL paths of S3Service unverified.
"""

import pytest

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")

from moto import mock_aws  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.s3_service import S3Service  # noqa: E402

BUCKET = "docxy-test-bucket"
REGION = "us-east-1"


@pytest.fixture
def s3_service(monkeypatch, tmp_path):
    """An S3Service bound to a mocked bucket."""
    monkeypatch.setattr(settings, "AWS_ENABLED", True)
    monkeypatch.setattr(settings, "AWS_REGION", REGION)
    monkeypatch.setattr(settings, "AWS_S3_BUCKET", BUCKET)
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setattr(settings, "AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_DIR", str(tmp_path))

    with mock_aws():
        boto3.client("s3", region_name=REGION).create_bucket(Bucket=BUCKET)
        yield S3Service()


def test_upload_bytes_to_s3(s3_service):
    result = s3_service.upload_file(b"%PDF-1.4 fake", "documents/2026/09/abc/original.pdf")

    assert result["storage_provider"] == "S3"
    assert result["s3_bucket"] == BUCKET
    assert result["s3_url"].startswith("s3://")
    assert result["file_size_bytes"] == len(b"%PDF-1.4 fake")

    body = boto3.client("s3", region_name=REGION).get_object(
        Bucket=BUCKET, Key="documents/2026/09/abc/original.pdf"
    )["Body"].read()
    assert body == b"%PDF-1.4 fake"


def test_upload_path_to_s3(s3_service, tmp_path):
    src = tmp_path / "source.txt"
    src.write_text("extracted text body", encoding="utf-8")

    result = s3_service.upload_file(src, "extracted/2026/09/abc/extracted.txt", content_type="text/plain")
    assert result["storage_provider"] == "S3"
    assert result["file_size_bytes"] == src.stat().st_size


def test_round_trip_download(s3_service, tmp_path):
    key = "documents/2026/09/round/original.pdf"
    s3_service.upload_file(b"round trip payload", key)

    dest = tmp_path / "downloaded.pdf"
    s3_service.download_file(key, dest)

    assert dest.exists()
    assert dest.read_bytes() == b"round trip payload"


def test_download_of_missing_key_raises(s3_service, tmp_path):
    from app.core.exceptions import S3DownloadError

    with pytest.raises(S3DownloadError):
        s3_service.download_file("documents/does/not/exist.pdf", tmp_path / "nope.pdf")


def test_presigned_url_is_a_real_s3_url(s3_service):
    key = "extracted/2026/09/abc/extracted.txt"
    s3_service.upload_file(b"text", key)

    url = s3_service.generate_presigned_url(key)
    assert url.startswith("https://"), "presigned URL should be an absolute HTTPS URL"
    assert BUCKET in url
    assert "Signature" in url or "X-Amz-Signature" in url


def test_local_mode_presigned_url_points_at_the_storage_route(monkeypatch, tmp_path):
    """With AWS off the advertised URL must match the registered route."""
    monkeypatch.setattr(settings, "AWS_ENABLED", False)
    monkeypatch.setattr(settings, "LOCAL_STORAGE_DIR", str(tmp_path))
    service = S3Service()

    url = service.generate_presigned_url("extracted/2026/09/abc/extracted.txt")
    assert url == "/api/v1/storage/local/extracted/2026/09/abc/extracted.txt"
