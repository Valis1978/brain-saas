from app.db.session import engine
from app.models.capture import Base

def init_db():
    print("Initializing database...")
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully!")

if __name__ == "__main__":
    init_db()
