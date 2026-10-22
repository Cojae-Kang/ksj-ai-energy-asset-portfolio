"""Vol.2 차트 (차트 영역만). Vol.1 스타일 도우미를 그대로 쓰고, PF 전용 차트를 더한다.

각 함수는 (png 경로, 폭 pt, 높이 pt)를 받는 그리기 함수를 돌려준다 → 셀 크기에 맞춰 렌더링.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np

from research.vol01.charts import (FS, Draw, _fig, _save, _style, bars, cover_background, flow4, grouped, hbars,  # noqa: F401
                                   label_frac, lines, plt)
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402
from matplotlib.ticker import FuncFormatter, NullLocator  # noqa: E402


# ---------------------------------------------------------------------------
# 사업 구조도
# ---------------------------------------------------------------------------
def structure(nodes: Mapping[str, tuple[str, str]], edges: Sequence[tuple[str, str, str]], c: Mapping) -> Draw:
    """nodes: 키 → (제목, 부제). 위치는 고정 배치(SPC 중심). edges: (from, to, 라벨)."""
    pos = {"sponsor": (50, 88), "spc": (50, 52), "lenders": (12, 52), "tenant": (88, 52),
           "epc": (20, 14), "power": (80, 14), "om": (50, 14), "reserve": (14, 88)}

    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        ax.axis("off")
        bw, bh = 22, 15
        for k, (title, sub) in nodes.items():
            x, y = pos[k]
            main = k == "spc"
            ax.add_patch(FancyBboxPatch((x - bw / 2, y - bh / 2), bw, bh, boxstyle="round,pad=0.4,rounding_size=1.5",
                                        fc=c["charcoal"] if main else (c["panel"] if k in ("lenders", "tenant", "reserve") else "white"),
                                        ec=c["charcoal"] if main else c["gold"], lw=1.2))
            ax.text(x, y + 2.4, title, ha="center", va="center", fontsize=FS + 2.2, fontweight="bold",
                    color=c["gold"] if main else c["brown_dark"])
            ax.text(x, y - 3.4, sub, ha="center", va="center", fontsize=FS - 0.2, color="white" if main else c["text"])
        for a, b, lab in edges:
            (x0, y0), (x1, y1) = pos[a], pos[b]
            dx, dy = x1 - x0, y1 - y0
            # 박스 가장자리에서 시작·끝
            sx = (bw / 2 + 1) / abs(dx) if dx else np.inf
            sy = (bh / 2 + 1) / abs(dy) if dy else np.inf
            s = min(sx, sy)
            p0 = (x0 + dx * s, y0 + dy * s)
            p1 = (x1 - dx * s, y1 - dy * s)
            ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=12, color=c["gold"], lw=1.3,
                                         shrinkA=0, shrinkB=0))
            mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
            ax.text(mx, my + (2.2 if dy == 0 else 0), lab, ha="center", va="bottom" if dy == 0 else "center",
                    fontsize=FS - 0.4, color=c["note"], bbox=dict(fc="white", ec="none", pad=0.6))
        _save(fig, path)
    return draw


def yield_bars(labels: Sequence[str], values: Sequence[float], colors: Sequence[str], c: Mapping,
               fmt: Callable[[float], str], band: tuple[float, float] | None = None, band_label: str = "",
               marks: Sequence[float | None] | None = None, mark_label: str = "") -> Draw:
    """막대(원가 대비 수익률 등, %) + 점검 범위 음영(band) + 막대별 비교 표식(marks, 예: 대출금리)."""
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        ax = fig.add_axes([0.06, 0.14, 0.92, 0.80])
        x = np.arange(len(labels))
        top = max(list(values) + [band[1] if band else 0] + [m for m in (marks or []) if m is not None])
        if band:
            ax.axhspan(band[0], band[1], color=c["gold"], alpha=0.16, lw=0, zorder=0)
            for yv in band:
                ax.axhline(yv, color=c["gold"], lw=0.6, ls=":", zorder=1)
            ax.text(len(labels) - 0.45, band[1], f"{band_label} {fmt(band[0])}~{fmt(band[1])}", ha="right", va="bottom",
                    fontsize=FS - 0.4, color=c["note"])
        b = ax.bar(x, values, color=colors, width=0.5, zorder=2)
        for bar, v in zip(b, values):
            ax.text(bar.get_x() + bar.get_width() / 2, v + top * 0.02, fmt(v), ha="center", va="bottom",
                    fontsize=FS + 1.2, fontweight="bold", color=c["text"], zorder=3)
        if marks:
            for i, m in enumerate(marks):
                if m is None:
                    continue
                ax.plot([i - 0.32, i + 0.32], [m, m], color=c["brick"], lw=1.8, zorder=4)
                ax.text(i + 0.34, m, fmt(m), ha="left", va="center", fontsize=FS - 0.8, color=c["brick"], zorder=4)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=FS - 0.2)
        ax.set_xlim(-0.6, len(labels) - 0.4)
        ax.set_ylim(0, top * 1.2)
        ax.yaxis.set_major_locator(NullLocator())
        _style(ax, c)
        _save(fig, path)
    return draw


def debt_irr_curve(labels: Sequence[str], debt: Sequence[float], irr: Sequence[float], irr_ex: Sequence[float] | None,
                   notes: Sequence[str], c: Mapping, dfmt: Callable[[float], str], names: tuple[str, str, str]) -> Draw:
    """x = 단계(예: 전력비 포함 비율). 막대 = 대출 한도(아래 절반), 선 = Equity IRR %(위 절반), 점선 = 잔존가치 제외 IRR.
    notes = x축 라벨 아래 줄(예: 최소 DSCR)."""
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        ax = fig.add_axes([0.04, 0.17, 0.88, 0.80])
        x = np.arange(len(labels))
        b = ax.bar(x, debt, color=c["warm_grey_light"], width=0.5)
        top = max(debt)
        for bar, v in zip(b, debt):
            ax.text(bar.get_x() + bar.get_width() / 2, v + top * 0.03, dfmt(v), ha="center", va="bottom", fontsize=FS, color=c["text"])
        ax.set_ylim(0, top * 2.1)                                  # 막대는 아래쪽
        ax.set_xticks(x)
        ax.set_xticklabels([f"{lb}\n{nt}" for lb, nt in zip(labels, notes)], fontsize=FS - 0.4)
        ax.yaxis.set_major_locator(NullLocator())
        _style(ax, c)
        ax2 = ax.twinx()
        vals = list(irr) + list(irr_ex or [])
        lo, hi = min(vals), max(vals)
        span = max(hi - lo, 1.0)
        ax2.set_ylim(lo - span * 1.25, hi + span * 0.3)            # 선은 위쪽
        ax2.plot(x, irr, color=c["gold"], lw=2.2, marker="o", ms=4)
        for xi, v in zip(x, irr):
            ax2.text(xi, v + span * 0.05, f"{v:.1f}%", ha="center", va="bottom", fontsize=FS + 0.6, fontweight="bold", color=c["gold"])
        if irr_ex is not None:
            ax2.plot(x, irr_ex, color=c["brick"], lw=1.3, ls="--", marker="o", ms=3)
            for xi, v in zip(x, irr_ex):
                ax2.text(xi, v - span * 0.05, f"{v:.1f}%", ha="center", va="top", fontsize=FS - 0.6, color=c["brick"])
        ax2.yaxis.set_major_locator(NullLocator())
        for sp in ("top", "left", "right"):
            ax2.spines[sp].set_visible(False)
        _save(fig, path)
    return draw


# ---------------------------------------------------------------------------
# CFADS vs 원리금 + DSCR
# ---------------------------------------------------------------------------
def cfads_ds(years: Sequence[int], cfads: Sequence[float], ds: Sequence[float], dscr: Sequence[float], c: Mapping,
             target: float, labels: tuple[str, str, str], fmt: Callable[[float], str]) -> Draw:
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        ax = fig.add_axes([0.07, 0.12, 0.84, 0.84])
        x = np.arange(len(years))
        ax.bar(x - 0.2, cfads, width=0.38, color=c["brown_mid"], label=labels[0])
        ax.bar(x + 0.2, ds, width=0.38, color=c["gold"], label=labels[1])
        ax.set_xticks(x[::2] if len(x) > 12 else x)
        ax.set_xticklabels([str(years[i]) for i in (x[::2] if len(x) > 12 else x)])
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: fmt(v)))
        ax.tick_params(axis="y", labelsize=FS - 0.6, colors=c["note"])
        _style(ax, c, grid_y=True)
        ax2 = ax.twinx()
        d = np.array(dscr, dtype=float)
        ax2.plot(x, d, color=c["charcoal"], lw=1.6, marker="o", ms=2.2)
        ax2.axhline(target, color=c["brick"], lw=0.8, ls="--")
        ax2.text(x[-1], target, f" {labels[2]} {target:.2f}x", va="bottom", ha="right", fontsize=FS - 0.4, color=c["brick"])
        fin = d[np.isfinite(d)]
        if len(fin):
            ax2.set_ylim(0, max(fin.max(), target) * 1.25)
        for s in ("top", "left", "bottom"):
            ax2.spines[s].set_visible(False)
        ax2.spines["right"].set_color(c["warm_grey_light"])
        ax2.tick_params(labelsize=FS - 0.6, colors=c["note"], length=0)
        ax2.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.1f}x"))
        _save(fig, path)
    return draw


# ---------------------------------------------------------------------------
# 토네이도
# ---------------------------------------------------------------------------
def tornado(rows: Sequence[tuple[str, float, float]], base: float, c: Mapping, fmt: Callable[[float], str],
            ref: float | None = None, ref_label: str = "") -> Draw:
    """rows: [(변수 라벨, 불리한 쪽 값, 유리한 쪽 값)] — 위에서부터 범위가 큰 순서."""
    labels = [r[0] for r in rows]

    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        lf = label_frac(labels, w)
        ax = fig.add_axes([lf, 0.08, 0.95 - lf, 0.88])
        vals = [v for _, a, b in rows for v in (a, b) if v == v] + [base] + ([ref] if ref else [])
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1.0
        for i, (_, a, b) in enumerate(rows):
            for v, col in ((a, c["brick"]), (b, c["brown_mid"])):
                if v != v:
                    continue
                ax.barh(i, v - base, left=base, height=0.56, color=col)
                ax.text(v + (span * 0.012 if v >= base else -span * 0.012), i, fmt(v), va="center",
                        ha="left" if v >= base else "right", fontsize=FS + 0.2, fontweight="bold", color=c["text"])
        ax.axvline(base, color=c["charcoal"], lw=0.9)
        if ref is not None:
            ax.axvline(ref, color=c["brick"], lw=0.8, ls="--")
            ax.text(ref, -0.75, ref_label, ha="center", va="bottom", fontsize=FS - 0.6, color=c["brick"])
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels(labels)
        ax.invert_yaxis()
        ax.set_ylim(len(rows) - 0.4, -1.0)
        ax.set_xlim(lo - span * 0.22, hi + span * 0.22)
        ax.xaxis.set_major_locator(NullLocator())
        _style(ax, c)
        ax.spines["bottom"].set_visible(False)
        _save(fig, path)
    return draw


# ---------------------------------------------------------------------------
# 히트맵 (임대료 × CAPEX)
# ---------------------------------------------------------------------------
def heatmap(z: np.ndarray, rows: Sequence[str], cols: Sequence[str], c: Mapping, thresholds: tuple[float, float],
            xlabel: str, ylabel: str) -> Draw:
    """값 < 1.0 벽돌색, 1.0~목표 웜그레이, ≥ 목표 골드 계열 (명도 = 값)."""
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        ax = fig.add_axes([0.13, 0.14, 0.85, 0.82])
        lo, tgt = thresholds
        from matplotlib.colors import to_rgb
        cols_rgb = {"bad": to_rgb(c["brick"]), "mid": to_rgb(c["warm_grey_light"]), "good": to_rgb(c["gold"])}
        img = np.zeros((*z.shape, 3))
        for i in range(z.shape[0]):
            for j in range(z.shape[1]):
                v = z[i, j]
                key = "bad" if v < lo else ("mid" if v < tgt else "good")
                base = np.array(cols_rgb[key])
                mix = 0.35 + 0.65 * min(1.0, abs(v - tgt) / max(tgt, 1e-9) * 2)
                img[i, j] = 1 - (1 - base) * mix
                ax.text(j, i, f"{v:.2f}x", ha="center", va="center", fontsize=FS + 0.8, fontweight="bold",
                        color="white" if key == "bad" and mix > 0.6 else c["text"])
        ax.imshow(img, aspect="auto")
        ax.set_xticks(range(len(cols)))
        ax.set_xticklabels(cols)
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels(rows)
        ax.set_xlabel(xlabel, fontsize=FS, color=c["note"])
        ax.set_ylabel(ylabel, fontsize=FS, color=c["note"])
        for s in ax.spines.values():
            s.set_visible(False)
        ax.tick_params(colors=c["text"], labelsize=FS, length=0)
        _save(fig, path)
    return draw


# ---------------------------------------------------------------------------
# XY 선 (실수 x축): 승인 확률별 옵션 가치, 수렴
# ---------------------------------------------------------------------------
def xy(series: Sequence[tuple[str, Sequence[float], Sequence[float], str]], c: Mapping, xfmt: Callable[[float], str],
       yfmt: Callable[[float], str], vline: tuple[float, str] | None = None, band: Sequence[float] | None = None,
       logx: bool = False, hline: float | None = None) -> Draw:
    """series: [(이름, x, y, 색)]. band: 첫 시리즈의 ±값(표준오차 × 1.96)."""
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        ax = fig.add_axes([0.11, 0.13, 0.85, 0.83])
        for k, (name, xs, ys, col) in enumerate(series):
            ax.plot(xs, ys, color=col, lw=2.0 if k == 0 else 1.4, marker="o", ms=2.6)
            if band is not None and k == 0:
                ax.fill_between(xs, np.array(ys) - np.array(band), np.array(ys) + np.array(band), color=col, alpha=0.15, lw=0)
        if hline is not None:
            ax.axhline(hline, color=c["warm_grey"], lw=0.7, ls=":")
        if vline is not None:
            ax.axvline(vline[0], color=c["brick"], lw=0.9, ls="--")
            ax.text(vline[0], ax.get_ylim()[1], " " + vline[1], ha="left", va="top", fontsize=FS - 0.4, color=c["brick"])
        if logx:
            ax.set_xscale("log")
            ax.xaxis.set_minor_locator(NullLocator())
            ax.set_xticks(list(series[0][1]))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: xfmt(v)))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: yfmt(v)))
        ax.tick_params(axis="y", labelsize=FS - 0.4, colors=c["note"])
        _style(ax, c, grid_y=True)
        _save(fig, path)
    return draw


def ts_lines(labels: Sequence[str], series: Sequence[tuple[str, Sequence[float], str, float]], c: Mapping,
             fmt: Callable[[float], str], every: int = 6, end_values: Sequence[float] | None = None) -> Draw:
    """월별 시계열 (x = 'YYYY-MM' 라벨). 끝점에 '이름 값' (end_values가 있으면 그 값 = 기준일 일별 값)."""
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        ax = fig.add_axes([0.07, 0.12, 0.72, 0.84])
        x = np.arange(len(labels))
        ends = []
        for k, (name, ys, col, lw) in enumerate(series):
            y = np.array(ys, dtype=float)
            ax.plot(x, y, color=col, lw=lw)
            last = np.where(np.isfinite(y))[0]
            if len(last):
                lab = end_values[k] if end_values is not None else y[last[-1]]
                ends.append([y[last[-1]], name, col, x[last[-1]], lab])
        ends.sort(key=lambda e: e[0])
        span = (ax.get_ylim()[1] - ax.get_ylim()[0]) * 0.08
        shown = []
        for e in ends:
            yy = e[0] if not shown or e[0] - shown[-1] >= span else shown[-1] + span
            shown.append(yy)
            ax.annotate(f"{e[1]} {fmt(e[4])}", (e[3], e[0]), xytext=(x[-1] + len(x) * 0.03, yy), textcoords="data",
                        va="center", fontsize=FS + 0.4, fontweight="bold", color=e[2], annotation_clip=False)
        ticks = x[::every]
        ax.set_xticks(ticks)
        ax.set_xticklabels([labels[i] for i in ticks])
        ax.tick_params(axis="y", labelsize=FS - 0.4, colors=c["note"])
        _style(ax, c, grid_y=True)
        _save(fig, path)
    return draw
