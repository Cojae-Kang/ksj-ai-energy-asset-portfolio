"""Vol.3 차트 (차트 영역만). Vol.1·Vol.2 스타일 도우미를 그대로 쓰고, IPO 전용 차트를 더한다.

각 함수는 (png 경로, 폭 pt, 높이 pt)를 받는 그리기 함수를 돌려준다 → 셀 크기에 맞춰 렌더링.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np

from research.vol01.charts import (FS, Draw, _fig, _save, _style, bars, cover_background, flow4, grouped, hbars,  # noqa: F401
                                   label_frac, plt)
from matplotlib.ticker import FuncFormatter, NullLocator  # noqa: E402


def ranges(rows: Sequence[tuple[str, float, float, float]], c: Mapping, fmt: Callable[[float], str], value_label: str) -> Draw:
    """가정 범위: rows = [(라벨, 피어 최소, 피어 최대, 적용값)]. 범위 막대 + 적용값 골드 마커 (행별 독립 축 비율)."""
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        lf = label_frac([r[0] for r in rows], w, lo=0.18)
        ax = fig.add_axes([lf, 0.08, 0.95 - lf, 0.86])
        for i, (_, lo, hi, v) in enumerate(rows):
            span = max(hi, v) * 1.25 or 1.0          # 행마다 최대값 기준 0~1로 정규화 (단위가 달라도 한 그림)
            ax.barh(i, (hi - lo) / span, left=lo / span, height=0.42, color=c["warm_grey_light"])
            ax.plot([v / span], [i], marker="D", ms=7, color=c["gold"], zorder=5)
            ax.text(lo / span - 0.012, i, fmt(lo), ha="right", va="center", fontsize=FS - 0.2, color=c["note"])
            ax.text(hi / span + 0.012, i, fmt(hi), ha="left", va="center", fontsize=FS - 0.2, color=c["note"])
            ax.text(v / span, i - 0.28, f"{value_label} {fmt(v)}", ha="center", va="bottom", fontsize=FS + 0.6,
                    fontweight="bold", color=c["gold"])
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels([r[0] for r in rows])
        ax.set_ylim(len(rows) - 0.5, -0.8)
        ax.set_xlim(0, 1)
        ax.xaxis.set_major_locator(NullLocator())
        _style(ax, c)
        ax.spines["bottom"].set_visible(False)
        _save(fig, path)
    return draw


def price_ladder(labels: Sequence[str], values: Sequence[float], c: Mapping, fmt: Callable[[float], str],
                 band: tuple[float, float] | None, band_label: str, ref: tuple[float, str] | None = None) -> Draw:
    """할인율별 주당 공모가 막대 + 희망공모가 밴드 음영 + 평가가액 기준선."""
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        ax = fig.add_axes([0.04, 0.12, 0.80, 0.84])
        top = max(list(values) + ([ref[0]] if ref else []))
        cols = [c["gold"] if band and band[0] - 1e-6 <= v <= band[1] + 1e-6 else c["brown_mid"] for v in values]
        b = ax.bar(labels, values, color=cols, width=0.56)
        for bar, v in zip(b, values):
            ax.text(bar.get_x() + bar.get_width() / 2, v + top * 0.02, fmt(v), ha="center", va="bottom",
                    fontsize=FS + 1.0, fontweight="bold", color=c["text"])
        if band:
            ax.axhspan(band[0], band[1], color=c["gold"], alpha=0.16, lw=0)
            ax.text(len(values) - 0.45, (band[0] + band[1]) / 2, band_label, ha="left", va="center", fontsize=FS + 0.4,
                    fontweight="bold", color=c["gold"], clip_on=False)
        if ref:
            ax.axhline(ref[0], color=c["charcoal"], lw=0.9, ls="--")
            ax.text(len(values) - 0.45, ref[0], ref[1], ha="left", va="center", fontsize=FS, color=c["charcoal"], clip_on=False)
        ax.set_ylim(0, top * 1.15)
        ax.yaxis.set_major_locator(NullLocator())
        _style(ax, c)
        _save(fig, path)
    return draw


def histogram(values: np.ndarray, c: Mapping, fmt: Callable[[float], str], marks: Sequence[tuple[float, str, str]],
              band: tuple[float, float] | None, band_label: str, bins: int = 60) -> Draw:
    """1년 후 주당가치 분포: 히스토그램 + 분위 세로선(marks = [(값, 라벨, 색)]) + 밴드 음영."""
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        ax = fig.add_axes([0.04, 0.13, 0.93, 0.80])
        lo, hi = np.quantile(values, [0.002, 0.998])
        ax.hist(np.clip(values, lo, hi), bins=bins, color=c["warm_grey_light"], edgecolor="white", lw=0.3)
        ymax = ax.get_ylim()[1]
        if band:
            ax.axvspan(band[0], band[1], color=c["gold"], alpha=0.22, lw=0)
            ax.text((band[0] + band[1]) / 2, ymax * 1.02, band_label, ha="center", va="bottom", fontsize=FS + 0.6,
                    fontweight="bold", color=c["gold"])
        for k, (v, lab, col) in enumerate(marks):
            ax.axvline(v, color=col, lw=1.1, ls="--" if k != len(marks) - 1 else "-")
            ax.text(v, ymax * (0.92 - 0.11 * (k % 3)), f" {lab} {fmt(v)}", ha="left", va="top", fontsize=FS - 0.2,
                    fontweight="bold", color=col)
        ax.set_ylim(0, ymax * 1.14)
        ax.yaxis.set_major_locator(NullLocator())
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: fmt(v)))
        ax.tick_params(axis="x", labelsize=FS - 0.4, colors=c["note"])
        _style(ax, c)
        _save(fig, path)
    return draw


def price_heat(z: np.ndarray, rows: Sequence[str], cols: Sequence[str], c: Mapping, band: tuple[float, float] | None,
               fmt: Callable[[float], str], xlabel: str, ylabel: str, bold_rows: set[int] | None = None) -> Draw:
    """적용 PER × 할인율 → 주당 공모가. 밴드 안 = 골드, 밴드 위 = 웜그레이, 밴드 아래 = 흰색."""
    def draw(path: Path, w: float, h: float) -> None:
        from matplotlib.colors import to_rgb
        fig = _fig(w, h)
        lf = label_frac(rows, w, lo=0.12, hi=0.34)
        ax = fig.add_axes([lf, 0.13, 0.98 - lf, 0.83])
        img = np.ones((*z.shape, 3))
        gold, grey = np.array(to_rgb(c["gold"])), np.array(to_rgb(c["warm_grey_light"]))
        for i in range(z.shape[0]):
            for j in range(z.shape[1]):
                v = z[i, j]
                inside = band is not None and band[0] - 1e-6 <= v <= band[1] + 1e-6
                above = band is not None and v > band[1]
                img[i, j] = 1 - (1 - gold) * 0.55 if inside else (1 - (1 - grey) * 0.55 if above else (1, 1, 1))
                ax.text(j, i, fmt(v), ha="center", va="center", fontsize=FS + 0.4,
                        fontweight="bold" if inside or (bold_rows and i in bold_rows) else "normal", color=c["text"])
        ax.imshow(img, aspect="auto")
        for i in range(z.shape[0] + 1):
            ax.axhline(i - 0.5, color="white", lw=1.2)
        ax.set_xticks(range(len(cols)))
        ax.set_xticklabels(cols)
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels(rows)
        if bold_rows:
            for i in bold_rows:
                ax.get_yticklabels()[i].set_fontweight("bold")
        ax.set_xlabel(xlabel, fontsize=FS, color=c["note"])
        ax.set_ylabel(ylabel, fontsize=FS, color=c["note"])
        for s in ax.spines.values():
            s.set_visible(False)
        ax.tick_params(colors=c["text"], labelsize=FS, length=0)
        _save(fig, path)
    return draw


def convergence(ns: Sequence[int], series: Sequence[tuple[str, Sequence[float], str]], c: Mapping, fmt: Callable[[float], str]) -> Draw:
    """시뮬레이션 횟수별 P10·P50·P90 (로그 x축)."""
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        ax = fig.add_axes([0.13, 0.14, 0.70, 0.80])
        for name, ys, col in series:
            ax.plot(ns, ys, color=col, lw=1.8, marker="o", ms=3)
            ax.text(ns[-1] * 1.12, ys[-1], f"{name} {fmt(ys[-1])}", va="center", fontsize=FS + 0.2, fontweight="bold",
                    color=col, clip_on=False)
        ax.set_xscale("log")
        ax.xaxis.set_minor_locator(NullLocator())
        ax.set_xticks(list(ns))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: fmt(v)))
        ax.tick_params(axis="both", labelsize=FS - 0.4, colors=c["note"])
        _style(ax, c, grid_y=True)
        _save(fig, path)
    return draw



def export_figure(draw: Draw, stem, title: str, unit: str, foot: str, c: Mapping, dpi: int = 200,
                  w_pt: float = 720.0, h_pt: float = 420.0) -> list:
    """figures/ 단독 그림: 제목 · 단위 · 차트 · 출처 각주 → PNG(dpi) + PDF. 반환: 저장 경로 목록."""
    import textwrap
    from pathlib import Path as _P
    stem = _P(stem)
    stem.parent.mkdir(parents=True, exist_ok=True)
    inner = stem.with_name(stem.name + "_inner.png")
    head, tail = 56.0, 26.0
    draw(inner, w_pt, h_pt - head - tail)
    fig = _fig(w_pt, h_pt)
    fig.patch.set_facecolor("white")
    fig.text(14 / w_pt, 1 - 12 / h_pt, textwrap.fill(title, 70), fontsize=FS + 4, fontweight="bold", color=c["text"], va="top")
    fig.add_artist(plt.Line2D([14 / w_pt, 1 - 14 / w_pt], [1 - 40 / h_pt] * 2, color=c["gold"], lw=1.0))
    if unit:
        fig.text(1 - 14 / w_pt, 1 - 50 / h_pt, unit, fontsize=FS + 0.6, color=c["note"], va="center", ha="right")
    ax = fig.add_axes([0, tail / h_pt, 1, (h_pt - head - tail) / h_pt])
    ax.imshow(plt.imread(inner))
    ax.axis("off")
    fig.text(14 / w_pt, 8 / h_pt, foot, fontsize=FS - 0.4, color=c["note"], va="bottom")
    out = []
    for ext in ("png", "pdf"):
        p = stem.with_suffix(f".{ext}")
        fig.savefig(p, dpi=dpi, facecolor="white")
        out.append(p)
    plt.close(fig)
    inner.unlink(missing_ok=True)
    return out
