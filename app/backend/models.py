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

class UserRole(enum.Enum):
    """
    Org-scoped role — memory/TOGAL_PARITY_REAUDIT.md #17: "No roles/RBAC/
    invites (org exists only)." A User belongs to exactly one Organization
    today (User.organization_id, set once at signup/invite-accept and never
    reassigned anywhere in the app) — CLAUDE.md's "Clerk (orgs/teams
    built-in)" line treats org == team, so this is a plain column on User
    rather than a separate OrganizationMembership join table; a
    many-orgs-per-user model isn't something any other part of the app
    supports today, and adding it here would be scope the gap didn't ask
    for. permissions.py defines the rank ordering and what each role can do.
    """
    OWNER = "owner"    # the org's creator (routes/auth_routes.py's signup); at least one must always exist
    ADMIN = "admin"    # manage members/invites/roles; full project CRUD
    MEMBER = "member"  # create projects; edit/delete only projects they own
    VIEWER = "viewer"  # read-only

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
    role = Column(SQLEnum(UserRole), default=UserRole.MEMBER, nullable=False)
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
    ai_model_version = Column(String(50), default="pending")
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
    # Which AI model produced the annotation being corrected — stamped from
    # the frontend Annotation's meta.aiModelVersion (see
    # annotations/fromDetection.js's detectionMeta). Lets eval_harness.py
    # scope a promotion-gate evaluation to one candidate model's corrections
    # instead of an undifferentiated all-time mix. Null for manual
    # annotations (no AI model produced them) or older events predating
    # this column.
    model_version = Column(String(50), nullable=True, index=True)
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


class ModelVersionStage(enum.Enum):
    CANDIDATE = "candidate"  # registered, not yet evaluated or not yet passing the gate
    ACTIVE = "active"        # currently promoted — at most one per model `name`
    ARCHIVED = "archived"    # was active, superseded by a later promotion
    REJECTED = "rejected"    # explicitly failed a promotion attempt


class ModelVersion(Base):
    """
    Model registry + promotion gate — the entity CLAUDE.md §5 names but never
    specs fields for, closing memory/TOGAL_PARITY_REAUDIT.md #14/§5: "Gate
    model promotion on... mIoU rooms, mAP symbols, measurement-error %,
    tracked per release." See eval_harness.py for how those three metrics
    actually get computed (from CorrectionEvent ground truth, since no
    labeled "golden plan set" exists in this repo) and gate_promotion() for
    the pass/fail logic /eval/model-versions/{id}/promote calls before
    flipping stage to ACTIVE.
    """
    __tablename__ = "model_versions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # e.g. "yolov8m-seg" — groups versions of the same model line
    version_string = Column(String(50), nullable=False, unique=True)  # matches TakeoffResult.ai_model_version / CorrectionEvent.model_version
    stage = Column(SQLEnum(ModelVersionStage), default=ModelVersionStage.CANDIDATE, nullable=False)
    notes = Column(Text, nullable=True)

    # Last eval_harness.py run's output — an audit record, not itself
    # trusted for gating: /promote always re-runs the harness fresh rather
    # than trusting a possibly-stale stored value.
    miou = Column(Float, nullable=True)
    map_score = Column(Float, nullable=True)  # simplified precision proxy — see eval_harness.py's honest caveat on true mAP
    measurement_error_pct = Column(Float, nullable=True)
    eval_sample_size = Column(Integer, nullable=True)
    evaluated_at = Column(DateTime(timezone=True), nullable=True)

    promoted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class HandoffTargetSystem(enum.Enum):
    """
    Which partner's import layout a CostCodeMapping/handoff export targets.
    memory/TOGAL_PARITY_REAUDIT.md #15 names Procore/DESTINI/Ediphi as the
    integrations to match the *style* of — none publish a public API (Togal
    itself has none either, per the same doc), so this is a structured
    file handoff, not a live push. GENERIC is a plain UPC/WBS CSV for any
    other partner or manual review.
    """
    PROCORE = "procore"
    DESTINI = "destini"
    EDIPHI = "ediphi"
    GENERIC = "generic"


