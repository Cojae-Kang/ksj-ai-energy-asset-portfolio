"""Vol.1 Exhibit 그래프 (matplotlib). 이미지 안에 'Exhibit N' + 결론형 제목 + 하단 출처 한 줄을 포함한다.

저장: research/vol01/exhibits/exhibit{N}_{kr|en}.png (200dpi) + .svg
"""
from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Mapping

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from .data import Exhibit1, Exhibit2, Exhibit3, Exhibit4  # noqa: E402
from .text import ExhibitText  # noqa: E402

FIG_W = 7.2           # inch (A4 본문 폭 ≈ 170mm에 맞춤)
DPI = 200
# 변형별 (그림 폭 inch, 높이 배율, 파일명 접미사). 캐러셀은 폭을 줄여 휴대폰에서 글자가 약 1.3배 크게 보이게 한다.
VARIANTS = {"note": (FIG_W, 1.0, ""), "carousel": (5.6, 1.12, "_carousel")}


# ---------------------------------------------------------------------------
# 공통 레이아웃
# ---------------------------------------------------------------------------
def _width_units(s: str) -> float:
    return sum(2.0 if unicodedata.east_asian_width(ch) in ("W", "F") else 1.05 for ch in s)


def wrap(text: str, max_units: float) -> list[str]:
    """한글 폭(2)·영문 폭(≈1)을 고려한 단어 단위 줄바꿈."""
    lines, cur = [], ""
    for word in text.split(" "):
        cand = f"{cur} {word}".strip()
        if cur and _width_units(cand) > max_units:
            lines.append(cur)
            cur = word
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


class ExhibitFigure:
    """헤더(Exhibit N + 제목)와 푸터(출처)를 갖춘 그림. axes 영역은 rect로 받는다."""

    def __init__(self, et: ExhibitText, colors: Mapping, height: float = 4.3, variant: str = "note"):
        self.colors = colors
        fig_w, h_scale, self.suffix = VARIANTS[variant]
        self.title_lines = wrap(et.title, 84 * fig_w / FIG_W)
        head_in = 0.30 + 0.245 * len(self.title_lines) + 0.12
        foot_in = 0.34 + (0.14 if variant == "carousel" else 0)
        self.fig = plt.figure(figsize=(fig_w, height * h_scale + 0.245 * (len(self.title_lines) - 1)))
        H = self.fig.get_figheight()
        self.top = 1 - head_in / H
        self.bottom = foot_in / H
        f = self.fig
        f.text(0.012, 1 - 0.13 / H, et.label.upper(), color=colors["teal"], fontsize=8.5, fontweight="bold",
               va="top", ha="left")
        f.add_artist(plt.Line2D([0.012, 0.988], [1 - 0.30 / H + 0.04 / H] * 2, color=colors["teal"], lw=1.2,
                                transform=f.transFigure))
        for i, line in enumerate(self.title_lines):
            f.text(0.012, 1 - (0.36 + 0.245 * i) / H, line, color=colors["navy"], fontsize=11.5, fontweight="bold",
                   va="top", ha="left")
        f.add_artist(plt.Line2D([0.012, 0.988], [self.bottom - 0.04 / H] * 2, color=colors["light_grey"], lw=0.8,
                                transform=f.transFigure))
        for i, line in enumerate(reversed(wrap(et.source, 150 * fig_w / FIG_W))):
            f.text(0.012, (0.10 + 0.14 * i) / H, line, color=colors["grey"], fontsize=7.2, va="bottom", ha="left")

    def axes(self, left=0.09, right=0.97, pad_top=0.06, pad_bottom=0.10):
        ax = self.fig.add_axes([left, self.bottom + pad_bottom, right - left, self.top - self.bottom - pad_top - pad_bottom])
        style_axes(ax, self.colors)
        return ax

    def save(self, out_dir: Path, stem: str) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        stem += self.suffix
        if self.suffix:                        # 캐러셀용은 하위 폴더, PNG만
            out_dir = out_dir / "carousel"
            out_dir.mkdir(parents=True, exist_ok=True)
            self.fig.savefig(out_dir / f"{stem}.png", dpi=DPI, facecolor="white")
            plt.close(self.fig)
            return [out_dir / f"{stem}.png", None]
        paths = [out_dir / f"{stem}.png", out_dir / f"{stem}.svg"]
        self.fig.savefig(paths[0], dpi=DPI, facecolor="white")
        self.fig.savefig(paths[1], facecolor="white")
        plt.close(self.fig)
        return paths


