import os
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from anthropic import Anthropic, APIError
from dotenv import load_dotenv

from app.schemas import ChatRequest, ChatResponse, MotherProfile
from app.system_prompt import SYSTEM_PROMPT

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kucak")

API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not API_KEY:
    logger.warning(
        "ANTHROPIC_API_KEY tanımlı değil — .env dosyasını kontrol et "
        "(bkz. .env.example). /chat çağrıları şu an hata verecek."
    )

client = Anthropic(api_key=API_KEY) if API_KEY else None

app = FastAPI(title="Kucak API", version="0.1.0")

# Mobil uygulama (Expo) ve Railway production ortamı için.
# ALLOWED_ORIGINS env değişkeni ayarlanmışsa onu kullan, yoksa geliştirme ortamı için açık bırak.
allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

RESPOND_TOOL = {
    "name": "respond_to_mother",
    "description": "Anneye verilecek cevabı ve sohbet arayüzü için yapılandırılmış alanları üretir.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answer_text": {
                "type": "string",
                "description": "Anneye gösterilecek asıl cevap metni. <ton> ve <format_kurallari> kurallarına uy.",
            },
            "quick_replies": {
                "type": "array",
                "items": {"type": "string"},
                "description": "0-4 arası, annenin tıklayabileceği kısa hızlı yanıt seçeneği (bkz. <hizli_yanit_uretimi>). Uygun değilse boş liste.",
                "maxItems": 4,
            },
            "safety_flag": {
                "type": "string",
                "enum": ["normal", "dikkat", "acil"],
                "description": "normal: sıradan soru. dikkat: hafif uyarı gerektiren konu (örn. düşük ateş, sarı bayrak ruhsal). acil: kırmızı bayrak (112/doktor yönlendirmesi yapıldı).",
            },
            "topic_category": {
                "type": "string",
                "description": "Konunun kısa kategorisi, örn. 'bitkisel_urun', 'alerji', 'ek_gida', 'ruhsal', 'kapsam_disi'.",
            },
        },
        "required": ["answer_text", "quick_replies", "safety_flag", "topic_category"],
    },
}


def build_profile_block(profile: MotherProfile | None) -> str:
    """Anne profilini sistem promptuna eklenecek kısa bir bağlam bloğuna çevirir.
    Gerçek implementasyonda bu, Postgres'teki kalıcı profilden gelecek
    (teknik-mimari-maliyet-v1.md Bölüm 4) — şimdilik istemciden geliyor."""
    if not profile:
        return ""
    parts = []
    if profile.pregnancy_week:
        parts.append(f"Şu an {profile.pregnancy_week}. gebelik haftasında.")
    if profile.baby_age_months is not None:
        parts.append(f"Bebeği {profile.baby_age_months} aylık.")
    if profile.halal_sensitive:
        parts.append("Helal ürünlere dikkat ediyor — etiket sorularında bunu varsayılan olarak değerlendir.")
    if profile.allergies:
        parts.append(f"Bilinen alerji/hassasiyetleri: {', '.join(profile.allergies)}.")
    if not parts:
        return ""
    return "\n\n<anne_profili>\n" + " ".join(parts) + "\n</anne_profili>"


@app.get("/")
def health_check():
    return {"status": "ok", "service": "kucak-api"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    if client is None:
        raise HTTPException(
            status_code=500,
            detail="ANTHROPIC_API_KEY tanımlı değil. .env dosyasına gerçek API anahtarını ekle.",
        )

    system = SYSTEM_PROMPT + build_profile_block(request.profile)

    messages = [{"role": m.role, "content": m.content} for m in request.conversation_history]
    messages.append({"role": "user", "content": request.message})

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=system,
            messages=messages,
            tools=[RESPOND_TOOL],
            tool_choice={"type": "tool", "name": "respond_to_mother"},
        )
    except APIError as e:
        logger.error(f"Anthropic API hatası: {e}")
        raise HTTPException(status_code=502, detail=f"AI servisinden cevap alınamadı: {e}")

    tool_use_block = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use_block is None:
        raise HTTPException(status_code=502, detail="Model yapılandırılmış bir cevap üretmedi.")

    data = tool_use_block.input
    return ChatResponse(
        answer=data.get("answer_text", ""),
        quick_replies=data.get("quick_replies", []),
        safety_flag=data.get("safety_flag", "normal"),
        topic_category=data.get("topic_category", "genel"),
    )
