import sys
from types import SimpleNamespace

from ai.inference.remote_clip import RemoteClipEmbeddings


def test_remote_clip_validates_text_and_region_vectors(monkeypatch):
    vector = [0.0] * 512

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def submit(self, *args, api_name):
            value = ({"embedding": vector} if api_name == "/embed_clip_text"
                     else {"regions": [{"annotation_id": "a", "embedding": vector}]})
            return SimpleNamespace(result=lambda timeout: value)

    monkeypatch.setitem(sys.modules, "gradio_client", SimpleNamespace(
        Client=Client, handle_file=lambda path: path,
    ))
    client = RemoteClipEmbeddings(space_id="owner/space", token="secret")
    assert len(client.embed_text("door")) == 512
    result = client.embed_regions("drawing.png", [{"annotation_id": "a", "bbox": [0, 0, 10, 10]}])
    assert result[0]["annotation_id"] == "a"
    assert len(result[0]["embedding"]) == 512


def test_remote_clip_rejects_wrong_vector_size(monkeypatch):
    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def submit(self, *args, **kwargs):
            return SimpleNamespace(result=lambda timeout: {"embedding": [1.0]})

    monkeypatch.setitem(sys.modules, "gradio_client", SimpleNamespace(Client=Client))
    client = RemoteClipEmbeddings(space_id="owner/space", token="secret")
    try:
        client.embed_text("door")
        assert False, "expected invalid embeddings to be rejected"
    except Exception as exc:
        assert "invalid embedding" in str(exc)
