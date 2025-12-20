"""
Script to create the first admin user in the database.
Run this once after deploying to Render.
"""
import os
from backend.database import SessionLocal, engine
from backend.models import Base, User
import hashlib

def create_admin():
    """Create the first admin user"""
    # Create tables if they don't exist
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        # Check if admin already exists
        existing_admin = db.query(User).filter(User.username == "admin").first()
        if existing_admin:
            print("✅ Admin user already exists!")
            print(f"   Username: {existing_admin.username}")
            print(f"   Role: {existing_admin.role}")
            return
        
        # Create admin user
        admin_password = "admin123"
        hashed_password = hashlib.sha256(admin_password.encode()).hexdigest()
        
        admin_user = User(
            username="admin",
            password_hash=hashed_password,
            first_name="Admin",
            last_name="User",
            role="admin",
            is_active=True
        )
        
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)
        
        print("✅ Admin user created successfully!")
        print(f"   Username: admin")
        print(f"   Password: admin123")
        print(f"   Role: admin")
        print(f"   ID: {admin_user.id}")
        
    except Exception as e:
        print(f"❌ Error creating admin: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    print("🚀 Initializing admin user...")
    print(f"📊 Database: {os.getenv('DATABASE_URL', 'aviation_mro.db')}")
    create_admin()
