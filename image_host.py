"""آپلود عکس به یه هاست عمومی و پایدار (catbox.moe) برای وقتی که لینک تلگرام
برای بافر قابل‌خوندن نیست. رایگانه و نیازی به کلید/ثبت‌نام نداره."""
import requests

CATBOX_UPLOAD_URL = "https://catbox.moe/user/api.php"


def upload_image(image_path: str, timeout: int = 30) -> str:
    """عکس رو آپلود می‌کنه و یه لینک مستقیم و عمومی (https://files.catbox.moe/...) برمی‌گردونه.
    اگه آپلود شکست بخوره RuntimeError پرتاب می‌کنه."""
    with open(image_path, "rb") as f:
        resp = requests.post(
            CATBOX_UPLOAD_URL,
            data={"reqtype": "fileupload"},
            files={"fileToUpload": f},
            timeout=timeout,
        )
    resp.raise_for_status()
    url = resp.text.strip()
    if not url.startswith("http"):
        raise RuntimeError(f"آپلود عکس به هاست عمومی شکست خورد: {url}")
    return url
