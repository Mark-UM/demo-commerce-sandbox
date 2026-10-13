from fastapi.testclient import TestClient

from app.main import create_app


def test_console_and_assets_are_served_with_api_auth_preserved(tmp_path):
    with TestClient(create_app(str(tmp_path / "console.sqlite3"), "secret")) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert page.headers["content-type"].startswith("text/html")
        assert 'lang="zh-CN"' in page.text
        for path, content_type in (
            ("/static/console.js", "javascript"),
            ("/static/console.css", "text/css"),
        ):
            asset = client.get(path)
            assert asset.status_code == 200
            assert content_type in asset.headers["content-type"]
        assert client.get("/api/admin/summary").status_code == 401
        assert (
            client.get("/api/admin/summary", headers={"X-API-Key": "bad"}).status_code
            == 403
        )
        assert (
            client.get("/api/admin/summary", headers={"X-API-Key": "secret"}).json()[
                "orders"
            ]
            == 120
        )
        assert "/" not in client.get("/openapi.json").json()["paths"]


def test_console_static_paths_cannot_read_application_files(tmp_path):
    with TestClient(create_app(str(tmp_path / "console.sqlite3"))) as client:
        assert client.get("/static/missing.js").status_code == 404
        assert client.get("/static/%2e%2e/main.py").status_code == 404


def test_responsive_artwork_is_local_compact_and_cacheable(tmp_path):
    with TestClient(create_app(str(tmp_path / "art.sqlite3"), "secret")) as client:
        page = client.get("/").text
        assert '<picture class="hero-art" aria-hidden="true">' in page
        assert 'width="1920" height="640" alt=""' in page
        assert 'decoding="async" fetchpriority="high"' in page
        for filename, max_bytes in (
            ("commerce-atmosphere.webp", 150_000),
            ("commerce-atmosphere-small.webp", 50_000),
        ):
            path = f"/static/images/{filename}"
            assert path in page
            asset = client.get(path)
            assert asset.status_code == 200
            assert asset.headers["content-type"] == "image/webp"
            assert asset.content[:4] == b"RIFF"
            assert asset.content[8:12] == b"WEBP"
            assert 0 < len(asset.content) < max_bytes
            cached = client.get(path, headers={"If-None-Match": asset.headers["etag"]})
            assert cached.status_code == 304
            assert cached.content == b""
