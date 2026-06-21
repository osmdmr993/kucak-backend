import os
import json
import logging
import asyncio
import urllib.request

from fastapi import FastAPI, HTTPException, Request
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
    logger.warning("ANTHROPIC_API_KEY tanimli degil.")

client = Anthropic(api_key=API_KEY) if API_KEY else None

app = FastAPI(title="Kucak API", version="0.1.0")

allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

RESPOND_TOOL = {
    "name": "respond_to_mother",
    "description": "Anneye verilecek cevabi ve sohbet arayuzu icin yapilandirilmis alanlari uretir.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answer_text": {
                "type": "string",
                "description": "Anneye gosterilecek asil cevap metni.",
            },
            "quick_replies": {
                "type": "array",
                "items": {"type": "string"},
                "description": "0-4 arasi, annenin tiklayabilecegi kisa hizli yanit secenegi. Uygun degilse bos liste.",
                "maxItems": 4,
            },
            "safety_flag": {
                "type": "string",
                "enum": ["normal", "dikkat", "acil"],
                "description": "normal: siradan soru. dikkat: hafif uyari. acil: 112/doktor yonlendirmesi.",
            },
            "topic_category": {
                "type": "string",
                "description": "Konunun kisa kategorisi, orn. 'bitkisel_urun', 'alerji', 'ek_gida', 'ruhsal'.",
            },
        },
        "required": ["answer_text", "quick_replies", "safety_flag", "topic_category"],
    },
}

MEMORY_EXTRACTION_PROMPT = """Sen bir hafıza çıkarma asistanısın. Sana bir anne ile Kucak AI arasındaki son konuşma mesajı ve mevcut hafıza listesi verilecek.

Görevin: Bu konuşmadan, annenin veya bebeğinin durumunu gelecekte de bilinmesi gereken ÖNEMLİ bir bilgi var mı? Varsa çıkar.

Kaydedilmesi gereken bilgiler:
- Gebelik haftası değişikliği ("32. haftaya girdim")
- Bebeğin yaşı güncellenmesi ("bebeğim 6 aylık oldu")
- Ek gıdaya geçiş, emzirme durumu değişimi
- Yeni sağlık durumu (demir eksikliği, reflü, kolik vb.)
- Kullandığı takviyeler/ilaçlar
- Bebekte yeni alerji/hassasiyet tespiti
- Doğum gerçekleşti (hamilelikten doğum sonrasına geçiş)

Kaydedilmemesi gereken bilgiler:
- Günlük sorular ("bugün ne yemeliyim")
- Genel beslenme soruları
- Zaten profilde olan bilgiler

YANITI SADECE VE SADECE HAM JSON OLARAK VER. Başka hiçbir şey yazma. Markdown kullanma. Backtick kullanma.

Güncelleme gerekmiyorsa tam olarak şunu yaz:
{{"should_update": false}}

Güncelleme gerekiyorsa tam olarak şunu yaz:
{{"should_update": true, "memories": [{{"key": "benzersiz_anahtar", "value": "bilgi", "date": "YYYY-MM-DD"}}]}}

Mevcut hafıza: {current_memories}
Anne mesajı: {user_message}
AI cevabı: {ai_answer}"""


def build_profile_block(profile: MotherProfile | None) -> str:
    if not profile:
        return ""
    parts = []

    if profile.name:
        parts.append(f"Annenin adı: {profile.name}.")
    if profile.city:
        parts.append(f"Yaşadığı şehir: {profile.city}.")

    if profile.stage == "hamile":
        if profile.pregnancy_week:
            parts.append(f"Şu an {profile.pregnancy_week}. gebelik haftasında.")
        if profile.due_date:
            parts.append(f"Tahmini doğum tarihi: {profile.due_date}.")
    elif profile.stage == "dogum_sonrasi":
        if profile.baby_age_months is not None:
            parts.append(f"Bebeği {profile.baby_age_months} aylık.")
        if profile.is_breastfeeding:
            parts.append("Emziriyor.")
        else:
            parts.append("Emzirmiyor.")

    if profile.is_first_baby:
        parts.append("İlk bebeği.")
    else:
        parts.append("Daha önce çocuğu olmuş.")

    if profile.has_gestational_diabetes:
        parts.append("Gestasyonel diyabeti var — karbonhidrat ve şeker önerilerinde dikkatli ol.")

    if profile.halal_sensitive:
        parts.append("Helal ürünlere dikkat ediyor.")

    if profile.allergies:
        parts.append(f"Bilinen alerji/hassasiyetleri: {', '.join(profile.allergies)}.")

    if profile.has_other_conditions:
        parts.append(f"Diğer özel durum: {profile.has_other_conditions}.")

    # Hafıza bloğu
    if profile.memories:
        memory_lines = []
        for m in profile.memories:
            date_str = f" ({m.get('date', '')})" if m.get('date') else ""
            memory_lines.append(f"- {m.get('value', '')}{date_str}")
        if memory_lines:
            parts.append("\nAnne hakkında daha önce öğrenilen bilgiler:\n" + "\n".join(memory_lines))

    if not parts:
        return ""
    return "\n\n<anne_profili>\n" + "\n".join(parts) + "\n</anne_profili>"


