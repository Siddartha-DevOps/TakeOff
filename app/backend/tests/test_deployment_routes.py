import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_vercel_api_proxy_targets_the_live_render_service():
    config = json.loads((REPOSITORY_ROOT / "vercel.json").read_text(encoding="utf-8"))
    api_rewrite = next(
        rewrite for rewrite in config["rewrites"] if rewrite["source"] == "/api/:path*"
    )

    assert api_rewrite["destination"] == (
        "https://takeoff-backend-6c0v.onrender.com/api/:path*"
    )
