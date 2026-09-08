"""放送用 地図インセット描画（Pillow・完全オフライン）.

同梱の市区町村境界データ（国土数値情報由来）だけを使って、ヘリ現在地の
小さな地図をテロップ画像に重ねるための RGBA 画像を生成する。

ライセンス上の設計要件（docs/LICENSING.md 参照）:
  * 外部の地図サービス・タイルは一切使わない（相手方と通信依存を増やさない）
  * 出典クレジットを **常に** 描画する（オペレーターが消せない）

制御UI（control_ui.py）からは OSC で ON/OFF・位置・大きさ・表示範囲を変更する。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .renderer import font_candidates

# 出典表記。データを地図として公衆送信するため、画面内に必ず出す。
# ここは設定で消せないようにする（消せる作りにしてはいけない）。
#
# 国土数値情報の利用規約（政府標準利用規約準拠版, 令和2年4月1日制定）と
# 国土地理院コンテンツ利用規約（令和7年11月20日改正）はいずれも
# 「出典の記載」に加えて「編集・加工等を行ったこと」の記載を求めているため、
# 両方を満たす文言にしている。
#
# 出典先が2者あるのは、境界形状が国土数値情報(行政区域データ N03)、
# 地名文字列が国土地理院(地理院地図 muni.js 由来の市区町村コード表)のため。
# 詳細は docs/ATTRIBUTION.md / docs/DATA_PROVENANCE.md を参照。
CREDIT_TEXT = "出典:国土数値情報(国土交通省)・国土地理院を加工して作成"


@dataclass
class MapStyle:
    """地図インセットの見た目・配置."""
    on: bool = False              # 既定OFF。明示的にONにしたときだけ放送に出る
    x: int = 1440                 # 左上位置(フレーム座標px)
    y: int = 690
    w: int = 420                  # 大きさ(px)
    h: int = 315
    span: float = 0.30            # 横幅に収める経度[度](小さいほど拡大)
    trail: bool = True            # 軌跡を描く
    opacity: int = 255            # 地図の不透明度(0-255)

    # 配色（放送で視認しやすい濃色ベース）
    bg: tuple = (16, 22, 40)
    land: tuple = (34, 46, 78)
    line: tuple = (74, 92, 140)
    pref: tuple = (110, 200, 255)   # 都道府県境は色を変える
    heli: tuple = (255, 64, 56)
    trailc: tuple = (255, 168, 32)
    frame: tuple = (200, 210, 230)
    credit: tuple = (208, 216, 232)


def _credit_font(size: int) -> ImageFont.FreeTypeFont:
    import os
    for p in font_candidates():
        try:
            if os.path.exists(p):
                f = ImageFont.truetype(p, size)
                try:
                    f.set_variation_by_name("Regular")
                except Exception:
                    pass
                return f
        except Exception:
            continue
    return ImageFont.load_default()


class MapRenderer:
    """境界データからヘリ位置の地図インセットを描く."""

    def __init__(self, lookup=None):
        self._lookup = lookup
        self._failed = False
        self._fonts: dict = {}      # サイズ→フォント(毎回ロードすると重い)

    def _font(self, size: int):
        f = self._fonts.get(size)
        if f is None:
            f = _credit_font(size)
            self._fonts[size] = f
        return f

    def ensure_data(self):
        """境界データを（必要なら）読み込む。失敗時はNoneを返す."""
        if self._lookup is None and not self._failed:
            try:
                from nnn_decoder.geocode import OfflineMuniLookup
                self._lookup = OfflineMuniLookup()
            except Exception:
                self._failed = True
        return self._lookup

    def render(self, lat: float, lon: float, st: MapStyle,
               trail: Optional[list] = None) -> Optional[np.ndarray]:
        """(lat, lon) を中心とした地図を RGBA (h, w, 4) で返す。失敗時 None."""
        lk = self.ensure_data()
        if lk is None or st.w < 40 or st.h < 30:
            return None
        w, h = int(st.w), int(st.h)

        img = Image.new("RGBA", (w, h), (*st.bg, 255))
        d = ImageDraw.Draw(img)

        # --- 投影(中心 lat/lon の等距円筒。緯度で経度方向を補正) ---
        px_lon = w / max(1e-6, st.span)
        px_lat = px_lon / max(0.2, math.cos(math.radians(lat)))

        def proj(lo, la):
            return (w / 2 + (lo - lon) * px_lon,
                    h / 2 - (la - lat) * px_lat)

        half_lon = (w / 2) / px_lon
        half_lat = (h / 2) / px_lat
        m = half_lon * 0.2
        lon0, lat0 = lon - half_lon - m, lat - half_lat - m
        lon1, lat1 = lon + half_lon + m, lat + half_lat + m

        # --- 陸地(市区町村ポリゴン) ---
        try:
            for _cd, rings in lk.geoms_in_view(lon0, lat0, lon1, lat1):
                for xs, ys in rings:
                    if len(xs) < 3:
                        continue
                    pts = [proj(xs[k], ys[k]) for k in range(len(xs))]
                    d.polygon(pts, fill=(*st.land, 255), outline=(*st.line, 255))
        except Exception:
            pass

        # --- 都道府県境(色を変えて上に重ねる) ---
        try:
            for xs, ys in lk.pref_borders_in_view(lon0, lat0, lon1, lat1):
                if len(xs) < 2:
                    continue
                pts = [proj(xs[k], ys[k]) for k in range(len(xs))]
                d.line(pts, fill=(*st.pref, 255), width=2)
        except Exception:
            pass

        # --- 軌跡 ---
        if st.trail and trail and len(trail) >= 2:
            pts = [proj(lo, la) for lo, la in trail]
            d.line(pts, fill=(*st.trailc, 255), width=2)

        # --- 現在位置マーカー ---
        cx, cy = w / 2, h / 2
        r = max(5, min(w, h) // 22)
        d.line([(cx - r * 2, cy), (cx + r * 2, cy)], fill=(*st.heli, 255), width=1)
        d.line([(cx, cy - r * 2), (cx, cy + r * 2)], fill=(*st.heli, 255), width=1)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(*st.heli, 255), width=2)

        # --- 出典クレジット(必須・常時描画) ---
        # 枠幅に収まる最大サイズを選ぶ(小さい地図でも出典が切れないように)
        fs = max(8, int(h * 0.055))
        f = self._font(fs)
        tb = None
        for _ in range(12):
            f = self._font(fs)
            try:
                tb = d.textbbox((0, 0), CREDIT_TEXT, font=f)
            except Exception:
                tb = (0, 0, len(CREDIT_TEXT) * fs // 2, fs)
            if (tb[2] - tb[0]) <= w - 8 or fs <= 8:
                break
            fs -= 1
        th = tb[3] - tb[1]
        pad = 3
        by1 = h - 1
        by0 = by1 - th - pad * 2
        d.rectangle([0, by0, w, by1], fill=(0, 0, 0, 170))
        d.text((pad + 2 - tb[0], by0 + pad - tb[1]), CREDIT_TEXT, font=f,
               fill=(*st.credit, 255))

        # --- 外枠 ---
        d.rectangle([0, 0, w - 1, h - 1], outline=(*st.frame, 255), width=2)

        arr = np.asarray(img).copy()
        if st.opacity < 255:
            a = arr[:, :, 3].astype(np.uint16) * int(st.opacity) // 255
            arr[:, :, 3] = a.astype(np.uint8)
        return arr


def compose(frame: np.ndarray, inset: np.ndarray, x: int, y: int) -> np.ndarray:
    """frame(RGBA) の (x, y) に inset(RGBA) をアルファ合成した新しい配列を返す."""
    if inset is None:
        return frame
    H, W = frame.shape[:2]
    h, w = inset.shape[:2]
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(W, x0 + w), min(H, y0 + h)
    if x1 <= x0 or y1 <= y0:
        return frame
    out = frame.copy()
    sub = inset[: y1 - y0, : x1 - x0].astype(np.float32)
    dst = out[y0:y1, x0:x1].astype(np.float32)
    a = sub[:, :, 3:4] / 255.0
    rgb = sub[:, :, :3] * a + dst[:, :, :3] * (1 - a)
    # アルファは「上に乗せた分」だけ増える(Fill&Keyのキーが抜けないように)
    al = np.maximum(dst[:, :, 3:4], sub[:, :, 3:4])
    out[y0:y1, x0:x1, :3] = rgb.astype(np.uint8)
    out[y0:y1, x0:x1, 3:4] = al.astype(np.uint8)
    return out
