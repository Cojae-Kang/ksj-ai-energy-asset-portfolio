"""한글 폰트 결정·등록: assets/fonts의 Noto Sans KR(OFL) → Windows 맑은 고딕 → config의 기타 후보."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from src.data_fetch.base import resolve_path

logger = logging.getLogger("research.fonts")

RL_REGULAR, RL_BOLD = "KSJ-Regular", "KSJ-Bold"   # ReportLab 등록 이름


@dataclass
class FontSet:
    regular: Path
    bold: Path
    label: str          # 보고용 이름 (예: "Noto Sans KR (assets/fonts)")


def candidates(cfg: Mapping) -> list[tuple[Path, Path, str]]:
    f = cfg["research"]["fonts"]
    d = resolve_path(f["dir"])
    out = [(d / f["regular"], d / f["bold"], f"Noto Sans KR ({f['dir']})")]
    for reg, bold in f.get("fallbacks", []):
        out.append((Path(reg), Path(bold), Path(reg).stem))
    return out


def resolve_fonts(cfg: Mapping, cands: list[tuple[Path, Path, str]] | None = None) -> FontSet:
    tried = []
    for reg, bold, label in cands or candidates(cfg):
        if reg.exists():
            if not bold.exists():  # 굵은 체가 없으면 보통 체로 대체
                logger.warning("굵은 글꼴 없음(%s) → 보통 글꼴로 대체", bold)
                bold = reg
            if "Noto" not in label:
                logger.warning("Noto Sans KR 없음 → %s로 대체", label)
            return FontSet(reg, bold, label)
        tried.append(str(reg))
    raise FileNotFoundError("한글 폰트를 찾지 못했습니다. assets/fonts/NotoSansKR-Regular.ttf를 확인하거나 "
                            "config research.fonts.fallbacks에 경로를 추가하세요. 시도: " + ", ".join(tried))


def register_matplotlib(fs: FontSet) -> str:
    import matplotlib
    from matplotlib import font_manager

    for p in {fs.regular, fs.bold}:
        font_manager.fontManager.addfont(str(p))
    family = font_manager.FontProperties(fname=str(fs.regular)).get_name()
    matplotlib.rcParams.update({"font.family": family, "axes.unicode_minus": False,
                                "svg.fonttype": "path", "pdf.fonttype": 42})
    return family


def register_reportlab(fs: FontSet) -> tuple[str, str]:
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    pdfmetrics.registerFont(TTFont(RL_REGULAR, str(fs.regular)))
    pdfmetrics.registerFont(TTFont(RL_BOLD, str(fs.bold)))
    addMapping(RL_REGULAR, 0, 0, RL_REGULAR)
    addMapping(RL_REGULAR, 1, 0, RL_BOLD)
    addMapping(RL_REGULAR, 0, 1, RL_REGULAR)
    addMapping(RL_REGULAR, 1, 1, RL_BOLD)
    return RL_REGULAR, RL_BOLD
