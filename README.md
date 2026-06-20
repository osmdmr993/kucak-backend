# Kucak API (v0.1 — ilk iskelet)

Bu, Kucak'ın "beyni" — anneden gelen mesajı alıp, sistem promptumuzla (sistem-promptu-v1.md)
Claude Sonnet 4.6'ya gönderen, yapılandırılmış bir cevap (metin + hızlı yanıt seçenekleri +
güvenlik seviyesi) döndüren basit bir API.

**Henüz YOK (sıradaki adımlar):** RAG/bilgi tabanı (Voyage AI + pgvector), kalıcı kullanıcı
profili (Postgres), kimlik doğrulama, gerçek mobil uygulama. Bu adım sadece "AI çekirdeği
gerçekten çalışıyor mu" sorusuna cevap veriyor.

## Kurulum (5 dakika)

1. **Python 3.11+ kurulu olmalı.** (Bilgisayarında yoksa python.org'dan indir.)
2. Bu klasörde bir terminal aç, şunu çalıştır:
   ```
   pip install -r requirements.txt
   ```
3. `.env.example` dosyasını kopyala, adını `.env` yap. İçindeki `sk-ant-...` kısmını
   kendi gerçek Anthropic API anahtarınla değiştir (console.anthropic.com → API Keys —
   faturalandırma/kredi kartı eklemen gerekiyor, gerçek kullanım gerçek ücretlendiriliyor
   ama tek bir test mesajı bir sentin bile altında).
4. Sunucuyu başlat:
   ```
   uvicorn app.main:app --reload
   ```
5. Tarayıcıda `http://127.0.0.1:8000` adresine gidersen `{"status":"ok"}` görmelisin —
   bu, sunucunun çalıştığını gösterir.

## Test etmek

Terminalde (sunucu çalışırken, başka bir terminal sekmesinde):
```
python test_chat.py
```

Bu, gerçek bir anne sorusu gönderip Kucak'ın gerçek cevabını ekrana yazdıracak.

## Sıradaki adımlar

1. RAG/bilgi tabanı kurulumu (WHO/SB içeriğinin kürasyonu + embedding) — bu bir içerik
   araştırma turu gerektiriyor, sadece kod değil.
2. Expo ile mobil uygulama iskeleti — bu API'yi çağıran gerçek bir sohbet ekranı.
3. Kalıcı kullanıcı profili (Postgres/Supabase).
4. Kimlik doğrulama (Google/Apple sosyal giriş).
