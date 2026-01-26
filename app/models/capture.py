from sqlalchemy import Column, Integer, String, DateTime, JSON, Text
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class Capture(Base):
    __tablename__ = "captures"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True) # Telegram User ID
    user_name = Column(String, nullable=True)
    content_type = Column(String) # 'voice' or 'text'
    raw_content = Column(Text, nullable=True) # Text or Transcription
    intent_data = Column(JSON, nullable=True) # Structured JSON from AI
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="NEW") # NEW, PROCESSED, ERROR
