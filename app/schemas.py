from pydantic import BaseModel, Field
from typing import Literal, Optional


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class MotherProfile(BaseModel):
    """Henüz Postgres'te kalıcı değil — ileride teknik-mimari-maliyet-v1.md Bölüm 4'teki
    kişiselleştirme mimarisine göre veritabanından doldurulacak. Şimdilik istemciden
    (mobil uygulamadan) doğrudan gönderiliyor."""
    pregnancy_week: Optional[int] = None
    baby_age_months: Optional[int] = None
    halal_sensitive: bool = False
    allergies: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str
    conversation_history: list[ChatMessage] = Field(default_factory=list)
    profile: Optional[MotherProfile] = None


class ChatResponse(BaseModel):
    answer: str
    quick_replies: list[str] = Field(default_factory=list)
    safety_flag: Literal["normal", "dikkat", "acil"] = "normal"
    topic_category: str = "genel"