def extract_memories_background(
    user_message: str,
    ai_answer: str,
    current_memories: list,
    user_id: str | None,
    supabase_url: str | None,
    supabase_key: str | None,
):
    """Arka planda hafıza çıkarır ve Supabase'e kaydeder."""
    logger.info(f"Hafiza extraction basladi: user_id={user_id}")
    
    if not client:
        return
    if not user_id:
        return
    if not supabase_url:
        return
    if not supabase_key:
        return

    try:
        prompt = MEMORY_EXTRACTION_PROMPT.format(
            current_memories=json.dumps(current_memories, ensure_ascii=False),
            user_message=user_message,
            ai_answer=ai_answer,
        )

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(raw)

        if not result.get("should_update"):
            return

        new_memories = result.get("memories", [])
        if not new_memories:
            return

        # Mevcut hafızayı güncelle (aynı key varsa üzerine yaz)
        updated = {m["key"]: m for m in current_memories}
        for nm in new_memories:
            updated[nm["key"]] = nm
        final_memories = list(updated.values())

        # Supabase'e kaydet (REST API ile)
        import urllib.request
        data = json.dumps({"memories": final_memories}).encode("utf-8")
        req = urllib.request.Request(
            f"{supabase_url}/rest/v1/profiles?user_id=eq.{user_id}",
            data=data,
            method="PATCH",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
        )
        resp = urllib.request.urlopen(req, timeout=5)
        logger.info(f"Hafiza guncellendi: user_id={user_id}, yeni_bilgi={len(new_memories)}, http={resp.status}")

    except Exception as e:
        logger.error(f"Hafiza extraction hatasi: {type(e).__name__}: {e}")


RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
SMTP_HOST = "smtp.resend.com"
SMTP_PORT = 465
SMTP_USER = "resend"
SMTP_PASS = os.environ.get("RESEND_API_KEY")  # Resend SMTP şifresi API key'dir


