"""自分で入れる表紙画像の扱い。

国会図書館に書影が無い本もあるので、手で入れられるようにしてある。
撮った写真をそのまま入れるとDBが膨らむので、**保存する前に縮める**。
"""
import io

from PIL import Image, UnidentifiedImageError

# 受け取るファイルの上限。これを超えたら読まずに断る
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# 保存するときの大きさ。表紙は大きくても 120×176 でしか出さないが、
# あとで拡大表示したくなっても耐えるくらいに残しておく
MAX_SIZE = (600, 900)
JPEG_QUALITY = 82


class InvalidImageError(ValueError):
    """画像として読めなかった"""


def normalize(raw: bytes) -> tuple[bytes, str]:
    """受け取った画像を、縮めた JPEG に揃える。

    戻りは (中身, content-type)。
    透過は白で埋める（表紙に透明部分は要らないし、JPEG は透過を持てない）。
    """
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError) as error:
        raise InvalidImageError("画像として読み取れませんでした") from error

    if image.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        converted = image.convert("RGBA")
        background.paste(converted, mask=converted.split()[-1])
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")

    # 縦横比を保ったまま、収まる大きさまで縮める（元より大きくはしない）
    image.thumbnail(MAX_SIZE, Image.LANCZOS)

    out = io.BytesIO()
    image.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return out.getvalue(), "image/jpeg"
