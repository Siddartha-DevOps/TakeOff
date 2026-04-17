"\"\"\"
Database seeding script - creates test users and sample data
\"\"\"
from sqlalchemy.orm import Session
from database import SessionLocal, engine, Base
import models
from auth import get_password_hash
from datetime import datetime, timezone

def seed_database():
    \"\"\"Seed the database with initial data\"\"\"
    
    # Create tables
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    try:
        # Check if data already exists
        existing_orgs = db.query(models.Organization).count()
        if existing_orgs > 0:
            print(\"✅ Database already seeded\")
            return
        
        print(\"🌱 Seeding database...\")
        
        # Create organizations
        org1 = models.Organization(name=\"ACME Construction\")
        org2 = models.Organization(name=\"BuildRight LLC\")
        db.add_all([org1, org2])
        db.commit()
        db.refresh(org1)
        db.refresh(org2)
        print(f\"✅ Created {2} organizations\")
        
        # Create test users (from /app/memory/test_credentials.md if exists)
        test_users = [
            {
                \"email\": \"alex@acme.com\",
                \"password\": \"password123\",
                \"full_name\": \"Alex Rivera\",
                \"organization_id\": org1.id
            },
            {
                \"email\": \"priya@buildr.com\",
                \"password\": \"password123\",
                \"full_name\": \"Priya Patel\",
                \"organization_id\": org2.id
            },
            {
                \"email\": \"demo@takeoff.ai\",
                \"password\": \"demo2025\",
                \"full_name\": \"Demo User\",
                \"organization_id\": org1.id
            }
        ]
        
        db_users = []
        for user_data in test_users:
            hashed_password = get_password_hash(user_data[\"password\"])
            user = models.User(
                email=user_data[\"email\"],
                hashed_password=hashed_password,
                full_name=user_data[\"full_name\"],
                organization_id=user_data[\"organization_id\"],
                is_active=True
            )
            db.add(user)
            db_users.append(user)
        
        db.commit()
        for user in db_users:
            db.refresh(user)
        print(f\"✅ Created {len(db_users)} test users\")
        
        # Create sample projects
        sample_projects = [
            {
                \"name\": \"Waterford Tower — Level 12\",
                \"description\": \"High-rise residential project\",
                \"project_type\": \"High-rise residential\",
                \"owner_id\": db_users[0].id,
                \"organization_id\": org1.id,
                \"status\": \"active\"
            },
            {
                \"name\": \"Meridian Medical Campus\",
                \"description\": \"Healthcare facility construction\",
                \"project_type\": \"Healthcare\",
                \"owner_id\": db_users[0].id,
                \"organization_id\": org1.id,
                \"status\": \"active\"
            },
            {
                \"name\": \"Oak Grove Elementary Renovation\",
                \"description\": \"School renovation project\",
                \"project_type\": \"Education\",
                \"owner_id\": db_users[0].id,
                \"organization_id\": org1.id,
                \"status\": \"review\"
            }
        ]
        
        for project_data in sample_projects:
            project = models.Project(**project_data)
            db.add(project)
        
        db.commit()
        print(f\"✅ Created {len(sample_projects)} sample projects\")
        
        print(\"🎉 Database seeded successfully!\")
        
    except Exception as e:
        print(f\"❌ Error seeding database: {e}\")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == \"__main__\":
    seed_database()
"