def style_axes(ax, c: Mapping) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(c["light_grey"])
    ax.tick_params(colors=c["navy"], labelsize=8.5, length=0)
    ax.yaxis.label.set_color(c["navy"])
    ax.xaxis.label.set_color(c["navy"])
    ax.grid(axis="y", color=c["light_grey"], lw=0.6, alpha=0.8)
    ax.set_axisbelow(True)


# ---------------------------------------------------------------------------
# Exhibit 1~4
# ---------------------------------------------------------------------------
def exhibit1(e: Exhibit1, et: ExhibitText, c: Mapping, lang: str, out: Path, variant: str = "note") -> list[Path]:
    xf = ExhibitFigure(et, c, variant=variant)
    ax = xf.axes()
    colors = [c["navy"]] + [c["teal"]] * (len(e.values_twh) - 1)
    bars = ax.bar(e.labels, e.values_twh, color=colors, width=0.55)
    top = max(e.values_twh)
    for b, v in zip(bars, e.values_twh):
        ax.text(b.get_x() + b.get_width() / 2, v + top * 0.02, f"{v:,.0f} TWh", ha="center", va="bottom",
                color=c["navy"], fontsize=9, fontweight="bold")
    for b, m in zip(bars[1:], [e.multiple_2030, e.multiple_2035]):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() / 2, f"×{m:.1f}", ha="center", va="center",
                color="white", fontsize=11, fontweight="bold")
    ax.set_ylim(0, top * 1.18)
    ax.set_ylabel("TWh")
    note = {"kr": "2024년 대비 배수 · 2030E/2035E = IEA 기준 시나리오", "en": "Multiple vs 2024 · 2030E/2035E = IEA Base Case"}[lang]
    ax.text(0.0, 1.02, note, transform=ax.transAxes, fontsize=7.5, color=c["grey"])
    return xf.save(out, f"exhibit1_{lang}")


def exhibit2(e: Exhibit2, et: ExhibitText, c: Mapping, lang: str, out: Path, variant: str = "note") -> list[Path]:
    xf = ExhibitFigure(et, c, variant=variant)
    ax = xf.axes(left=0.34 if variant == "carousel" else 0.30, right=0.92)
    labels = {"kr": ["전 세계 전력 수요", "데이터센터 전력 수요", "AI 데이터센터 전력 수요"],
              "en": ["Global electricity demand", "Data-centre demand", "AI data-centre demand"]}[lang]
    vals = [e.global_, e.dc, e.ai_dc]
    bars = ax.barh(labels, vals, color=[c["light_grey"], c["navy"], c["teal"]], height=0.55)
    for b, v in zip(bars, vals):
        ax.text(v + max(vals) * 0.015, b.get_y() + b.get_height() / 2, f"{v:.0f}%", va="center",
                color=c["navy"], fontsize=10, fontweight="bold")
    ax.set_xlim(0, max(vals) * 1.15)
    ax.grid(axis="x", color=c["light_grey"], lw=0.6)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel({"kr": "2025년 전년 대비 증가율 (%)", "en": "2025 growth, year on year (%)"}[lang], fontsize=8.5)
    return xf.save(out, f"exhibit2_{lang}")


