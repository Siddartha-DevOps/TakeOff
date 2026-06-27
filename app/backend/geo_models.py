"""
First-class geometry data model (PostGIS).

CLAUDE.md guardrail #4: "Geometry is first-class. Store detections/measurements
as real geometry in PostGIS, not as loose JSON blobs." Today the app stores
everything in ``TakeoffResult.detection_data`` as a JSON ``Text`` column, which
cannot be spatially indexed, intersected, measured, or diffed in the database.

This module adds the real model — ``Sheet``, ``Condition``, ``Detection``,
``Measurement``, ``CorrectionEvent``, ``ModelVersion`` — with PostGIS geometry
columns (GeoAlchemy2). Coordinates are stored with **SRID 0** because drawing
geometry is local planar CAD space (PDF points / feet), not geographic. PostGIS
still does exact planar ST_Area / ST_Length / ST_Intersects on SRID 0.

These tables live on a **separate metadata** (``GeoBase``) and are created by the
Alembic migration that first runs ``CREATE EXTENSION postgis`` — they are
deliberately NOT part of the startup ``Base.metadata.create_all`` so the app
still boots on a database where PostGIS has not been provisioned yet.

Cross-table foreign keys (``drawings.id``, ``organizations.id``, ``users.id``)
reference the existing tables by name; they resolve at migration-apply time when
both old and new tables exist in the same database.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

try:  # GeoAlchemy2 is required for the geometry columns; degrade informatively.
    from geoalchemy2 import Geometry

    HAS_GEOALCHEMY2 = True
except ImportError:  # pragma: no cover - exercised only without the dep
    HAS_GEOALCHEMY2 = False

    def Geometry(*_args, **_kwargs):  # type: ignore[misc]
        raise ImportError(
            "geoalchemy2 is required for the PostGIS geometry model. "
            "Install it: pip install geoalchemy2"
        )


# Separate metadata so these tables are managed only by the PostGIS-aware
# Alembic migration, never by the app's startup create_all().
GeoBase = declarative_base()

#: Local planar SRID for drawing-space geometry (PDF points / feet, not lat/lon).
DRAWING_SRID = 0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Sheet(GeoBase):
    """A single drawing page with its calibration (scale, dpi, dimensions).

    Separated from ``Drawing`` because one uploaded file (PDF) can hold many
    sheets, and every measurement depends on the per-sheet scale.
    """

    __tablename__ = "sheets"

    id = Column(Integer, primary_key=True, index=True)
    drawing_id = Column(Integer, ForeignKey("drawings.id", ondelete="CASCADE"), index=True)
    page_no = Column(Integer, default=0)
    scale_ratio = Column(Float)            # real inches per paper inch (e.g. 96)
    scale_text = Column(String(50))        # e.g. '1/8"=1\'-0"'
    dpi = Column(Integer, default=300)     # only relevant to the raster path
    width_pt = Column(Float)               # page width in PDF points
    height_pt = Column(Float)
    is_vector = Column(Boolean, default=False)  # measured from native vectors?
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    detections = relationship("Detection", back_populates="sheet", cascade="all, delete-orphan")


class Condition(GeoBase):
    """A named takeoff condition (trade item) measurements attach to.

    e.g. trade="Flooring", type="LVT", unit="sqft". Mirrors Togal's
    classification model; both AI and manual measurements roll up to a condition.
    """

    __tablename__ = "conditions"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name = Column(String(255), nullable=False)
    trade = Column(String(100))
    type = Column(String(100))
    unit = Column(String(20))              # sqft | ft | ea
    color = Column(String(20))
    formula = Column(Text)                 # optional custom formula (Area * unit cost)
    waste_pct = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    measurements = relationship("Measurement", back_populates="condition")


class ModelVersion(GeoBase):
    """A trained/used model version, for provenance + eval-gated promotion."""

    __tablename__ = "model_versions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    version = Column(String(40), nullable=False)
    task = Column(String(60))              # space_seg | symbol_det | ocr | vector
    metrics = Column(JSON)                 # {"mIoU":..., "mAP":..., "err_pct":...}
    weights_uri = Column(String(500))
    promoted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)


class Detection(GeoBase):
    """A detected/drawn entity stored as real geometry.

    ``source`` distinguishes exact vector geometry from AI predictions and
    manual edits, so accuracy can be tracked per provenance.
    """

    __tablename__ = "detections"

    id = Column(Integer, primary_key=True, index=True)
    sheet_id = Column(Integer, ForeignKey("sheets.id", ondelete="CASCADE"), index=True)
    detection_class = Column(String(80))   # Space | wall | standard_door | ...
    confidence = Column(Float, default=1.0)
    source = Column(String(20), default="vector")  # vector | ai | manual
    model_version_id = Column(Integer, ForeignKey("model_versions.id"), nullable=True)
    properties = Column(JSON)              # arbitrary labels/attrs (editable)
    geom = Column(Geometry(geometry_type="GEOMETRY", srid=DRAWING_SRID))
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    sheet = relationship("Sheet", back_populates="detections")
    measurements = relationship("Measurement", back_populates="detection", cascade="all, delete-orphan")
    corrections = relationship("CorrectionEvent", back_populates="detection", cascade="all, delete-orphan")


class Measurement(GeoBase):
    """A quantity derived from a detection: value + unit + the geometry it came from."""

    __tablename__ = "measurements"

    id = Column(Integer, primary_key=True, index=True)
    detection_id = Column(Integer, ForeignKey("detections.id", ondelete="CASCADE"), index=True)
    condition_id = Column(Integer, ForeignKey("conditions.id", ondelete="SET NULL"), nullable=True)
    value = Column(Float, nullable=False)
    unit = Column(String(20), nullable=False)   # sqft | ft | ea
    geom = Column(Geometry(geometry_type="GEOMETRY", srid=DRAWING_SRID))
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    detection = relationship("Detection", back_populates="measurements")
    condition = relationship("Condition", back_populates="measurements")


class CorrectionEvent(GeoBase):
    """Every human correction — the training-data flywheel (guardrail #5).

    Logged from day one: accept / reject / edit / relabel / resize / create /
    delete, with full before/after snapshots, so corrections become retraining
    data instead of being discarded.
    """

    __tablename__ = "correction_events"

    id = Column(Integer, primary_key=True, index=True)
    detection_id = Column(Integer, ForeignKey("detections.id", ondelete="CASCADE"), index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    action = Column(String(30), nullable=False)  # accept|reject|edit|relabel|resize|create|delete
    before = Column(JSON)
    after = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    detection = relationship("Detection", back_populates="corrections")
