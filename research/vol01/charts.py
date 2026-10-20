"""matplotlib 차트 (차트 영역만). 제목·범례 줄·출처는 layout.py가 PDF 텍스트로 그린다.

각 함수는 (png 경로, 폭 pt, 높이 pt)를 받는 그리기 함수를 돌려준다 → 셀 크기에 정확히 맞춰 렌더링(확대·축소 없음).
스타일: 격자 최소화, 막대 위 값 표시, 굵은 테두리 없음.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: E402
from matplotlib.ticker import FuncFormatter, NullLocator  # noqa: E402

DPI = 260
Draw = Callable[[Path, float, float], None]
FS = 7.6           # 기본 글자 크기(pt) — 페이지에서 실제 크기 그대로


def label_frac(labels: Sequence[str], w_pt: float, lo: float = 0.14, hi: float = 0.46) -> float:
    """y축 라벨이 잘리지 않도록 왼쪽 여백 비율을 라벨 실제 폭으로 계산 (한글 1em, 영문 약 0.56em)."""
    import unicodedata
    em = FS
    widest = max((sum(em if unicodedata.east_asian_width(ch) in ("W", "F") else em * 0.56 for ch in str(s)) for s in labels),
                 default=0)
    return min(hi, max(lo, (widest + 10) / w_pt))


def _fig(w_pt: float, h_pt: float):
    fig = plt.figure(figsize=(w_pt / 72, h_pt / 72))
    return fig


def _style(ax, c: Mapping, grid_y: bool = False, grid_x: bool = False) -> None:
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(c["warm_grey_light"])
    ax.spines["bottom"].set_linewidth(0.8)
    ax.tick_params(colors=c["text"], labelsize=FS, length=0, pad=3)
    if grid_y:
        ax.grid(axis="y", color=c["warm_grey_light"], lw=0.4, alpha=0.6)
    if grid_x:
        ax.grid(axis="x", color=c["warm_grey_light"], lw=0.4, alpha=0.6)
    ax.set_axisbelow(True)


def _save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)


def comma(v: float, dec: int = 0) -> str:
    return f"{v:,.{dec}f}"


# ---------------------------------------------------------------------------
# 막대
# ---------------------------------------------------------------------------
def bars(labels: Sequence[str], values: Sequence[float], colors: Sequence[str], c: Mapping, fmt: Callable[[float], str],
         ylim_pad: float = 1.18, notes: Sequence[str] | None = None) -> Draw:
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        ax = fig.add_axes([0.06, 0.13, 0.92, 0.82])
        b = ax.bar(labels, values, color=colors, width=0.56)
        top = max(values)
        for i, (bar, v) in enumerate(zip(b, values)):
            ax.text(bar.get_x() + bar.get_width() / 2, v + top * 0.025, fmt(v), ha="center", va="bottom",
                    fontsize=FS + 1.4, fontweight="bold", color=c["text"])
            if notes and notes[i]:
                ax.text(bar.get_x() + bar.get_width() / 2, v / 2, notes[i], ha="center", va="center",
                        fontsize=FS + 1.6, fontweight="bold", color="white")
        ax.set_ylim(0, top * ylim_pad)
        ax.yaxis.set_major_locator(NullLocator())
        _style(ax, c)
        _save(fig, path)
    return draw


def hbars(labels: Sequence[str], values: Sequence[float], colors: Sequence[str], c: Mapping,
          fmt: Callable[[float], str], left: float | None = None, log: bool = False) -> Draw:
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        lf = left if left is not None else label_frac(labels, w)
        ax = fig.add_axes([lf, 0.06, 0.86 - lf, 0.9])
        y = range(len(labels))
        ax.barh(list(y), values, color=colors, height=0.56)
        vmax = max(values)
        for i, v in enumerate(values):
            x = v * (1.06 if log else 1) + (0 if log else vmax * 0.015)
            ax.text(x, i, fmt(v), va="center", fontsize=FS + 1.2, fontweight="bold", color=c["text"])
        ax.set_yticks(list(y))
        ax.set_yticklabels(labels)
        ax.invert_yaxis()
        if log:
            ax.set_xscale("log")
        ax.set_xlim(0 if not log else min(values) * 0.6, vmax * (1.22 if not log else 3.2))
        ax.xaxis.set_major_locator(NullLocator())
        ax.xaxis.set_minor_locator(NullLocator())
        _style(ax, c)
        ax.spines["bottom"].set_visible(False)
        _save(fig, path)
    return draw


def grouped(cats: Sequence[str], series: Sequence[tuple[str, Sequence[float], str]], c: Mapping,
            fmt: Callable[[float], str], label_series: set[int] | None = None, horizontal: bool = False,
            extra_labels: Sequence[str] | None = None, left: float | None = None, log: bool = False,
            zero_line: bool = False) -> Draw:
    """series: [(이름, 값들, 색)]. label_series: 값 라벨을 붙일 시리즈 인덱스(기본: 전부)."""
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        n = len(series)
        width = 0.8 / n
        vals = [v for _, vs, _ in series for v in vs if v == v]
        vmax, vmin = max(vals), min(vals + [0])
        if horizontal:
            lf = left if left is not None else label_frac(cats, w)
            ax = fig.add_axes([lf, 0.05, 0.86 - lf, 0.92])
            for k, (_, vs, col) in enumerate(series):
                ys = [i + (k - (n - 1) / 2) * width for i in range(len(cats))]
                ax.barh(ys, vs, height=width * 0.92, color=col)
                if label_series is None or k in label_series:
                    for yy, v in zip(ys, vs):
                        if v == v:
                            ax.text(v * (1.05 if log else 1) + (0 if log else vmax * 0.012), yy, fmt(v), va="center",
                                    fontsize=FS - 0.2, color=c["text"])
            if extra_labels:
                for i, t in enumerate(extra_labels):
                    vals_i = [vs[i] for _, vs, _ in series if vs[i] == vs[i]]
                    ax.text(max(vals_i) * (1.6 if log else 1) + (0 if log else vmax * 0.16), i, t, va="center",
                            fontsize=FS + 1.6, fontweight="bold", color=c["gold"])
            ax.set_yticks(range(len(cats)))
            ax.set_yticklabels(cats)
            ax.invert_yaxis()
            if log:
                ax.set_xscale("log")
                ax.set_xlim(min(vals) * 0.5, vmax * 9)
            else:
                ax.set_xlim(0, vmax * 1.42)
            ax.xaxis.set_major_locator(NullLocator())
            ax.xaxis.set_minor_locator(NullLocator())
            _style(ax, c)
            ax.spines["bottom"].set_visible(False)
        else:
            ax = fig.add_axes([0.03, 0.12, 0.95, 0.84])
            for k, (_, vs, col) in enumerate(series):
                xs = [i + (k - (n - 1) / 2) * width for i in range(len(cats))]
                bars_ = ax.bar(xs, [0 if v != v else v for v in vs], width=width * 0.9,
                               color=[col if (v == v and v >= 0) else c["brick"] for v in vs])
                if label_series is None or k in label_series:
                    for b, v in zip(bars_, vs):
                        if v == v:
                            off = (vmax - vmin) * 0.02
                            ax.text(b.get_x() + b.get_width() / 2, v + (off if v >= 0 else -off), fmt(v),
                                    ha="center", va="bottom" if v >= 0 else "top", fontsize=FS - 0.6,
                                    color=c["text"])
            ax.set_xticks(range(len(cats)))
            ax.set_xticklabels(cats)
            ax.set_ylim(min(0, vmin * 1.9 - (vmax - vmin) * 0.04), vmax * 1.2)
            ax.yaxis.set_major_locator(NullLocator())
            if zero_line or vmin < 0:
                ax.axhline(0, color=c["warm_grey"], lw=0.6)
            _style(ax, c)
        _save(fig, path)
    return draw


def contrib_bars(names: Sequence[str], earn: Sequence[float], mult: Sequence[float], c: Mapping,
                 labels: tuple[str, str]) -> Draw:
    """회사별 이익 기여 vs 멀티플 기여 (% of Δln 시총). 음수 허용, 0 기준선."""
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        lf = label_frac(names, w)
        ax = fig.add_axes([lf, 0.06, 0.93 - lf, 0.9])
        n, hgt = len(names), 0.36
        vals = list(earn) + list(mult)
        lo, hi = min(0, min(vals)), max(vals)
        span = hi - lo
        for i in range(n):
            for k, (v, col) in enumerate(((earn[i], c["brown_mid"]), (mult[i], c["gold"]))):
                y = i + (k - 0.5) * hgt
                ax.barh(y, v, height=hgt * 0.92, color=col if v >= 0 else c["brick"])
                ax.text(v + (span * 0.015 if v >= 0 else -span * 0.015), y, f"{v:.0f}%", va="center",
                        ha="left" if v >= 0 else "right", fontsize=FS + 0.6, fontweight="bold", color=c["text"])
        ax.axvline(0, color=c["warm_grey"], lw=0.7)
        ax.axvline(50, color=c["warm_grey_light"], lw=0.6, ls="--")
        ax.text(50, -0.75, "50%", ha="center", va="bottom", fontsize=FS - 0.6, color=c["note"])
        ax.set_yticks(range(n))
        ax.set_yticklabels(names)
        ax.invert_yaxis()
        ax.set_ylim(n - 0.4, -0.95)
        ax.set_xlim(lo - span * 0.12 if lo < 0 else 0, hi + span * 0.16)
        ax.xaxis.set_major_locator(NullLocator())
        _style(ax, c)
        ax.spines["bottom"].set_visible(False)
        _save(fig, path)
    return draw


def range_chart(rows: Sequence[tuple[str, float, float, str]], base: tuple[float, str] | None, c: Mapping,
                fmt: Callable[[float], str], xmax: float) -> Draw:
    """rows: [(라벨, 시작, 끝, 색)] — 막대 또는 범위 밴드. base: (값, 라벨) 골드 마커."""
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        ax = fig.add_axes([0.13, 0.12, 0.84, 0.84])
        for i, (lab, a, b, col) in enumerate(rows):
            ax.barh(i, b - a, left=a, height=0.5, color=col)
            if a > 0:
                ax.text(a, i - 0.36, fmt(a), ha="center", va="bottom", fontsize=FS, color=c["note"])
            ax.text(b + xmax * 0.012, i, fmt(b), va="center", fontsize=FS + 1.2, fontweight="bold", color=c["text"])
        if base:   # 기준값 마커와 라벨은 밴드 위쪽 (축 라벨과 겹치지 않게)
            i = len(rows) - 1
            ax.plot([base[0]], [i], marker="D", ms=7, color=c["gold"], zorder=5)
            ax.text(base[0], i - 0.36, base[1], ha="center", va="bottom", fontsize=FS + 0.6, fontweight="bold",
                    color=c["gold"])
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels([r[0] for r in rows])
        ax.invert_yaxis()
        ax.set_xlim(0, xmax)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: comma(v)))
        _style(ax, c, grid_x=True)
        _save(fig, path)
    return draw


def lines(x: Sequence[int], series: Sequence[tuple[str, Sequence[float], str, float]], c: Mapping,
          fmt: Callable[[float], str], ref: float | None = None, right: float = 0.80, ylim: tuple | None = None,
          end_labels: bool = True) -> Draw:
    """series: [(이름, 값들, 색, 선 굵기)]. 끝점에 '이름 값' 라벨."""
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        ax = fig.add_axes([0.07, 0.12, right - 0.07, 0.84])
        if ref is not None:
            ax.axhline(ref, color=c["warm_grey_light"], lw=0.8, ls="--")
        ends = []
        for name, ys, col, lw in series:
            ax.plot(x, ys, color=col, lw=lw, marker="o", ms=2.4)
            ends.append([ys[-1], name, col])
        if end_labels:   # 끝 라벨 겹침 방지
            ends.sort(key=lambda e: e[0])
            span = (ax.get_ylim()[1] - ax.get_ylim()[0]) * 0.075
            for k in range(1, len(ends)):
                if ends[k][0] - ends[k - 1][0] < span:
                    ends[k][0] = ends[k - 1][0] + span
            orig = {name: ys[-1] for name, ys, _, _ in series}
            for ypos, name, col in ends:
                ax.annotate(f"{name} {fmt(orig[name])}", (x[-1], orig[name]), xytext=(x[-1] + (x[-1] - x[0]) * 0.03, ypos),
                            textcoords="data", va="center", fontsize=FS + 0.6, fontweight="bold", color=col,
                            annotation_clip=False)
        if ylim:
            ax.set_ylim(*ylim)
        ax.set_xticks(list(x) if len(x) <= 6 else [v for v in x if (v - x[0]) % 2 == 0])
        ax.tick_params(axis="y", labelsize=FS - 0.4, colors=c["note"])
        _style(ax, c, grid_y=True)
        _save(fig, path)
    return draw


def waterfall(steps: Sequence[tuple[str, float, str]], c: Mapping, fmt: Callable[[float], str]) -> Draw:
    """steps: [(라벨, 값, 종류)] 종류 = 'total' | 'delta'. 누적 폭포."""
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        ax = fig.add_axes([0.03, 0.12, 0.95, 0.84])
        run, xs, tops = 0.0, [], []
        for i, (lab, v, kind) in enumerate(steps):
            if kind == "total":
                ax.bar(i, v, color=c["brown_dark"] if i == 0 else c["gold"], width=0.56)
                run = v
                y_lab = v
            else:
                base = run if v >= 0 else run + v
                ax.bar(i, abs(v), bottom=base, color=c["brown_mid"] if v >= 0 else c["brick"], width=0.56)
                if i < len(steps) - 1:
                    pass
                run += v
                y_lab = max(run, run - v)
            ax.text(i, y_lab * 1.015 + abs(steps[0][1]) * 0.01, fmt(v), ha="center", va="bottom",
                    fontsize=FS + 1, fontweight="bold", color=c["text"])
            xs.append(i)
            tops.append(run)
        for i in range(len(steps) - 1):
            ax.plot([i + 0.28, i + 0.72], [tops[i], tops[i]], color=c["warm_grey"], lw=0.6, ls=":")
        ax.set_xticks(xs)
        ax.set_xticklabels([s[0] for s in steps])
        ax.set_ylim(0, max(tops + [s[1] for s in steps]) * 1.16)
        ax.yaxis.set_major_locator(NullLocator())
        _style(ax, c)
        _save(fig, path)
    return draw


def risk_matrix(points: Sequence[tuple[str, float, float]], c: Mapping, xlabel: str, ylabel: str,
                levels: tuple[str, str]) -> Draw:
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        ax = fig.add_axes([0.1, 0.13, 0.86, 0.83])
        ax.add_patch(Rectangle((3, 3), 2.5, 2.5, color=c["panel"], zorder=0))
        for v in (3,):
            ax.axvline(v, color=c["warm_grey_light"], lw=0.6)
            ax.axhline(v, color=c["warm_grey_light"], lw=0.6)
        for name, lk, im in points:
            col = c["brick"] if lk >= 3 and im >= 4 else c["brown_dark"]
            ax.scatter([lk], [im], s=90, color=col, zorder=3)
            # 같은 행 오른쪽에 가까운 점이 있으면 라벨을 위로 올려 겹침 방지
            crowded = any(o_im == im and 0 < o_lk - lk <= 1.5 for _, o_lk, o_im in points)
            ax.annotate(name, (lk, im), xytext=(0, 9) if crowded else (7, 4), textcoords="offset points",
                        ha="center" if crowded else "left", fontsize=FS + 0.6, fontweight="bold", color=col)
        ax.set_xlim(0.5, 5.5)
        ax.set_ylim(0.5, 5.5)
        ax.set_xticks([1, 3, 5])
        ax.set_xticklabels([levels[0], "", levels[1]])
        ax.set_yticks([1, 3, 5])
        ax.set_yticklabels([levels[0], "", levels[1]])
        ax.set_xlabel(xlabel, fontsize=FS, color=c["note"])
        ax.set_ylabel(ylabel, fontsize=FS, color=c["note"])
        _style(ax, c)
        ax.spines["left"].set_visible(True)
        ax.spines["left"].set_color(c["warm_grey_light"])
        _save(fig, path)
    return draw


# ---------------------------------------------------------------------------
# 파이프라인 구조도 (A3)
# ---------------------------------------------------------------------------
def pipeline(sources: Sequence[dict], stages: Sequence[tuple[str, Sequence[str]]], c: Mapping, lang: str) -> Draw:
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        ax.axis("off")
        n = len(sources)
        bh, gap = 86 / n - 2.2, 2.2
        for i, s in enumerate(sources):
            y = 96 - (i + 1) * bh - i * gap
            done = s["ok"]
            ax.add_patch(FancyBboxPatch((1, y), 27, bh, boxstyle="round,pad=0.3,rounding_size=1",
                                        fc=c["panel"] if done else "white", ec=c["gold"] if done else c["warm_grey"],
                                        lw=1.0, ls="-" if done else (0, (3, 2))))
            ax.text(2.6, y + bh * 0.66, s["org_kr"] if lang == "kr" else s["org_en"], fontsize=FS + 0.6,
                    fontweight="bold", va="center", color=c["text"] if done else c["warm_grey"])
            ax.text(2.6, y + bh * 0.28, (s["status_kr"] if lang == "kr" else s["status_en"]), fontsize=FS - 0.4,
                    va="center", color=c["brown_dark"] if done else c["warm_grey"])
        xs, sw = [35, 57, 79], 19.5
        for i, (title, items) in enumerate(stages):
            ax.add_patch(FancyBboxPatch((xs[i], 18), sw, 64, boxstyle="round,pad=0.4,rounding_size=1.2",
                                        fc=c["charcoal"] if i == 2 else "white", ec=c["charcoal"], lw=1.1))
            col = "white" if i == 2 else c["text"]
            ax.text(xs[i] + 1.6, 78, title, fontsize=FS + 2, fontweight="bold", va="top",
                    color=c["gold"] if i == 2 else c["brown_dark"])
            for k, it in enumerate(items):
                ax.text(xs[i] + 1.6, 69 - k * 8.4, it, fontsize=FS, va="top", color=col)
        for x0, x1 in ((29, xs[0] - 0.6), (xs[0] + sw + 0.4, xs[1] - 0.6), (xs[1] + sw + 0.4, xs[2] - 0.6)):
            ax.add_patch(FancyArrowPatch((x0, 50), (x1, 50), arrowstyle="-|>", mutation_scale=11, color=c["gold"],
                                         lw=1.3))
        _save(fig, path)
    return draw


# ---------------------------------------------------------------------------
# 표지 배경: 은은한 송전선·격자 패턴 (골드 저채도)
# ---------------------------------------------------------------------------
def cover_background(path: Path, w_pt: float, h_pt: float, c: Mapping) -> Path:
    fig = _fig(w_pt, h_pt)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 75)
    ax.axis("off")
    fig.patch.set_facecolor(c["charcoal"])
    ax.set_facecolor(c["charcoal"])
    g = c["gold"]
    for x in range(0, 101, 4):                      # 미세 격자
        ax.plot([x, x], [0, 75], color=g, lw=0.25, alpha=0.06)
    for y in range(0, 76, 4):
        ax.plot([0, 100], [y, y], color=g, lw=0.25, alpha=0.06)

    def tower(x0: float, base: float, hgt: float, alpha: float) -> list[tuple[float, float]]:
        top, w0, w1 = base + hgt, hgt * 0.16, hgt * 0.035
        pts = [(x0 - w0, base), (x0 - w1, top), (x0 + w1, top), (x0 + w0, base)]
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color=g, lw=0.8, alpha=alpha)
        n = 6
        for k in range(n):                          # 격자형 트러스
            y0, y1 = base + hgt * k / n, base + hgt * (k + 1) / n
            wa, wb = w0 - (w0 - w1) * k / n, w0 - (w0 - w1) * (k + 1) / n
            ax.plot([x0 - wa, x0 + wb], [y0, y1], color=g, lw=0.5, alpha=alpha * 0.8)
            ax.plot([x0 + wa, x0 - wb], [y0, y1], color=g, lw=0.5, alpha=alpha * 0.8)
        arms = []
        for k, frac in enumerate((0.72, 0.86)):     # 완금(cross-arm)
            ya = base + hgt * frac
            span = hgt * (0.34 - 0.08 * k)
            ax.plot([x0 - span, x0 + span], [ya, ya], color=g, lw=0.8, alpha=alpha)
            arms += [(x0 - span, ya), (x0 + span, ya)]
        return arms

    towers = [(58, 6, 40, 0.20), (76, 10, 30, 0.16), (90, 13, 22, 0.12), (101, 15, 16, 0.10)]
    arm_sets = [tower(*t) for t in towers]
    for a, b in zip(arm_sets, arm_sets[1:]):        # 송전선 (현수선)
        for p, q in zip(a, b):
            xs = [p[0] + (q[0] - p[0]) * t / 30 for t in range(31)]
            sag = 2.2
            ys = [p[1] + (q[1] - p[1]) * t / 30 - sag * math.sin(math.pi * t / 30) for t in range(31)]
            ax.plot(xs, ys, color=g, lw=0.6, alpha=0.18)
    ax.plot([0, 100], [5.5, 5.5], color=g, lw=0.6, alpha=0.18)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160, facecolor=c["charcoal"])
    plt.close(fig)
    return path
