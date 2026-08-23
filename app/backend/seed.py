"""
Database seeding script - creates test users and sample data
"""
from sqlalchemy import func
from database import SessionLocal
import models
from auth import get_password_hash
from auth_identity import normalize_email

def seed_database():
    """Seed the database with initial data"""

    db = SessionLocal()

    try:
        print("🌱 Ensuring demo data exists...")

        # Idempotent by natural keys. Another real organization in the same
        # database must never suppress creation of the documented demo login.
        org1 = db.query(models.Organization).filter(models.Organization.name == "ACME Construction").first()
        org2 = db.query(models.Organization).filter(models.Organization.name == "BuildRight LLC").first()
        if org1 is None:
            org1 = models.Organization(name="ACME Construction")
            db.add(org1)
        if org2 is None:
            org2 = models.Organization(name="BuildRight LLC")
            db.add(org2)
        db.flush()

        # Create test users (from /app/memory/test_credentials.md if exists)
        test_users = [
            {
                "email": "alex@acme.com",
                "password": "password123",
                "full_name": "Alex Rivera",
                "organization_id": org1.id,
                "role": models.UserRole.OWNER,
            },
            {
                "email": "priya@buildr.com",
                "password": "password123",
                "full_name": "Priya Patel",
                "organization_id": org2.id,
                "role": models.UserRole.OWNER,
            },
            {
                "email": "demo@takeoff.ai",
                "password": "demo2025",
                "full_name": "Demo User",
                "organization_id": org1.id,
                "role": models.UserRole.MEMBER,
            }
        ]

        db_users = []
        for user_data in test_users:
            email = normalize_email(user_data["email"])
            user = db.query(models.User).filter(func.lower(models.User.email) == email).first()
            if user is None:
                user = models.User(
                    email=email,
                    hashed_password=get_password_hash(user_data["password"]),
                    full_name=user_data["full_name"],
                    organization_id=user_data["organization_id"],
                    role=user_data["role"],
                    is_active=True,
                )
                db.add(user)
            db_users.append(user)
        db.flush()

        # Create sample projects
        sample_projects = [
            {
                "name": "Waterford Tower — Level 12",
                "description": "High-rise residential project",
                "project_type": "High-rise residential",
                "owner_id": db_users[0].id,
                "organization_id": org1.id,
                "status": "active"
            },
            {
                "name": "Meridian Medical Campus",
                "description": "Healthcare facility construction",
                "project_type": "Healthcare",
                "owner_id": db_users[0].id,
                "organization_id": org1.id,
                "status": "active"
            },
            {
                "name": "Oak Grove Elementary Renovation",
                "description": "School renovation project",
                "project_type": "Education",
                "owner_id": db_users[0].id,
                "organization_id": org1.id,
                "status": "review"
            }
        ]

        for project_data in sample_projects:
            exists = db.query(models.Project).filter(
                models.Project.organization_id == project_data["organization_id"],
                models.Project.name == project_data["name"],
            ).first()
            if exists is None:
                db.add(models.Project(**project_data))

        db.commit()
        print("🎉 Demo data is ready")

    except Exception as e:
        print(f"❌ Error seeding database: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()
