from sqlalchemy import Column, Index, Integer, String, DateTime, ForeignKey, Text, Boolean, Enum as SQLEnum, Float
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry
from pgvector.sqlalchemy import Vector
from datetime import datetime, timezone
import enum
from database import Base

class ProcessingStatus(enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class Organization(Base):
    __tablename__ = "organizations"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    users = relationship("User", back_populates="organization")
    projects = relationship("Project", back_populates="organization")

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255))
    is_active = Column(Boolean, default=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    organization = relationship("Organization", back_populates="users")
    projects = relationship("Project", back_populates="owner")

class Project(Base):
    __tablename__ = "projects"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    project_type = Column(String(100))  # e.g., "High-rise residential", "Healthcare"
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    status = Column(String(50), default="active")  # active, archived, draft
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    owner = relationship("User", back_populates="projects")
    organization = relationship("Organization", back_populates="projects")
    drawings = relationship("Drawing", back_populates="project", cascade="all, delete-orphan")
    conditions = relationship("Condition", back_populates="project", cascade="all, delete-orphan")

class Condition(Base):
    """
    A named, measured item that AI and manual detections attach to —
    Togal calls this a "condition" (CLAUDE.md §5 calls it out too).
    Project-scoped rather than per-sheet: the same "Interior Partition
    Drywall" condition accumulates quantity across every sheet in a takeoff.
    """
    __tablename__ = "conditions"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    name = Column(String(255), nullable=False)          # e.g. "Interior Partition Drywall"
    trade = Column(String(100), nullable=False)          # e.g. "Drywall"
    space_type = Column(String(100), nullable=True)      # e.g. "Bedroom" — for room/space-type conditions
    annotation_type = Column(String(20), nullable=False)  # 'count' | 'line' | 'area' — matches the frontend Annotation model
    unit = Column(String(20), nullable=False)            # 'ea' | 'lf' | 'sf'
    color = Column(String(20), default="#6366f1")
    waste_percent = Column(Float, default=0)
    # Custom formula (CLAUDE.md's "waste%, formula" field, TOGAL_PARITY_REAUDIT.md
    # #5 "Add Custom Formula fields (Area × Unit Cost)"): total cost for a
    # condition is quantity * unit_cost * (1 + waste_percent/100), where
    # quantity is the live sum of measuredValue across its attached shapes
    # (see Takeoff.jsx's conditionCostTotals). "Area" is the common case
    # (annotation_type='area', unit='sf') but the same formula generalizes
    # to any unit (lf, ea).
    unit_cost = Column(Float, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    project = relationship("Project", back_populates="conditions")

class Drawing(Base):
    __tablename__ = "drawings"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)  # Local path or S3 URL
    file_size = Column(Integer)  # in bytes
    file_type = Column(String(50))  # PDF, TIFF, PNG, JPG
    sheet_name = Column(String(255))  # e.g., "A-101 Level 12"
    scale = Column(String(50))  # human-readable label, e.g. 1/8" = 1'-0"

    # Plan-set ingestion (memory/TOGAL_PARITY_REAUDIT.md #13) — a multi-page
    # PDF upload becomes one Drawing row per page, all sharing the same
    # file_path (the original multi-page file; ai/preprocessing.py's
    # page_number param picks the right page out of it) so nothing gets
    # re-encoded or duplicated on disk/object storage. sheet_number/
    # discipline are best-effort ai/title_block_ocr.py output — null if OCR
    # was unavailable or the title block wasn't parseable, never fabricated.
    page_number = Column(Integer, nullable=False, default=0)  # 0-indexed, matches preprocessing.py's convention
    total_pages = Column(Integer, nullable=True)  # page count of the source file this row came from
    sheet_number = Column(String(50), nullable=True)  # OCR-extracted, e.g. "A-101"
    discipline = Column(String(10), nullable=True)  # OCR-derived from sheet_number's leading letter(s), e.g. "A"
    upload_batch_id = Column(String(64), nullable=True, index=True)  # groups sheets split from the same upload

    # Scale calibration — see routes/scale_routes.py. scale_ratio is paper-inches
    # per real-foot (×12), expressed in the same 300-DPI pixel space
    # ai/preprocessing.py rasterizes drawings into, so it plugs directly into
    # ai/preprocessing.pixels_to_feet()/pixels_to_sqft() unchanged.
    scale_ratio = Column(Float, nullable=True)
    scale_source = Column(String(20), nullable=True)  # 'manual' | 'ocr' | 'default'
    scale_calibrated_at = Column(DateTime(timezone=True), nullable=True)
    # Cached OCR suggestion so GET /scale doesn't re-run OCR on every request.
    ocr_scale_ratio = Column(Float, nullable=True)
    ocr_scale_text = Column(String(255), nullable=True)  # raw matched OCR text, e.g. '1/8" = 1\'-0"'
    ocr_scale_confidence = Column(Float, nullable=True)

    processing_status = Column(SQLEnum(ProcessingStatus), default=ProcessingStatus.PENDING)
    uploaded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    processed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    project = relationship("Project", back_populates="drawings")
    takeoff_results = relationship("TakeoffResult", back_populates="drawing", cascade="all, delete-orphan")
    detections = relationship("Detection", back_populates="drawing", cascade="all, delete-orphan")

class Detection(Base):
    """
    Geometry is first-class (CLAUDE.md §2/§5): a detected shape — AI or
    manual — stored as real PostGIS geometry, not a JSON blob. This is the
    server-side counterpart to the frontend's unified Annotation model
    (frontend/src/annotations/types.js); annotation_id is the join key
    between the two, since annotations aren't the system of record here —
    TakeoffResult.detection_data still is, this is the geometry-first mirror
    of it.

    geom is plan-space (source-raster pixel coordinates — the same space
    ai/preprocessing.py rasterizes drawings into), not geographic, hence
    srid=0 rather than a real-world SRID like 4326.
    """
    __tablename__ = "detections"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    drawing_id = Column(Integer, ForeignKey("drawings.id"), nullable=False)
    annotation_id = Column(String(64), nullable=False)  # matches frontend Annotation.id
    annotation_type = Column(String(20), nullable=False)  # 'count' | 'line' | 'area'
    class_label = Column(String(100), nullable=False)  # e.g. room label, door/window type
    confidence = Column(Float, nullable=True)
    source = Column(String(20), nullable=False, default="ai")  # 'ai' | 'manual'
    condition_id = Column(Integer, ForeignKey("conditions.id"), nullable=True)
    geom = Column(Geometry(geometry_type="GEOMETRY", srid=0), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    project = relationship("Project")
    drawing = relationship("Drawing", back_populates="detections")
    condition = relationship("Condition")
    measurements = relationship("Measurement", back_populates="detection", cascade="all, delete-orphan")

class Measurement(Base):
    """
    The derived quantity for a Detection — value/unit/geom, per CLAUDE.md §5.
    Split from Detection so re-measuring (e.g. after a scale recalibration)
    can produce a new Measurement without mutating the original detected shape.
    """
    __tablename__ = "measurements"

    id = Column(Integer, primary_key=True, index=True)
    detection_id = Column(Integer, ForeignKey("detections.id"), nullable=False)
    value = Column(Float, nullable=False)
    unit = Column(String(20), nullable=False)  # 'sf' | 'lf' | 'ea'
    geom = Column(Geometry(geometry_type="GEOMETRY", srid=0), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    detection = relationship("Detection", back_populates="measurements")

class DrawingEmbedding(Base):
    """
    AI Search (image/text/pattern) index — closes the "CLIP endpoint
    returns [], TODO pgvector" gap in memory/TOGAL_PARITY_REAUDIT.md #7.
    One row per indexed patch: today that's one per AI detection (built on
    ingest — see clip_embeddings.index_drawing_embeddings(), called from
    the same places detection_geometry.persist_detection_geometries() is),
    embedded in CLIP's shared image/text space so both "find more like this
    region" and "find all outlets" work against the same index via
    pgvector cosine similarity.

    embed_image_patch()/embed_text() (clip_embeddings.py) require torch +
    CLIP, which — like every other heavy ML dependency in this backend
    (ai/detection_engine.py, ai/scale_detection.py) — live in the separate
    app/requirements.txt GPU stack, not backend/requirements.txt, per
    CLAUDE.md §2's "heavy ML runs on a separate GPU service" guardrail.
    Ingest and search both degrade to a clear message, never a crash, when
    that stack isn't installed.
    """
    __tablename__ = "drawing_embeddings"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    drawing_id = Column(Integer, ForeignKey("drawings.id"), nullable=False)
    annotation_id = Column(String(64), nullable=True)  # matching Detection.annotation_id, when this patch came from one
    label_hint = Column(String(100), nullable=True)     # e.g. detected class, for a readable result list
    geom = Column(Geometry(geometry_type="GEOMETRY", srid=0), nullable=False)  # patch bbox, plan-space pixels
    embedding = Column(Vector(512), nullable=False)     # CLIP ViT-B/32 image/text embedding dim
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        # HNSW, cosine distance — matches the <=> operator AI Search's
        # queries use (routes/ai_routes.py). Declared here (unlike
        # idx_*_geom, which geoalchemy2 manages automatically) so Alembic
        # autogenerate/check knows about it instead of flagging it as drift.
        Index(
            "idx_drawing_embeddings_vector", "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    # Relationships
    project = relationship("Project")
    drawing = relationship("Drawing")

class TakeoffResult(Base):
    __tablename__ = "takeoff_results"
    
    id = Column(Integer, primary_key=True, index=True)
    drawing_id = Column(Integer, ForeignKey("drawings.id"), nullable=False)
    detection_data = Column(Text)  # JSON string with rooms, doors, windows, walls
    quantities_data = Column(Text)  # JSON string with trade quantities
    confidence_scores = Column(Text)  # JSON string with confidence metrics
    processing_time_ms = Column(Integer)
    ai_model_version = Column(String(50), default="mock_v1")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    drawing = relationship("Drawing", back_populates="takeoff_results")

class CorrectionEvent(Base):
    """
    The training-data flywheel (CLAUDE.md §2/§5): every accept/reject/relabel
    a user makes on an AI (or manual) annotation, logged from day one.
    annotation_id matches the frontend Annotation.id — annotations themselves
    aren't persisted as rows yet (still JSON blobs in TakeoffResult), so this
    is intentionally not a hard FK, just a matching key.
    """
    __tablename__ = "correction_events"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    drawing_id = Column(Integer, ForeignKey("drawings.id"), nullable=True)  # null for un-uploaded/demo sheets
    annotation_id = Column(String(64), nullable=False)
    annotation_type = Column(String(20), nullable=False)  # 'count' | 'line' | 'area'
    action = Column(String(20), nullable=False)  # 'accept' | 'reject' | 'relabel' | 'edit'
    before = Column(Text, nullable=True)  # JSON snapshot
    after = Column(Text, nullable=True)   # JSON snapshot
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    project = relationship("Project")
    drawing = relationship("Drawing")
    user = relationship("User")

class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(255), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="usd")
    payment_status = Column(String(50), default="pending")  # pending, paid, failed, expired
    status = Column(String(50), default="initiated")  # initiated, completed, failed
    payment_metadata = Column(Text)  # JSON string (renamed from 'metadata' - reserved in SQLAlchemy)
    stripe_price_id = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    user = relationship("User")

class UserSubscription(Base):
    __tablename__ = "user_subscriptions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    plan_name = Column(String(50), nullable=False)  # starter, growth
    status = Column(String(50), default="active")  # active, cancelled, expired
    stripe_session_id = Column(String(255), nullable=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="usd")
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Relationships
    user = relationship("User")