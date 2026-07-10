from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, Enum as SQLEnum, Float
from sqlalchemy.orm import relationship
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