"""Vol.4 차트 (차트 영역만). Vol.1~3 스타일 도우미를 그대로 쓰고, PPA 전용 차트를 더한다."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np

from research.vol01.charts import (FS, Draw, _fig, _save, _style, bars, cover_background, flow4, grouped, hbars,  # noqa: F401
                                   label_frac, plt)
from research.vol02.charts import tornado, xy  # noqa: F401
from research.vol03.charts import discount_boxes, export_figure  # noqa: F401
from matplotlib.ticker import FuncFormatter, NullLocator  # noqa: E402


def corridor(points: Sequence[tuple[str, float, str]], bands: Sequence[tuple[str, float, float, str, float]], c: Mapping,
             fmt: Callable[[float], str], xlim: tuple[float, float], gap: tuple[float, float, str] | None = None) -> Draw:
    """가격 수직선: points = [(라벨, 값, 색)] 한 줄씩, bands = [(라벨, 시작, 끝, 색, 투명도)] 배경 음영.
    gap = (시작, 끝, 라벨): 두 값 사이 간격 화살표 (예: 협상 여지)."""
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        labels = [p[0] for p in points]
        lf = label_frac(labels, w, lo=0.20)
        ax = fig.add_axes([lf, 0.12, 0.95 - lf, 0.80])
        n = len(points)
        for lab, a, b, col, al in bands:
            ax.axvspan(a, b, color=col, alpha=al, lw=0, zorder=0)
            ax.text((a + b) / 2, -0.85, lab, ha="center", va="bottom", fontsize=FS - 0.2, color=c["note"])
        for i, (lab, v, col) in enumerate(points):
            ax.plot([xlim[0], v], [i, i], color=c["warm_grey_light"], lw=0.8, zorder=1)
            ax.plot([v], [i], marker="o", ms=8, color=col, zorder=3)
            ax.text(v + (xlim[1] - xlim[0]) * 0.015, i, fmt(v), va="center", ha="left", fontsize=FS + 1.4,
                    fontweight="bold", color=col)
        if gap:
            a, b, lab = gap
            y = n - 0.35
            ax.annotate("", xy=(b, y), xytext=(a, y), arrowprops={"arrowstyle": "<->", "color": c["brick"], "lw": 1.2})
            ax.text((a + b) / 2, y + 0.12, lab, ha="center", va="top", fontsize=FS + 0.4, fontweight="bold", color=c["brick"])
        ax.set_yticks(range(n))
        ax.set_yticklabels(labels)
        ax.set_ylim(n + 0.15, -1.0)
        ax.set_xlim(*xlim)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
        ax.tick_params(axis="x", labelsize=FS - 0.4, colors=c["note"])
        _style(ax, c, grid_x=True)
        _save(fig, path)
    return draw


def line_ref(xs: Sequence[float], series: Sequence[tuple[str, Sequence[float | None], str]], c: Mapping,
             xfmt: Callable[[float], str], yfmt: Callable[[float], str], hlines: Sequence[tuple[float, str, str]] = (),
             vlines: Sequence[tuple[float, str, str]] = (), shade: tuple[float, float, str] | None = None) -> Draw:
    """선 그래프 + 수평 기준선(값, 라벨, 색) + 수직 표시선 + x 구간 음영(시작, 끝, 라벨). 라벨은 겹치지 않게 줄을 나눔."""
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        ax = fig.add_axes([0.10, 0.13, 0.80, 0.80])
        ys_all = []
        for name, ys, col in series:
            y = np.array([np.nan if v is None else v for v in ys], float)
            ys_all += list(y[np.isfinite(y)])
            ax.plot(xs, y, color=col, lw=2.0, marker="o", ms=2.6)
            last = np.where(np.isfinite(y))[0]
            if last.size and name:
                ax.text(xs[last[-1]], y[last[-1]], " " + name, va="center", ha="left", fontsize=FS, color=col, clip_on=False)
        ys_all += [hv for hv, _, _ in hlines]
        lo, hi = min(ys_all), max(ys_all)
        pad = (hi - lo) * 0.12 or 0.01
        ax.set_ylim(lo - pad, hi + pad * 2.2)
        if shade:
            ax.axvspan(shade[0], shade[1], color=c["gold"], alpha=0.14, lw=0, zorder=0)
            ax.text((shade[0] + shade[1]) / 2, hi + pad * 1.9, shade[2], ha="center", va="top", fontsize=FS - 0.2,
                    color=c["gold"], fontweight="bold")
        for hv, lab, col in hlines:
            ax.axhline(hv, color=col, lw=0.9, ls="--")
            ax.text(xs[-1], hv, " " + lab, va="center", ha="left", fontsize=FS - 0.2, color=col, fontweight="bold", clip_on=False)
        for k, (vv, lab, col) in enumerate(vlines):
            ax.axvline(vv, color=col, lw=0.9, ls=":")
            ax.text(vv, lo - pad * 0.6 + k * pad * 0.0, " " + lab, va="bottom", ha="left", fontsize=FS - 0.2, color=col,
                    fontweight="bold", bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.6, "alpha": 0.9})
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: xfmt(v)))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: yfmt(v)))
        ax.tick_params(labelsize=FS - 0.4, colors=c["note"])
        _style(ax, c, grid_y=True)
        _save(fig, path)
    return draw


def irr_boxes(series: Sequence[tuple[str, Sequence[float]]], c: Mapping, marks: Sequence[tuple[float, str, str]]) -> Draw:
    """경로별 지분 IRR 분포 상자그림 (Vol.3 discount_boxes 재사용 — 단위 %)."""
    return discount_boxes(series, c, marks)
