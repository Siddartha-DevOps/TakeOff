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
    scale = Column(String(50))  # e.g., "1/8" = 1'-0"
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
