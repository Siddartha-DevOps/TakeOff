from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
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
    
    class Config:
        from_attributes = True
        use_enum_values = True

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


