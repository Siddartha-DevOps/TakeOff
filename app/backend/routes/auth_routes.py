from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
import schemas
import models
import auth
from auth import get_password_hash, verify_password, create_access_token
from audit import record_activity
from database import get_db
from auth_identity import normalize_email

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/signup", response_model=schemas.Token)
async def signup(user_data: schemas.UserCreate, db: Session = Depends(get_db)):
    email = normalize_email(user_data.email)
    # Check if user exists
    existing_user = db.query(models.User).filter(func.lower(models.User.email) == email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # A company name from onboarding becomes the organization name. Keep the
    # generated name as a backwards-compatible fallback for API clients that
    # only send email/password/full_name.
    organization_name = (user_data.organization_name or "").strip()
    org = models.Organization(
        name=organization_name or f"{user_data.full_name or email}'s Organization"
    )
    try:
        # One transaction: a hashing/constraint failure cannot leave an orphan
        # organization behind. flush() obtains org.id without committing it.
        db.add(org)
        db.flush()
        db_user = models.User(
            email=email,
            full_name=user_data.full_name,
            hashed_password=get_password_hash(user_data.password),
            organization_id=org.id,
            role=models.UserRole.OWNER,
            is_active=True,
        )
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Email already registered")
    except Exception:
        db.rollback()
        raise
    
    # Create access token
    access_token = create_access_token(data={"sub": db_user.email})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": db_user
    }

@router.post("/login", response_model=schemas.Token)
async def login(credentials: schemas.UserLogin, db: Session = Depends(get_db)):
    # Find user
    email = normalize_email(credentials.email)
    user = db.query(models.User).filter(func.lower(models.User.email) == email).first()
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")
    
    # Create access token
    access_token = create_access_token(data={"sub": user.email})

    if user.organization_id:
        record_activity(db, action="login", organization_id=user.organization_id, user_id=user.id)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }

@router.get("/me", response_model=schemas.User)
async def get_current_user_info(current_user: models.User = Depends(auth.get_current_user)):
    return current_user
