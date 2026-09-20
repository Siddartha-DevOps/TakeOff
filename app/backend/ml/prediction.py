"""Common geometry-first prediction and provenance contract for all AI models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GeometryType(str, Enum):
    BOUNDING_BOX = "BOUNDING_BOX"
    POLYGON = "POLYGON"
    LINESTRING = "LINESTRING"
    POINT = "POINT"


def _point(value: Any) -> bool:
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(isinstance(coordinate, (int, float)) for coordinate in value))


class Prediction(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    prediction_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    drawing_id: int | str
    page_id: int | str
    class_name: str = Field(alias="class", min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    geometry_type: GeometryType
    geometry: Any
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("created_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_geometry(self) -> "Prediction":
        geometry = self.geometry
        if self.geometry_type == GeometryType.POINT:
            if not _point(geometry):
                raise ValueError("POINT geometry must be [x, y]")
        elif self.geometry_type == GeometryType.BOUNDING_BOX:
            if (not isinstance(geometry, (list, tuple)) or len(geometry) != 4
                    or not all(isinstance(value, (int, float)) for value in geometry)
                    or geometry[2] <= geometry[0] or geometry[3] <= geometry[1]):
                raise ValueError("BOUNDING_BOX geometry must be [x1, y1, x2, y2] with positive area")
        elif self.geometry_type == GeometryType.LINESTRING:
            if not isinstance(geometry, list) or len(geometry) < 2 or not all(_point(p) for p in geometry):
                raise ValueError("LINESTRING geometry must contain at least two points")
        elif self.geometry_type == GeometryType.POLYGON:
            if not isinstance(geometry, list) or len(geometry) < 4 or not all(_point(p) for p in geometry):
                raise ValueError("POLYGON geometry must contain at least four points")
            if list(geometry[0]) != list(geometry[-1]):
                raise ValueError("POLYGON geometry must be a closed ring")
            area = abs(sum(
                a[0] * b[1] - b[0] * a[1]
                for a, b in zip(geometry, geometry[1:])
            )) / 2.0
            if area <= 0:
                raise ValueError("POLYGON geometry must have positive area")
        return self
