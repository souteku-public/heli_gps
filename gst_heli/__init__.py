"""GStreamerベースのヘリGPSスーパー送出(TouchDesigner不要).

SDIエンベデッド音声(decklinkaudiosrc)からGPSを復調し、
市区町村住所テロップをPillowで描画、Fill&KeyでSDI出力(decklinkvideosink)する。
専用ソフト不要・Python + GStreamer(LGPL) + Blackmagic Desktop Video のみ。
"""

__version__ = "1.0.0"

from .renderer import SuperRenderer

__all__ = ["SuperRenderer"]
