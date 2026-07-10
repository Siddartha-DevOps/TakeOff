from pydantic import BaseModel, EmailStr, Field
from typing import Any, Dict, Literal, Optional, List
from datetime import datetime
from models import ProcessingStatus

# User Schemas
class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None

class UserCreate(UserBase):
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class User(UserBase):
    id: int
    is_active: bool
    organization_id: Optional[int]
    created_at: datetime
    
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    user: User

# Organization Schemas
class OrganizationBase(BaseModel):
    name: str

class OrganizationCreate(OrganizationBase):
    pass

class Organization(OrganizationBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

# Project Schemas
class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None
    project_type: Optional[str] = None

class ProjectCreate(ProjectBase):
    pass

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    project_type: Optional[str] = None
    status: Optional[str] = None

class Project(ProjectBase):
    id: int
    owner_id: int
    organization_id: int
    status: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class ProjectList(Project):
    sheets_count: int = 0
    progress: int = 0
    
    class Config:
        from_attributes = True

# Drawing Schemas
class DrawingBase(BaseModel):
    sheet_name: Optional[str] = None
    scale: Optional[str] = None

class DrawingCreate(DrawingBase):
    pass

class Drawing(DrawingBase):
    id: int
    project_id: int
    filename: str
    original_filename: str
    file_size: Optional[int]
    file_type: Optional[str]
    processing_status: ProcessingStatus
    uploaded_at: datetime
    processed_at: Optional[datetime]
    scale_ratio: Optional[float] = None
    scale_source: Optional[str] = None
    scale_calibrated_at: Optional[datetime] = None
    page_number: int = 0
    total_pages: Optional[int] = None
    sheet_number: Optional[str] = None
    discipline: Optional[str] = None
    upload_batch_id: Optional[str] = None

    class Config:
        from_attributes = True
        use_enum_values = True

# Condition Schemas
class ConditionBase(BaseModel):
    name: str
    trade: str
    space_type: Optional[str] = None
    annotation_type: Literal["count", "line", "area"]
    unit: str
    color: str = "#6366f1"
    waste_percent: float = 0
    unit_cost: float = 0

class ConditionCreate(ConditionBase):
    pass

class ConditionUpdate(BaseModel):
    name: Optional[str] = None
    trade: Optional[str] = None
    space_type: Optional[str] = None
    annotation_type: Optional[Literal["count", "line", "area"]] = None
    unit: Optional[str] = None
    color: Optional[str] = None
    waste_percent: Optional[float] = None
    unit_cost: Optional[float] = None

class Condition(ConditionBase):
    id: int
    project_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Correction Event Schemas — the training-data flywheel (CLAUDE.md §2/§5)
class CorrectionEventCreate(BaseModel):
    drawing_id: Optional[int] = None
    annotation_id: str
    annotation_type: Literal["count", "line", "area"]
    action: Literal["accept", "reject", "relabel", "edit"]
    before: Optional[Dict[str, Any]] = None
    after: Optional[Dict[str, Any]] = None

class CorrectionEvent(BaseModel):
    id: int
    project_id: int
    drawing_id: Optional[int]
    annotation_id: str
    annotation_type: str
    action: str
    before: Optional[Dict[str, Any]]
    after: Optional[Dict[str, Any]]
    user_id: int
    created_at: datetime

# Takeoff Result Schemas
class TakeoffResultCreate(BaseModel):
    detection_data: str
    quantities_data: str
    confidence_scores: str
    processing_time_ms: int

class TakeoffResult(TakeoffResultCreate):
    id: int
    drawing_id: int
    ai_model_version: str
    created_at: datetime
    
    class Config:
        from_attributes = True