def send_welcome_email(name: str, email: str):
    """Yeni kullanıcıya hoşgeldin emaili gönder."""
    if not SMTP_PASS:
        logger.warning("RESEND_API_KEY tanımlı değil, hoşgeldin emaili gönderilemiyor.")
        return

    import smtplib
    import ssl
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    first_name = name.split()[0] if name else "Sevgili anne"

    html_content = f"""
    <!DOCTYPE html>
    <html lang="tr">
    <head><meta charset="UTF-8"></head>
    <body style="font-family: -apple-system, sans-serif; background: #fff9f5; margin: 0; padding: 0;">
      <div style="max-width: 560px; margin: 40px auto; background: white; border-radius: 16px; overflow: hidden; box-shadow: 0 2px 12px rgba(0,0,0,0.08);">
        <div style="background: #FAEEDA; padding: 32px; text-align: center;">
          <h1 style="font-size: 28px; font-weight: 800; color: #173404; margin: 0;">kucak</h1>
          <p style="color: #854F0B; margin: 8px 0 0; font-size: 14px;">Seni de bebeğini de kucaklayan uzman.</p>
        </div>
        <div style="padding: 32px;">
          <h2 style="color: #173404; font-size: 20px;">Hoş geldin, {first_name}! 🤱</h2>
          <p style="color: #412402; line-height: 1.7;">Kucak ailesine katıldığın için çok mutluyuz. Artık hamilelik ve bebeğinle ilgili her beslenme sorusunu bana sorabilirsin — 7/24 buradayım.</p>
          <div style="background: #EAF3DE; border-radius: 12px; padding: 20px; margin: 24px 0;">
            <h3 style="color: #27500A; font-size: 16px; margin: 0 0 12px;">Başlamak için birkaç ipucu:</h3>
            <p style="color: #173404; margin: 8px 0; font-size: 14px;">✓ Hamilelik haftanı veya bebeğinin yaşını söyle — sana özel cevap vereyim.</p>
            <p style="color: #173404; margin: 8px 0; font-size: 14px;">✓ Yemek tarifleri, takviye soruları, ek gıda rehberliği — her şeyi sorabilirsin.</p>
            <p style="color: #173404; margin: 8px 0; font-size: 14px;">✓ Sohbetlerimizi hatırlıyorum — her seferinde sıfırdan başlamana gerek yok.</p>
          </div>
          <p style="color: #412402; line-height: 1.7;">İlk sorunla başlamaya hazır mısın? Uygulamayı aç ve yaz! 💬</p>
          <p style="color: #854F0B; font-size: 13px; margin-top: 32px;">Soruların için: <a href="mailto:destek@kucak.app" style="color: #c2607a;">destek@kucak.app</a></p>
        </div>
        <div style="background: #FAEEDA; padding: 16px; text-align: center;">
          <p style="color: #854F0B; font-size: 12px; margin: 0;">© 2025 Kucak · <a href="https://osmdmr993.github.io/kucak-privacy/privacy-policy.html" style="color: #854F0B;">Gizlilik Politikası</a></p>
        </div>
      </div>
    </body>
    </html>
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Hoş geldin, {first_name}! 🤱"
        msg["From"] = "Kucak <noreply@kucak.app>"
        msg["To"] = email
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail("noreply@kucak.app", email, msg.as_string())

        logger.info(f"Hoşgeldin emaili gönderildi: {email}")
    except Exception as e:
        logger.warning(f"Hoşgeldin emaili gönderilemedi: {e}")


@app.post("/webhook/revenuecat")
async def revenuecat_webhook(request: Request):
    """RevenueCat webhook — deneme başlangıcı ve iptal olaylarını işle."""
    try:
        body = await request.json()
        event = body.get("event", {})
        event_type = event.get("type", "")
        app_user_id = event.get("app_user_id", "")

        logger.info(f"RevenueCat webhook: {event_type} — user: {app_user_id}")

        supabase_url = os.environ.get("SUPABASE_URL")
        supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")

        if event_type == "INITIAL_PURCHASE" and app_user_id:
            # Deneme başlangıç tarihini kaydet
            import threading
            def save_trial():
                try:
                    from datetime import datetime, timezone
                    now = datetime.now(timezone.utc).isoformat()
                    req = urllib.request.Request(
                        f"{supabase_url}/rest/v1/profiles?user_id=eq.{app_user_id}",
                        data=json.dumps({"trial_started_at": now}).encode("utf-8"),
                        method="PATCH",
                        headers={
                            "apikey": supabase_key,
                            "Authorization": f"Bearer {supabase_key}",
                            "Content-Type": "application/json",
                            "Prefer": "return=minimal",
                        },
                    )
                    urllib.request.urlopen(req, timeout=10)
                    logger.info(f"Trial başlangıcı kaydedildi: {app_user_id}")
                except Exception as e:
                    logger.error(f"Trial kayıt hatası: {e}")
            threading.Thread(target=save_trial, daemon=True).start()

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Webhook hatası: {e}")
        return {"status": "error"}


@app.get("/")
def health_check():
    return {"status": "ok", "service": "kucak-api"}


@app.post("/profile/welcome")
def profile_welcome(data: dict):
    """Profil tamamlanınca hoşgeldin emaili gönder."""
    name = data.get("name", "")
    email = data.get("email", "")
    if name and email:
        import threading
        threading.Thread(
            target=send_welcome_email,
            args=(name, email),
            daemon=True,
        ).start()
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    if client is None:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY tanimli degil.")

    system = SYSTEM_PROMPT + build_profile_block(request.profile)

    messages = [{"role": m.role, "content": m.content} for m in request.conversation_history]
    # Mesajı oluştur — fotoğraf varsa image içerikli mesaj, yoksa text
    if request.image_base64:
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": request.image_base64,
                    },
                },
                {
                    "type": "text",
                    "text": request.message,
                },
            ],
        })
    else:
        messages.append({"role": "user", "content": request.message})

    try:
        response = client.beta.prompt_caching.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=messages,
            tools=[RESPOND_TOOL],
            tool_choice={"type": "tool", "name": "respond_to_mother"},
        )
    except APIError as e:
        logger.error(f"Anthropic API hatasi: {e}")
        raise HTTPException(status_code=502, detail=f"AI servisinden cevap alinamadi: {e}")

    tool_use_block = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use_block is None:
        raise HTTPException(status_code=502, detail="Model yapilandirilmis bir cevap uretmedi.")

    data = tool_use_block.input
    ai_answer = data.get("answer_text", "")

    # Arka planda hafıza çıkar (ana cevabı bloke etmez)
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
    current_memories = request.profile.memories if request.profile and request.profile.memories else []
    user_id = request.profile.user_id if request.profile else None

    import threading
    threading.Thread(
        target=extract_memories_background,
        args=(request.message, ai_answer, current_memories, user_id, supabase_url, supabase_key),
        daemon=True,
    ).start()

    return ChatResponse(
        answer=ai_answer,
        quick_replies=data.get("quick_replies", []),
        safety_flag=data.get("safety_flag", "normal"),
        topic_category=data.get("topic_category", "genel"),
    )


@app.post("/referral/generate")
def generate_referral(data: dict):
    """Kullanıcı için referral kodu oluştur."""
    user_id = data.get("user_id")
    name = data.get("name", "user")
    
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id gerekli")
    
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
    
    try:
        # Mevcut kod var mı kontrol et
        req = urllib.request.Request(
            f"{supabase_url}/rest/v1/profiles?user_id=eq.{user_id}&select=referral_code",
            method="GET",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
            },
        )
        res = urllib.request.urlopen(req, timeout=10)
        profiles = json.loads(res.read())
        
        if profiles and profiles[0].get("referral_code"):
            return {"referral_code": profiles[0]["referral_code"]}
        
        # Yeni kod oluştur
        name_part = ''.join(filter(str.isalpha, name)).upper()[:4].ljust(4, 'K')
        import random
        code = f"{name_part}{random.randint(1000, 9999)}"
        
        # Kaydet
        req = urllib.request.Request(
            f"{supabase_url}/rest/v1/profiles?user_id=eq.{user_id}",
            data=json.dumps({"referral_code": code}).encode("utf-8"),
            method="PATCH",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
            },
        )
        urllib.request.urlopen(req, timeout=10)
        
        return {"referral_code": code}
    except Exception as e:
        logger.error(f"Referral kodu oluşturulamadı: {e}")
        raise HTTPException(status_code=500, detail="Referral kodu oluşturulamadı")


@app.post("/referral/apply")
def apply_referral(data: dict):
    """Referral kodunu uygula — her iki kullanıcıya da bonus ekle."""
    user_id = data.get("user_id")
    code = data.get("code", "").strip().upper()
    
    if not user_id or not code:
        raise HTTPException(status_code=400, detail="user_id ve code gerekli")
    
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
    
    try:
        # Referral kodunu bul
        req = urllib.request.Request(
            f"{supabase_url}/rest/v1/profiles?referral_code=eq.{code}&select=user_id,bonus_days",
            method="GET",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
            },
        )
        res = urllib.request.urlopen(req, timeout=10)
        referrers = json.loads(res.read())
        
        if not referrers:
            return {"status": "not_found", "message": "Geçersiz referral kodu"}
        
        referrer = referrers[0]
        referrer_id = referrer["user_id"]
        
        if referrer_id == user_id:
            return {"status": "self_referral", "message": "Kendi kodunu kullanamazsın"}
        
        # Kendi zaten kullanmış mı kontrol et
        req = urllib.request.Request(
            f"{supabase_url}/rest/v1/profiles?user_id=eq.{user_id}&select=referred_by",
            method="GET",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
            },
        )
        res = urllib.request.urlopen(req, timeout=10)
        my_profile = json.loads(res.read())
        
        if my_profile and my_profile[0].get("referred_by"):
            return {"status": "already_used", "message": "Zaten bir referral kodu kullandın"}
        
        # Yeni kullanıcıya +3 gün bonus
        req = urllib.request.Request(
            f"{supabase_url}/rest/v1/profiles?user_id=eq.{user_id}",
            data=json.dumps({"referred_by": code, "bonus_days": 3}).encode("utf-8"),
            method="PATCH",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
            },
        )
        urllib.request.urlopen(req, timeout=10)
        
        # Referrer'a +7 gün bonus
        new_bonus = (referrer.get("bonus_days") or 0) + 7
        req = urllib.request.Request(
            f"{supabase_url}/rest/v1/profiles?user_id=eq.{referrer_id}",
            data=json.dumps({"bonus_days": new_bonus}).encode("utf-8"),
            method="PATCH",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
            },
        )
        urllib.request.urlopen(req, timeout=10)
        
        # Referrals tablosuna kaydet
        req = urllib.request.Request(
            f"{supabase_url}/rest/v1/referrals",
            data=json.dumps({
                "referrer_user_id": referrer_id,
                "referred_user_id": user_id,
            }).encode("utf-8"),
            method="POST",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
            },
        )
        urllib.request.urlopen(req, timeout=10)
        
        logger.info(f"Referral uygulandı: {code} → {user_id}, referrer: {referrer_id}")
        return {"status": "success", "message": "Referral kodu uygulandı! +3 gün bonus kazandın.", "bonus_days": 3}
    
    except Exception as e:
        logger.error(f"Referral uygulanamadı: {e}")
        raise HTTPException(status_code=500, detail="Referral uygulanamadı")