def exhibit3(e: Exhibit3, et: ExhibitText, c: Mapping, lang: str, out: Path, variant: str = "note") -> list[Path]:
    xf = ExhibitFigure(et, c, variant=variant)
    ax = xf.axes(left=0.11 if variant == "carousel" else 0.09, right=0.84 if variant == "carousel" else 0.88)
    d = e.index
    names = {"kr": {"VA": "버지니아", "US": "미국 전체"}, "en": {"VA": "Virginia", "US": "U.S. total"}}[lang]
    ax.axhline(100, color=c["grey"], lw=0.8, ls="--")
    ax.plot(d["period"], d["US"], color=c["navy"], lw=1.8, marker="o", ms=3)
    ax.plot(d["period"], d["VA"], color=c["teal"], lw=2.6, marker="o", ms=3.5)
    last = d.iloc[-1]
    for col, color in (("VA", c["teal"]), ("US", c["navy"])):
        ax.annotate(f"{names[col]} {last[col]:.0f}", (last["period"], last[col]), xytext=(6, 0),
                    textcoords="offset points", va="center", color=color, fontsize=9, fontweight="bold",
                    annotation_clip=False)
    ax.set_ylabel({"kr": f"지수 ({e.base_year}=100)", "en": f"Index ({e.base_year}=100)"}[lang])
    ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
    lo, hi = float(d[["VA", "US"]].min().min()), float(d[["VA", "US"]].max().max())
    pad = (hi - lo) * 0.12 or 5
    ax.set_ylim(lo - pad, hi + pad)
    note = {"kr": "상업용(commercial) 부문 전력 소매판매량, 연간", "en": "Commercial-sector electricity retail sales, annual"}[lang]
    ax.text(0.0, 1.02, note, transform=ax.transAxes, fontsize=7.5, color=c["grey"])
    return xf.save(out, f"exhibit3_{lang}")


def exhibit4(e: Exhibit4, et: ExhibitText, c: Mapping, lang: str, out: Path, variant: str = "note") -> list[Path]:
    xf = ExhibitFigure(et, c, height=4.5, variant=variant)
    ax = xf.axes(left=0.32 if variant == "carousel" else 0.27, right=0.88)
    t = e.table.iloc[::-1].reset_index(drop=True)
    names = t["company"] if lang == "kr" else t["company_en"]
    y = range(len(t))
    h = 0.36
    ax.barh([i + h / 2 for i in y], t["mcap_t0"], height=h, color=c["light_grey"], label=e.t0)
    ax.barh([i - h / 2 for i in y], t["mcap_t1"], height=h, color=c["teal"], label=e.t1)
    xmax = float(t[["mcap_t0", "mcap_t1"]].max().max())
    for i, r in t.iterrows():
        ax.text(r["mcap_t1"] + xmax * 0.012, i - h / 2, f"×{r['multiple']:.1f}", va="center", color=c["teal"],
                fontsize=9.5, fontweight="bold")
    ax.set_yticks(list(y))
    ax.set_yticklabels(names)
    ax.set_xlim(0, xmax * 1.14)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_xlabel({"kr": "시가총액 (KRW 억원)", "en": "Market cap (KRW 100mn)"}[lang], fontsize=8.5)
    ax.grid(axis="x", color=c["light_grey"], lw=0.6)
    ax.grid(axis="y", visible=False)
    ax.legend(frameon=False, fontsize=8, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, labelcolor=c["navy"],
              handlelength=1.2, borderaxespad=0.2)
    return xf.save(out, f"exhibit4_{lang}")


