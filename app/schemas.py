from pydantic import BaseModel, Field
from typing import Literal, Optional


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class MotherProfile(BaseModel):
    # Kimlik (hafıza güncellemesi için)
    user_id: Optional[str] = None

    # Temel bilgiler
    name: Optional[str] = None
    city: Optional[str] = None

    # Aşama: hamile mi, doğum yaptı mı?
    stage: Optional[Literal["hamile", "dogum_sonrasi"]] = None

    # Hamilelik
    pregnancy_week: Optional[int] = None
    due_date: Optional[str] = None  # ISO format: "2025-03-15"

    # Doğum sonrası
    baby_age_months: Optional[int] = None
    is_breastfeeding: bool = False

    # Genel
    is_first_baby: bool = True
    halal_sensitive: bool = False
    allergies: list[str] = Field(default_factory=list)
    has_gestational_diabetes: bool = False
    has_other_conditions: Optional[str] = None
    memories: list[dict] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str
    conversation_history: list[ChatMessage] = Field(default_factory=list)
    profile: Optional[MotherProfile] = None
    image_base64: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    quick_replies: list[str] = Field(default_factory=list)
    safety_flag: Literal["normal", "dikkat", "acil"] = "normal"
    topic_category: str = "genel"
