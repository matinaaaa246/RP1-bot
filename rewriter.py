"""بازنویسی خبر با هوش مصنوعی برای تولید کپشن اینستاگرام (سازگار با اوپن‌ای‌آی)"""
import requests


REWRITE_SYSTEM_PROMPT = (
    "تو یک ویراستار خبری فارسی هستی. متن زیر را کاملا با جملات و ساختار خودت "
    "بازنویسی کن، خلاصه و روان، بدون کپی کردن جمله‌های اصلی، در حد یک کپشن "
    "اینستاگرام (حداکثر ۱۵۰ کلمه) به همراه ۳-۴ هشتگ مرتبط فارسی. فقط متن کپشن "
    "را برگردان، بدون توضیح اضافه."
)


def rewrite_caption(title: str, summary: str, api_key: str, api_url: str, model: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
            {"role": "user", "content": f"عنوان: {title}\nمتن: {summary}"},
        ],
        "temperature": 0.7,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    resp = requests.post(api_url, json=payload, headers=headers, timeout=30)

    if not resp.ok:
        # متن دقیق خطایی که خود سرور هوش مصنوعی برگردونده رو استخراج می‌کنیم
        try:
            detail = resp.json()
        except ValueError:
            detail = resp.text
        raise RuntimeError(
            f"سرور هوش مصنوعی خطا داد (کد {resp.status_code}): {detail}"
        )

    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()