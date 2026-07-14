"""テロップ(スーパー)描画 — Pillowで1080 RGBA画像を生成.

背景は透過(アルファ0)。この画像のRGBがFill、アルファがKeyになる。
毎秒1回程度しか更新しない静止テロップなので描画コストは軽微。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# フォント探索候補(Windows/Linux)。先頭から見つかったものを使う。
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\YuGothM.ttc",
    r"C:\Windows\Fonts\YuGothB.ttc",
    r"C:\Windows\Fonts\meiryo.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
    r"C:\Windows\Fonts\BIZ-UDPGothicR.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
]


@dataclass
class SuperStyle:
    """テロップの見た目設定."""
    font_path: Optional[str] = None      # 明示指定(なければ候補から自動)
    font_size: int = 90
    color: tuple[int, int, int] = (255, 255, 255)
    align_x: str = "center"              # left/center/right
    align_y: str = "bottom"              # top/center/bottom
    margin_x: int = 0                    # 基準位置からのオフセット(px)
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

    def _resolve_font_path(self) -> Optional[str]:
        import os
        if self.style.font_path and os.path.exists(self.style.font_path):
            return self.style.font_path
        for p in _FONT_CANDIDATES:
            if os.path.exists(p):
                return p
        return None

    def _font(self) -> ImageFont.FreeTypeFont:
        path = self._resolve_font_path()
        key = (path or "<default>", self.style.font_size)
        if key not in self._font_cache:
            if path:
                self._font_cache[key] = ImageFont.truetype(path, self.style.font_size)
            else:
                # 日本語フォントが見つからない環境向けの最終手段(豆腐になる可能性)
                self._font_cache[key] = ImageFont.load_default()
        return self._font_cache[key]

    def render(self, text: str) -> np.ndarray:
        """テキストを描画し RGBA(H,W,4) uint8 を返す(背景は透過)."""
        img = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        if text:
            self._draw_text(img, text)
        return np.asarray(img)

    def _draw_text(self, img: Image.Image, text: str) -> None:
        st = self.style
        draw = ImageDraw.Draw(img)
        font = self._font()

        # テキスト範囲を測る
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=st.stroke_width)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        # 基準位置(アンカー)を決める
        if st.align_x == "left":
            x = st.margin_x - bbox[0]
        elif st.align_x == "right":
            x = self.width - tw - st.margin_x - bbox[0]
        else:  # center
            x = (self.width - tw) // 2 - bbox[0] + st.margin_x
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
