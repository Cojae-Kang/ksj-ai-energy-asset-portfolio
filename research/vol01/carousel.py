"""LinkedIn 캐러셀 PDF: 1080×1350 세로 8장, 국문 본문 + 영문 부제 한 줄."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping
from xml.sax.saxutils import escape

from reportlab.lib import colors as rl_colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

from .fonts import RL_BOLD, RL_REGULAR
from .text import Copy

W, H = 1080, 1350
MX = 60
CW = W - 2 * MX
N_SLIDES = 8


def _c(h):
    return rl_colors.HexColor(h)


def fit_one_line(text: str, font: str, size: float, max_w: float, min_size: float = 18) -> tuple[str, float]:
    """영문 부제를 한 줄에 맞춤: 글자 크기를 줄이고, 그래도 넘치면 말줄임."""
    while size > min_size and stringWidth(text, font, size) > max_w:
        size -= 1
    if stringWidth(text, font, size) > max_w:
        while text and stringWidth(text + "…", font, size) > max_w:
            text = text[:-1]
        text = text.rstrip() + "…"
    return text, size


def first_sentences(text: str, n: int = 2) -> str:
    parts = re.split(r"(?<=[.!?다])\s+", text.strip())
    return " ".join(parts[:n])


class Slides:
    def __init__(self, path: Path, cfg: Mapping, copy: Copy):
        self.c = cfg["research"]["colors"]
        self.brand = cfg["research"]["brand"]
        self.repo = cfg["research"].get("repo_url", "")
        self.copy = copy
        path.parent.mkdir(parents=True, exist_ok=True)
        self.cv = canvas.Canvas(str(path), pagesize=(W, H))
        self.cv.setTitle(f"{copy.title} — LinkedIn carousel")
        self.cv.setAuthor(copy.labels["author"])
        self.n = 0

    def para(self, text: str, size: float, y_top: float, bold=False, color=None, leading=1.38, width=CW,
             x=MX) -> float:
        st = ParagraphStyle("p", fontName=RL_BOLD if bold else RL_REGULAR, fontSize=size, leading=size * leading,
                            textColor=_c(color or self.c["navy"]))
        p = Paragraph(escape(text), st)
        _, h = p.wrap(width, H)
        p.drawOn(self.cv, x, y_top - h)
        return y_top - h

    def frame(self, kicker: str) -> float:
        cv = self.cv
        self.n += 1
        cv.setFillColor(rl_colors.white)
        cv.rect(0, 0, W, H, fill=1, stroke=0)
        cv.setFillColor(_c(self.c["teal"]))
        cv.rect(0, H - 14, W, 14, fill=1, stroke=0)
        cv.setFont(RL_BOLD, 22)
        cv.drawString(MX, H - 70, self.brand)
        cv.setFillColor(_c(self.c["grey"]))
        cv.setFont(RL_REGULAR, 22)
        cv.drawRightString(W - MX, H - 70, f"{self.n} / {N_SLIDES}")
        cv.setStrokeColor(_c(self.c["light_grey"]))
        cv.setLineWidth(1.5)
        cv.line(MX, H - 90, W - MX, H - 90)
        cv.line(MX, 78, W - MX, 78)
        cv.setFont(RL_REGULAR, 18)
        cv.drawString(MX, 46, f"{self.copy.labels['note_no']} · {self.copy.date} · {self.copy.labels['author']}")
        cv.drawRightString(W - MX, 46, "교육·연구 목적 · 투자 권유 아님")
        cv.setFillColor(_c(self.c["teal"]))
        cv.setFont(RL_BOLD, 24)
        cv.drawString(MX, H - 140, kicker)
        return H - 160

    def headline(self, kr: str, en: str, y: float, size: float = 50) -> float:
        y = self.para(kr, size, y, bold=True, leading=1.25)
        en_fit, en_size = fit_one_line(en, RL_REGULAR, 27, CW)
        self.cv.setFillColor(_c(self.c["grey"]))
        self.cv.setFont(RL_REGULAR, en_size)
        self.cv.drawString(MX, y - en_size - 10, en_fit)
        return y - en_size - 34

    def image(self, path: Path | None, y_top: float, max_h: float) -> float:
        if path is None:
            return y_top
        iw, ih = ImageReader(str(path)).getSize()
        w = CW
        h = w * ih / iw
        if h > max_h:
            h, w = max_h, max_h * iw / ih
        self.cv.drawImage(str(path), MX + (CW - w) / 2, y_top - h, width=w, height=h)
        return y_top - h - 24

    def pending(self, label: str, reason: str, y_top: float) -> float:
        cv = self.cv
        cv.setStrokeColor(_c(self.c["grey"]))
        cv.setDash(8, 6)
        cv.roundRect(MX, y_top - 420, CW, 420, 16, stroke=1, fill=0)
        cv.setDash()
        self.para(f"{label} · 데이터 확인 중", 40, y_top - 150, bold=True, color=self.c["grey"], width=CW - 80, x=MX + 40)
        self.para(reason, 24, y_top - 230, color=self.c["grey"], width=CW - 80, x=MX + 40)
        return y_top - 444

    def end(self):
        self.cv.showPage()

    def save(self) -> int:
        self.cv.save()
        return self.n


def build_carousel(path: Path, cfg: Mapping, kr: Copy, en: Copy, imgs: dict[int, Path | None]) -> int:
    s = Slides(path, cfg, kr)
    c = cfg["research"]["colors"]

    # 1. 표지
    y = s.frame("Research Note · Vol.1")
    y = s.para(kr.title, 66, y - 120, bold=True, leading=1.22)
    en_fit, en_size = fit_one_line(en.title, RL_REGULAR, 30, CW)
    s.cv.setFillColor(_c(c["grey"]))
    s.cv.setFont(RL_REGULAR, en_size)
    s.cv.drawString(MX, y - 50, en_fit)
    s.cv.setFillColor(_c(c["teal"]))
    s.cv.rect(MX, y - 120, 120, 8, fill=1, stroke=0)
    y = s.para(f"{kr.date}  ·  {kr.labels['author']}", 30, y - 150) - 90
    for q_kr, q_en in (("Q1. AI 전력 수요는 진짜인가?", "IEA outlook + EIA metered sales"),
                       ("Q2. 시장은 이미 알고 있나?", "KRX market cap + DART earnings")):
        s.cv.setFillColor(_c(c["teal"]))
        s.cv.rect(MX, y - 96, 8, 96, fill=1, stroke=0)
        y2 = s.para(q_kr, 40, y, bold=True, x=MX + 32, width=CW - 32)
        s.cv.setFillColor(_c(c["grey"]))
        s.cv.setFont(RL_REGULAR, 24)
        s.cv.drawString(MX + 32, y2 - 34, q_en)
        y = y2 - 90
    s.para("공식 데이터 6곳으로 확인한 답 →", 30, 200, color=c["teal"], bold=True)
    s.end()

    # 2. Key Takeaways
    y = s.frame("Key Takeaways")
    y = s.headline("세 줄 요약", "Three takeaways in 30 seconds", y)
    for i, (k, ke) in enumerate(zip(kr.takeaways, en.takeaways), 1):
        s.cv.setFillColor(_c(c["teal"]))
        s.cv.setFont(RL_BOLD, 46)
        s.cv.drawString(MX, y - 52, f"{i}")
        y = s.para(k, 31, y - 8, width=CW - 70, x=MX + 70) - 46
    s.end()

    # 3~7. Exhibits
    slides = [
        (1, "수요는 진짜인가 ① 글로벌 전망", "Is demand real? (1) Global outlook — IEA"),
        (2, "수요는 진짜인가 ② 2025년 증가율", "Is demand real? (2) 2025 growth rates — IEA"),
        (3, "현장 데이터: 버지니아 vs 미국", "Ground truth: Virginia vs the U.S. — EIA"),
        (4, "시장은 이미 알고 있나?", "Has the market priced it in? — KRX, DART"),
        (5, "What I built", "Official data → automated pipeline → validated report"),
    ]
    for n, head_kr, head_en in slides:
        et = kr.exhibits[n]
        y = s.frame(et.label)
        y = s.headline(head_kr, head_en, y, size=46)
        if imgs.get(n) is None or et.pending:
            y = s.pending(et.label, et.pending or "", y)
        else:
            y = s.image(imgs[n], y, 720)
        body = kr.table1_sentence if n == 4 and kr.table1_sentence else first_sentences(et.body or "", 2)
        if body:
            s.para(body, 27, y, leading=1.45)
        s.end()

    # 8. 결론
    y = s.frame("Bottom line")
    y = s.headline("결론", "Bottom line — and what comes next in Vol.2", y)
    y = s.para(kr.conclusion, 33, y - 10, leading=1.5) - 40
    s.para("전체 노트(국문·영문 PDF)와 재현 코드: " + s.repo, 25, y, color=c["teal"], bold=True)
    s.para(kr.disclosures[0] + " " + kr.disclosures[1], 20, 230, color=c["grey"], leading=1.45)
    s.end()
    return s.save()
