"""テロップ(スーパー)描画 — Pillowで1080 RGBA画像を生成.

背景は透過(アルファ0)。この画像のRGBがFill、アルファがKeyになる。
毎秒1回程度しか更新しない静止テロップなので描画コストは軽微。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# 配布同梱フォント置き場(リポジトリ直下 fonts/)。ここが最優先。
# SIL OFL / IPAライセンス等、再配布可のフォントのみ置くこと(fonts/README.md 参照)。
_BUNDLED_FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"

# 再配布可(OFL/IPA)のフォント。放送・配布のライセンス面で安全なため優先する。
_OFL_CANDIDATES = [
    r"C:\Windows\Fonts\NotoSansJP-Bold.otf",
    r"C:\Windows\Fonts\NotoSansJP-Regular.otf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf",
    "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
]

# 環境依存フォント(EULA要確認)。OFL系が見つからないときのみ使う。
_SYSTEM_CANDIDATES = [
    r"C:\Windows\Fonts\YuGothB.ttc",
    r"C:\Windows\Fonts\YuGothM.ttc",
    r"C:\Windows\Fonts\meiryo.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
    r"C:\Windows\Fonts\BIZ-UDPGothicR.ttc",
]


def bundled_fonts() -> list[str]:
    """fonts/ に置かれた同梱フォント(あれば)を返す."""
    try:
        return sorted(str(p) for p in _BUNDLED_FONT_DIR.iterdir()
                      if p.suffix.lower() in (".ttf", ".otf", ".ttc", ".otc"))
    except Exception:
        return []


def font_candidates() -> list[str]:
    """探索順: 同梱fonts/ → OFL/IPA → 環境依存フォント."""
    return bundled_fonts() + _OFL_CANDIDATES + _SYSTEM_CANDIDATES


@dataclass
class SuperStyle:
    """テロップの見た目設定."""
    font_path: Optional[str] = None      # 明示指定(なければ候補から自動)
    font_size: int = 90
    # 可変フォントのウェイト名(Thin/Light/Regular/Medium/SemiBold/Bold/Black 等)。
    # 同梱の Noto Sans JP VF は可変なのでここで太さを決める。非可変なら無視。
    font_weight: str = "Bold"
    color: tuple[int, int, int] = (255, 255, 255)
    # 水平: 基準点 margin_x に対して文字の left/center/right を合わせる。
    #   left  … 基準点=文字の左端(右へ伸びる)
    #   right … 基準点=文字の右端(左へ伸びる)
    #   center… 基準点=文字の中央
    align_x: str = "left"
    align_y: str = "top"                 # top/center/bottom(margin_y基準)
    margin_x: int = 80                   # 水平の基準位置(px)
    margin_y: int = 60
    # フチ取り(視認性向上。放送テロップの定番)
    stroke_width: int = 4
    stroke_color: tuple[int, int, int] = (0, 0, 0)
    # 座布団(半透明の帯)。alpha=0で無効
    box_alpha: int = 0
    box_color: tuple[int, int, int] = (0, 0, 0)
    box_pad: int = 24


class SuperRenderer:
    """スーパー描画器. render(text)で RGBA numpy 配列(H,W,4)を返す."""

    def __init__(self, width: int = 1920, height: int = 1080,
                 style: SuperStyle | None = None):
        self.width = width
        self.height = height
        self.style = style or SuperStyle()
        self._font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}

    @staticmethod
    def _needs_cjk(text: str) -> bool:
        # ラテン/数字/記号(<0x2E7F)以外(かな・漢字など)を含むか
        return any(ord(c) > 0x2E7F for c in text)

    def _resolve_font_path(self, text: str = "") -> Optional[str]:
        """描画するtextに応じて実際に使うフォントパスを決める.

        ユーザ指定フォントに日本語字形が無く、textが日本語を含む場合は、
        テロップが消えないよう日本語対応の候補フォントへ自動フォールバックする。
        """
        import os
        from .fonts import font_has_japanese

        user = (self.style.font_path
                if self.style.font_path and os.path.exists(self.style.font_path)
                else None)
        need_jp = self._needs_cjk(text)
        # ユーザ指定でOK(日本語不要 or 日本語字形あり)ならそれを使う
        if user and (not need_jp or font_has_japanese(user)):
            return user
        # 日本語が要るのに指定フォントが非対応 → 日本語対応の候補を探す
        if need_jp:
            for p in font_candidates():
                if os.path.exists(p) and font_has_japanese(p):
                    return p
        # それでも無ければ: ユーザ指定 → 存在する最初の候補
        if user:
            return user
        for p in font_candidates():
            if os.path.exists(p):
                return p
        return None

    def _font(self, text: str = "") -> ImageFont.FreeTypeFont:
        path = self._resolve_font_path(text)
        weight = self.style.font_weight or ""
        key = (path or "<default>", self.style.font_size, weight)
        if key in self._font_cache:
            return self._font_cache[key]
        font = None
        # 指定パス → 候補パス の順で、実際に読めるものを採用(消える事故を防ぐ)
        for p in ([path] if path else []) + font_candidates():
            if not p:
                continue
            try:
                import os
                if os.path.exists(p):
                    font = ImageFont.truetype(p, self.style.font_size)
                    break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()
        # 可変フォント(Noto Sans JP VF等)ならウェイトを適用。
        # テロップは既定Boldで太らせる(Regularだと放送で細く見える)。
        if weight:
            try:
                font.set_variation_by_name(weight)
            except Exception:
                pass          # 可変フォントでない/その名前が無い場合は無視
        self._font_cache[key] = font
        return font

    def render(self, text: str) -> np.ndarray:
        """テキストを描画し RGBA(H,W,4) uint8 を返す(背景は透過)."""
        img = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        if text:
            self._draw_text(img, text)
        return np.asarray(img)

    def _draw_text(self, img: Image.Image, text: str) -> None:
        st = self.style
        draw = ImageDraw.Draw(img)
        font = self._font(text)

        # テキスト範囲を測る
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=st.stroke_width)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        # 水平: 基準点 margin_x に文字の左端/中央/右端を合わせる(アンカー相対)
        if st.align_x == "right":
            x = st.margin_x - tw - bbox[0]
        elif st.align_x == "center":
            x = st.margin_x - tw // 2 - bbox[0]
        else:  # left
            x = st.margin_x - bbox[0]
        if st.align_y == "top":
            y = st.margin_y - bbox[1]
        elif st.align_y == "center":
            y = (self.height - th) // 2 - bbox[1]
        else:  # bottom
            y = self.height - th - st.margin_y - bbox[1]

        # 座布団
        if st.box_alpha > 0:
            bx0 = x + bbox[0] - st.box_pad
            by0 = y + bbox[1] - st.box_pad
            bx1 = x + bbox[0] + tw + st.box_pad
            by1 = y + bbox[1] + th + st.box_pad
            draw.rectangle([bx0, by0, bx1, by1],
                           fill=(*st.box_color, st.box_alpha))

        draw.text((x, y), text, font=font, fill=(*st.color, 255),
                  stroke_width=st.stroke_width,
                  stroke_fill=(*st.stroke_color, 255))
