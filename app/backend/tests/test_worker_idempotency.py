import detection_geometry
import models
from types import SimpleNamespace


class Query:
    def __init__(self, model, events):
        self.model, self.events = model, events

    def filter(self, *args): return self
    def all(self): return [(11,), (12,)] if self.model is models.Detection.id else []
    def delete(self, **kwargs):
        self.events.append(("delete", self.model))
        return 2


class Db:
    def __init__(self): self.events = []
    def query(self, model): return Query(model, self.events)
    def flush(self): self.events.append(("flush", None))
    def commit(self): self.events.append(("commit", None))


def test_redelivery_replaces_same_source_detection_projection():
    db = Db()
    assert detection_geometry.persist_detection_geometries(db, 3, 7, {}, source="ai") == 0
    assert ("delete", models.Measurement) in db.events
    assert ("delete", models.Detection) in db.events
    assert db.events[-1] == ("commit", None)


def test_unconfirmed_scale_cleans_stale_trusted_projection(monkeypatch):
    from routes import takeoff_routes
    import scale_validation

    db = Db()
    drawing = SimpleNamespace(id=7, project_id=3)
    deleted = []
    monkeypatch.setattr(scale_validation, "is_scale_confirmed", lambda value: False)
    monkeypatch.setattr(
        takeoff_routes,
        "delete_detection_geometries",
        lambda session, drawing_id, source: deleted.append((drawing_id, source)) or 2,
    )
    monkeypatch.setattr(
        takeoff_routes,
        "persist_detection_geometries",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("untrusted projection persisted")),
    )
    assert takeoff_routes._replace_ai_geometry_projection(db, drawing, {}) == -2
    assert deleted == [(7, "ai")]
    assert db.events[-1] == ("commit", None)


def test_embedding_redelivery_replaces_same_encoder_rows(monkeypatch):
    import clip_embeddings

    class EmbeddingQuery:
        def __init__(self, db): self.db = db
        def filter(self, *args): return self
        def delete(self):
            self.db.rows.clear()
            self.db.deletes += 1

    class EmbeddingDb:
        def __init__(self): self.rows, self.deletes, self.commits = [], 0, 0
        def query(self, model):
            assert model is models.DrawingEmbedding
            return EmbeddingQuery(self)
        def add(self, value): self.rows.append(value)
        def commit(self): self.commits += 1

    db = EmbeddingDb()
    payload = {"rooms": [{"id": "room-1", "label": "Office", "bbox": [0, 0, 10, 10]}]}
    monkeypatch.setattr(clip_embeddings, "embeddings_backend", lambda: "lite")
    monkeypatch.setattr(clip_embeddings, "embed_image_patch", lambda image, label: [0.0] * 512)
    assert clip_embeddings.index_drawing_embeddings(db, 3, 7, "s3://bucket/plan.pdf", payload) == 1
    assert clip_embeddings.index_drawing_embeddings(db, 3, 7, "s3://bucket/plan.pdf", payload) == 1
    assert len(db.rows) == 1
    assert db.deletes == 2 and db.commits == 2


def test_takeoff_result_redelivery_reuses_processing_job_row():
    from routes import takeoff_routes

    class ResultQuery:
        def __init__(self, db): self.db = db
        def filter(self, *args): return self
        def first(self): return self.db.result

    class ResultDb:
        def __init__(self): self.result, self.adds = None, 0
        def query(self, model):
            assert model is models.TakeoffResult
            return ResultQuery(self)
        def add(self, value): self.result, self.adds = value, self.adds + 1

    db = ResultDb()
    first = takeoff_routes._takeoff_result_for_job(db, 7, "job-1")
    second = takeoff_routes._takeoff_result_for_job(db, 7, "job-1")
    assert first is second
    assert first.processing_job_id == "job-1"
    assert db.adds == 1