class CostCodeMapping(Base):
    """
    Maps one (trade, item) pair from TakeoffResult.quantities_data to a
    partner-estimating cost code — closes memory/TOGAL_PARITY_REAUDIT.md #15:
    "quantities → UPC/WBS map". Keyed by (project_id, trade, item) rather
    than a per-row/per-drawing id: quantities_data has no stable row identity
    across AI re-runs (see export_engine.py), but an estimator maps "Drywall
    / Gypsum board" to a cost code once and expects it to apply everywhere
    that trade/item shows up, across every drawing in the project — exactly
    how Ediphi's real UPC mapping behaves (confirmed via ediphi.com's
    Togal.AI integration announcement: quantities "map automatically to
    Unit Price Catalog (UPC) line items, complete with work breakdown
    structure").

    wbs_code is the coarse grouping (Procore's Cost Code is literally
    "Division-Code", e.g. "09-210", and must match the project's Work
    Breakdown Structure); upc_code is the finer-grained catalog line item
    within it (Ediphi's Unit Price Catalog). Both are free text here — this
    app has no cost database of its own (CLAUDE.md / TOGAL_PARITY_REAUDIT.md
    are explicit that estimating engines are out of scope), so codes are
    either typed by the estimator or pre-filled from CSI_SEED_CATALOG's
    public-standard MasterFormat defaults (handoff_engine.py) and then
    edited/overridden — never silently invented per-project.
    """
    __tablename__ = "cost_code_mappings"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    trade = Column(String(100), nullable=False)
    item = Column(String(200), nullable=False)
    wbs_code = Column(String(50), nullable=True)
    upc_code = Column(String(50), nullable=True)
    description = Column(String(300), nullable=True)
    target_system = Column(SQLEnum(HandoffTargetSystem), default=HandoffTargetSystem.GENERIC, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project")

    __table_args__ = (
        Index("ux_cost_code_mappings_project_trade_item", "project_id", "trade", "item", unique=True),
    )


class HandoffAuditEvent(Base):
    """
    The audit trail memory/TOGAL_PARITY_REAUDIT.md #15 requires — Ediphi's
    own pitch for this integration class is "a complete audit trail [that]
    shows original values, updates, and the user and timestamp for each
    change." Logs every mapping create/update/delete (before/after JSON
    snapshots, mirroring CorrectionEvent's shape) *and* every handoff file
    actually generated, so "who exported what, mapped how, and when" is
    always reconstructable — not just the current mapping state.
    """
    __tablename__ = "handoff_audit_events"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    mapping_id = Column(Integer, ForeignKey("cost_code_mappings.id"), nullable=True)
    action = Column(String(30), nullable=False)  # 'mapping_created' | 'mapping_updated' | 'mapping_deleted' | 'handoff_exported'
    target_system = Column(SQLEnum(HandoffTargetSystem), nullable=True)
    before = Column(Text, nullable=True)  # JSON snapshot
    after = Column(Text, nullable=True)   # JSON snapshot
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    project = relationship("Project")
    user = relationship("User")


class Comment(Base):
    """
    Real-time collaboration — memory/TOGAL_PARITY_REAUDIT.md #16: "No
    real-time collaboration (hardcoded avatars). Build: Liveblocks/Yjs
    presence, cursors, comments." Liveblocks itself is a paid external SaaS
    (needs an account + API key this sandbox has neither of, and CLAUDE.md's
    stack list names it alongside self-hostable Yjs as an either/or); Yjs is
    a CRDT for shared *documents*, which this app doesn't have (annotations
    are still discrete DB rows, not a shared text/structure to merge) — so
    "presence, cursors, comments" is built directly: a FastAPI WebSocket
    (realtime.py/routes/realtime_routes.py) fanned out through Redis pub/sub
    (the "Cache/presence: Upstash Redis" line in CLAUDE.md §3) for
    ephemeral presence/cursor broadcast, plus this table for the one part of
    "comments" that must survive a page reload or a second reviewer showing
    up later: a pinned, threaded, resolvable comment.

    Position is plan-space pixel coordinates (DrawingRenderer.jsx's
    toPlanSpacePoint convention — native image pixels / PDF points-at-
    scale-1, the same space Detection/Measurement geometry and scale
    calibration already use) rather than PostGIS geometry: a comment pin
    has no spatial query need (no ST_Intersects against it), so a real
    geometry column would be unused machinery, unlike Detection.geom.
    """
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    drawing_id = Column(Integer, ForeignKey("drawings.id"), nullable=False, index=True)
    parent_id = Column(Integer, ForeignKey("comments.id"), nullable=True)
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    body = Column(Text, nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    resolved = Column(Boolean, default=False, nullable=False)
    resolved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    project = relationship("Project")
    drawing = relationship("Drawing")
    author = relationship("User", foreign_keys=[author_id])


class InviteStatus(enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"  # lazily flipped from PENDING once expires_at has passed (team_routes.py)


class Invite(Base):
    """
    Org invite — memory/TOGAL_PARITY_REAUDIT.md #17's "invites" half.
    No SMTP/SendGrid/Resend or any mail-sending capability exists anywhere
    in this codebase (grepped — zero hits) — POST /team/invites returns the
    invite (including its token) directly in the API response rather than
    emailing it, and the frontend surfaces a copyable accept link. A real
    deployment would wire a mail provider to actually send it; the
    token/accept flow itself is fully real, only delivery is manual.
    """
    __tablename__ = "invites"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    email = Column(String(255), nullable=False, index=True)
    role = Column(SQLEnum(UserRole), nullable=False, default=UserRole.MEMBER)
    token = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(SQLEnum(InviteStatus), default=InviteStatus.PENDING, nullable=False)
    invited_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    organization = relationship("Organization")
    inviter = relationship("User", foreign_keys=[invited_by])


class MasterUnit(Base):
    """
    Repeating Groups — memory/TOGAL_PARITY_REAUDIT.md #19: "take off one
    master unit (hotel room/apartment) -> apply to hundreds of identical
    spaces." One Drawing (a sheet the estimator measured once — e.g. a
    single hotel room type) tagged with how many times that unit actually
    repeats across the project. repeating_groups.py's apply_multiplier()
    scales that drawing's quantities by instance_count wherever project-
    wide quantities are computed (export_engine.extract_rows()'s two real
    call sites: routes/export_routes.py and handoff_engine.py), so the
    estimator measures the unit once instead of redrawing it N times.

    One row per drawing (unique constraint below) — a drawing is either a
    master unit or it isn't; letting two overlapping MasterUnits target the
    same drawing would make "what's the multiplier here" ambiguous.
    """
    __tablename__ = "master_units"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    drawing_id = Column(Integer, ForeignKey("drawings.id"), nullable=False)
    name = Column(String(200), nullable=False)
    instance_count = Column(Integer, nullable=False, default=1)
    notes = Column(String(500), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    project = relationship("Project")
    drawing = relationship("Drawing")

    __table_args__ = (
        Index("ux_master_units_drawing_id", "drawing_id", unique=True),
    )


class Assembly(Base):
    """A persisted, org-editable trade assembly (one measured qty -> many lines).

    The code library (estimating/assemblies.ASSEMBLY_LIBRARY) is the default seed;
    this table lets an org store and edit its own assemblies. `key` is unique per
    org so it can be referenced by the same expansion engine.
    """
    __tablename__ = "assemblies"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    key = Column(String(100), nullable=False)
    name = Column(String(255), nullable=False)
    trade = Column(String(100), nullable=False)
    driver_unit = Column(String(20), nullable=False)  # 'sf' | 'lf' | 'ea'
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    components = relationship("AssemblyComponent", back_populates="assembly",
                              cascade="all, delete-orphan")

    __table_args__ = (
        Index("ux_assemblies_org_key", "organization_id", "key", unique=True),
    )


class AssemblyComponent(Base):
    """One line item an assembly produces per unit of its driver."""
    __tablename__ = "assembly_components"

    id = Column(Integer, primary_key=True, index=True)
    assembly_id = Column(Integer, ForeignKey("assemblies.id"), nullable=False, index=True)
    item = Column(String(255), nullable=False)
    unit = Column(String(20), nullable=False)          # sf | lf | ea | cy | gal | bf | lot
    factor = Column(Float, nullable=False)             # output qty per 1 driver unit
    waste_pct = Column(Float, nullable=False, default=0)
    trade = Column(String(100), nullable=True)         # optional per-component trade

    assembly = relationship("Assembly", back_populates="components")


class CostBook(Base):
    """A named unit-price list (org/regional) applied when expanding assemblies."""
    __tablename__ = "cost_books"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    currency = Column(String(10), nullable=False, default="USD")
    is_default = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    items = relationship("CostItem", back_populates="cost_book", cascade="all, delete-orphan")


class CostItem(Base):
    """One unit price in a cost book (item -> unit_cost)."""
    __tablename__ = "cost_items"

    id = Column(Integer, primary_key=True, index=True)
    cost_book_id = Column(Integer, ForeignKey("cost_books.id"), nullable=False, index=True)
    item = Column(String(255), nullable=False)
    unit = Column(String(20), nullable=True)
    unit_cost = Column(Float, nullable=False, default=0)

    cost_book = relationship("CostBook", back_populates="items")

    __table_args__ = (
        Index("ux_cost_items_book_item", "cost_book_id", "item", unique=True),
    )


class Estimate(Base):
    """A saved, named snapshot of a priced assemblies estimate.

    Turns an on-the-fly takeoff → assemblies calculation into a durable artifact
    an estimator can name, re-open, and export. `data` is the JSON snapshot
    (drivers / line_items / by_trade / total) so the estimate is reproducible
    even if the drawing or cost book changes later.
    """
    __tablename__ = "estimates"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    drawing_id = Column(Integer, ForeignKey("drawings.id"), nullable=True, index=True)
    cost_book_id = Column(Integer, ForeignKey("cost_books.id"), nullable=True)
    name = Column(String(255), nullable=False)
    total = Column(Float, nullable=False, default=0)
    data = Column(Text, nullable=False)  # JSON snapshot of the estimate
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))