# ---------------------------------------------------------------------------
# Exhibit 5: 파이프라인 구조도
# ---------------------------------------------------------------------------
def exhibit5(et: ExhibitText, sources: list[dict], n_tests: int, c: Mapping, lang: str, out: Path,
             variant: str = "note") -> list[Path]:
    xf = ExhibitFigure(et, c, height=4.6, variant=variant)
    big = variant == "carousel"
    ax = xf.fig.add_axes([0.012, xf.bottom + 0.02, 0.976, xf.top - xf.bottom - 0.04])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    kr = lang == "kr"

    fs_title, fs_line = (8.0, 6.6) if big else (8.6, 7.1)

    def box(x, y, w, h, title, lines=(), ok=True, fill="white", title_color=None, compact=False):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.2",
                                    fc=fill, ec=c["teal"] if ok else c["grey"], lw=1.3 if ok else 1.0,
                                    ls="-" if ok else (0, (3, 2))))
        color = c["navy"] if ok else c["grey"]
        if compact:   # 출처 상자: 제목·한 줄 설명을 상자 안 위/아래 절반에 배치
            ax.text(x + 1.5, y + h * 0.70, title, va="center", ha="left", fontsize=fs_title, fontweight="bold",
                    color=title_color or color)
            ax.text(x + 1.5, y + h * 0.27, lines[0], va="center", ha="left", fontsize=fs_line - 0.4, color=color)
            return
        ax.text(x + 1.5, y + h - 2.2, title, va="top", ha="left", fontsize=fs_title, fontweight="bold",
                color=title_color or color)
        for i, ln in enumerate(lines):
            ax.text(x + 1.5, y + h - 9.2 - i * 6.6, ln, va="top", ha="left", fontsize=fs_line, color=color)

    def arrow(x0, x1, y):
        ax.add_patch(FancyArrowPatch((x0, y), (x1, y), arrowstyle="-|>", mutation_scale=12, color=c["teal"], lw=1.4))

    # 1) 공식 출처 6곳
    ax.text(0.5, 99, "공식 출처" if kr else "Official sources", fontsize=8, color=c["grey"], va="top")
    n = len(sources)
    h, gap, y0 = 12.2, 2.6, 92
    for i, s in enumerate(sources):
        y = y0 - (i + 1) * h - i * gap
        status = s["status_kr"] if kr else s["status_en"]
        label = (s["org_kr"] if kr else s["org_en"])
        box(1, y, 29 if big else 27, h, label, [f"{s['use_kr'] if kr else s['use_en']} · {status}"], ok=s["ok"],
            compact=True)
    mid = y0 - (n * h + (n - 1) * gap) / 2
    ax.text(1, 0.5, "+ IEA 보고서 수치: 수기 입력 (출처 URL·발표월 기록)" if kr else
            "+ IEA report figures: manual entry (source URL and month recorded)", fontsize=6.8, color=c["grey"])

    # 2) 자동 수집 → 3) 검증 → 4) 리포트
    stages = [
        ("자동 수집" if kr else "Automated collection",
         (["재시도·타임아웃·캐시", "요청 속도 제한", "원본마다 .meta.json", "(출처·기준일 기록)", "API 키 로그 마스킹"] if kr else
          ["Retries, timeouts", "Rate limiting, cache", ".meta.json per file", "(source, as-of)", "API keys masked"])),
        ("검증" if kr else "Validation",
         (["식별자 검증", "(DART·SEC)", "보조 소스 교차검증", "단위·환율 검산", f"테스트 함수 {n_tests}개"] if kr else
          ["ID checks", "(DART, SEC)", "Cross-check vs", "secondary sources", f"{n_tests} test functions"])),
        ("리포트" if kr else "Report",
         (["Exhibit PNG·SVG", "국문·영문 PDF", "LinkedIn 캐러셀", "결론형 제목 자동 생성", "데이터 없으면 '확인 중'"] if kr else
          ["Exhibits (PNG, SVG)", "KR & EN PDFs", "LinkedIn carousel", "Data-driven titles", "Gaps flagged"])),
    ]
    xs, w, sh = ([38, 59, 80], 18.5, 56) if big else ([35, 56.5, 78], 18.5, 52)
    sy = mid - sh / 2
    arrow(30.5 if big else 29.5, xs[0] - 0.8, mid)
    for i, (title, lines) in enumerate(stages):
        box(xs[i], sy, w, sh, title, lines, fill=c["teal_tint"] if i == 2 else "white", title_color=c["teal"])
        if i < 2:
            arrow(xs[i] + w + 0.4, xs[i + 1] - 0.6, mid)
    cmd = ("python -m src.data_fetch.fetch_all\n→ python -m research.vol01.build" if big else
           "python -m src.data_fetch.fetch_all  →  python -m research.vol01.build")
    ax.text(xs[0], sy - 4, cmd, fontsize=6.6 if big else 7.2, color=c["navy"], family="monospace", va="top",
            linespacing=1.5)
    return xf.save(out, f"exhibit5_{lang}")
