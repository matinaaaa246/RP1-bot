"""انتشار پست در اینستاگرام از طریق GraphQL API بافر (Buffer)
چون دسترسی مستقیم به Instagram Graph API / فیسبوک از ایران فیلتره، به‌جاش
از بافر که به‌عنوان پارتنر رسمی متا به اینستاگرام وصله استفاده می‌کنیم.

نکته‌ی مهم: بافر عکس رو خودش دانلود نمی‌کنه که ما بفرستیم؛ باید یه آدرس
عمومی و مستقیم (https, بدون نیاز به لاگین) از عکس بهش بدیم تا خودش بگیرتش.
"""
import datetime

import requests

BUFFER_API_URL = "https://api.buffer.com"

CREATE_POST_MUTATION = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess {
      post {
        id
        text
        dueAt
        status
      }
    }
    ... on MutationError {
      message
    }
  }
}
"""


def publish_to_instagram(
    caption: str,
    image_url: str,
    channel_id: str,
    api_key: str,
    delay_seconds: int = 30,
) -> dict:
    """پست رو با همون عکس و کپشنِ تایید‌شده، تقریبا بلافاصله (چند ثانیه بعد،
    چون بافر مود «همین الان» نداره و حداقل باید یه dueAt در آینده‌ی نزدیک بدیم)
    از طریق بافر تو پیج اینستاگرام منتشر می‌کنه.

    image_url باید یه آدرس مستقیم و عمومیِ https باشه (نه فایل لوکال روی
    سرور خودمون)، چون بافر خودش این آدرس رو fetch می‌کنه.

    اگه بافر نتونه پست رو بسازه (کلید اشتباه، channel_id غلط، عکس در
    دسترس نبودن و غیره) یه RuntimeError با متن دقیق خطا پرتاب می‌شه.
    """
    due_at = (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(seconds=delay_seconds)
    ).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    variables = {
        "input": {
            "text": caption,
            "channelId": channel_id,
            "schedulingType": "automatic",
            "mode": "customScheduled",
            "dueAt": due_at,
            "assets": [{"image": {"url": image_url}}],
            # اینستاگرام تو بافر اجباری می‌خواد بدونه پست از نوع «post»ه
            # (در مقابل «story» یا «reel») و اینکه تو فید هم نشون داده بشه،
            # وگرنه خطای فیلد اجباری می‌ده
            "metadata": {
                "instagram": {"type": "post", "shouldShareToFeed": True}
            },
        }
    }

    resp = requests.post(
        BUFFER_API_URL,
        json={"query": CREATE_POST_MUTATION, "variables": variables},
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )

    if not resp.ok:
        raise RuntimeError(f"بافر خطای HTTP داد (کد {resp.status_code}): {resp.text}")

    data = resp.json()

    if data.get("errors"):
        raise RuntimeError(f"خطای GraphQL بافر: {data['errors']}")

    result = data.get("data", {}).get("createPost", {})
    if "message" in result:  # یعنی نوع پاسخ MutationError بوده
        raise RuntimeError(f"بافر نتونست پست رو بسازه: {result['message']}")

    if "post" not in result:
        raise RuntimeError(f"پاسخ غیرمنتظره از بافر: {data}")

    return result["post"]
