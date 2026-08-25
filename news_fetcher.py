"""دریافت خبر از فیدهای RSS و استخراج عکس + منبع از صفحه‌ی خبر"""
import os
import feedparser
import requests
from bs4 import BeautifulSoup


def _get_proxies():
    """اگه تو .env پروکسی تنظیم شده باشه، برای سایت‌های خارجی ازش استفاده می‌کنیم"""
    http_proxy = os.environ.get("HTTP_PROXY")
    https_proxy = os.environ.get("HTTPS_PROXY")
    if not http_proxy and not https_proxy:
        return None
    return {"http": http_proxy, "https": https_proxy}


def _image_from_entry(entry) -> str | None:
    """بعضی فیدها عکس رو مستقیم همراه خبر می‌فرستن (بدون نیاز به باز کردن صفحه)"""
    media_thumb = entry.get("media_thumbnail")
    if media_thumb:
        return media_thumb[0].get("url")

    media_content = entry.get("media_content")
    if media_content:
        for m in media_content:
            if m.get("url"):
                return m["url"]

    for enc in entry.get("enclosures", []):
        if enc.get("type", "").startswith("image") and enc.get("href"):
            return enc["href"]

    # بعضی فیدها عکس رو تو خود توضیحات (summary) به‌صورت تگ <img> می‌ذارن
    summary = entry.get("summary", "")
    if "<img" in summary:
        soup = BeautifulSoup(summary, "html.parser")
        img = soup.find("img", src=True)
        if img:
            return img["src"]

    return None


def fetch_latest_items(feed_urls: list[str], limit: int = 5) -> list[dict]:
    """خبرها رو از همه‌ی فیدها می‌گیره و به‌نوبت (یکی از این منبع، یکی از اون منبع) می‌چینه
    تا وقتی چندتا خبر موفق پیدا شد، فقط از یه منبع نباشه"""
    per_feed = []
    for url in feed_urls:
        parsed = feedparser.parse(url)
        feed_items = []
        for entry in parsed.entries[:limit]:
            feed_items.append({
                "title": entry.get("title", ""),
                "summary": entry.get("summary", ""),
                "link": entry.get("link", ""),
                "source_feed": parsed.feed.get("title", url),
                "feed_image_url": _image_from_entry(entry),  # ممکنه None باشه
            })
        per_feed.append(feed_items)

    items = []
    max_len = max((len(f) for f in per_feed), default=0)
    for i in range(max_len):
        for feed_items in per_feed:
            if i < len(feed_items):
                items.append(feed_items[i])
    return items


BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fa,en-US;q=0.9,en;q=0.8",
}


def get_image_and_source(item: dict, timeout: int = 15) -> dict:
    """اول میره سراغ خودِ صفحه‌ی خبر (og:image صفحه معمولاً کیفیت اصلی/کامل عکسه؛
    عکس تو خود فید RSS اغلب یه تامبنیل کوچیکه). فقط اگه صفحه باز نشد یا
    عکس نداد (مثلاً صفحه‌ی محافظتی/ضدبات مثل ایرنا)، به‌عنوان جایگزین از
    همون عکس کوچیکِ خود فید استفاده می‌کنه تا حداقل خبر رد نشه"""
    try:
        return extract_image_and_source(item["link"], timeout=timeout)
    except Exception as page_error:
        if item.get("feed_image_url"):
            return {
                "image_url": item["feed_image_url"],
                "site_name": item["source_feed"] or item["link"].split("/")[2],
            }
        raise page_error


def extract_image_and_source(article_url: str, timeout: int = 15) -> dict:
    """عکس و منبع رو از صفحه‌ی خبر استخراج می‌کنه؛ چند نوع تگ رو امتحان می‌کنه"""
    resp = requests.get(
        article_url, headers=BROWSER_HEADERS, timeout=timeout, proxies=_get_proxies()
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    def meta(prop, attr="property"):
        tag = soup.find("meta", attrs={attr: prop})
        return tag["content"] if tag and tag.get("content") else None

    image_url = (
        meta("og:image")
        or meta("og:image:secure_url")
        or meta("twitter:image")
        or meta("twitter:image", attr="name")
    )

    if not image_url:
        img_tag = soup.find("img", src=True)
        if img_tag:
            image_url = img_tag["src"]

    site_name = meta("og:site_name") or article_url.split("/")[2]

    if not image_url:
        page_title = soup.title.string.strip() if soup.title and soup.title.string else "(بدون عنوان)"
        raise RuntimeError(
            f"عکس پیدا نشد. عنوان صفحه‌ای که واقعاً دریافت شد: «{page_title}» "
            f"(کد وضعیت: {resp.status_code})"
        )

    return {"image_url": image_url, "site_name": site_name}


def download_image(image_url: str, dest_path: str, timeout: int = 35) -> str:
    last_error = None
    for attempt in range(2):  # یه بار retry اگه سرور کند بود
        try:
            resp = requests.get(
                image_url, headers=BROWSER_HEADERS, timeout=timeout, proxies=_get_proxies()
            )
            resp.raise_for_status()
            with open(dest_path, "wb") as f:
                f.write(resp.content)
            return dest_path
        except requests.exceptions.RequestException as e:
            last_error = e
    raise last_error
