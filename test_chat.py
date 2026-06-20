"""Basit bir test: sunucu çalışırken (uvicorn app.main:app --reload) bunu çalıştır.
Gerçek bir anne sorusu gönderip Kucak'ın gerçek cevabını gösterir."""

import requests
import json

URL = "http://127.0.0.1:8000/chat"

test_message = "Bebeğim 2 aylık, çok gazı oluyor, kaynanam rezene çayı ver dedi, verebilir miyim?"

print(f"Soru: {test_message}\n")

response = requests.post(URL, json={
    "message": test_message,
    "profile": {"baby_age_months": 2}
})

if response.status_code == 200:
    data = response.json()
    print(f"Kucak'ın cevabı:\n{data['answer']}\n")
    print(f"Hızlı yanıtlar: {data['quick_replies']}")
    print(f"Güvenlik seviyesi: {data['safety_flag']}")
    print(f"Konu kategorisi: {data['topic_category']}")
else:
    print(f"Hata ({response.status_code}): {response.text}")
