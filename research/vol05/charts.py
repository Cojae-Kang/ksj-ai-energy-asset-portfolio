"""Vol.5 차트 (차트 영역만). Vol.1~4 스타일 도우미를 그대로 쓰고, 지도용 차트 셋을 더한다."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping, Sequence

from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402
from matplotlib.ticker import NullLocator  # noqa: E402

from research.vol01.charts import FS, Draw, _fig, _save, _style, contrib_bars, cover_background, label_frac, range_chart  # noqa: F401
from research.vol03.charts import export_figure  # noqa: F401


def lens_flow(steps: Sequence[tuple[str, str, str, str, str]], c: Mapping, flow_label: str) -> Draw:
    """돈의 흐름 4단계: (단계, 'Vol.N', 앉은 자리, 질문, 핵심 숫자). 박스 사이 화살표, 아래에 흐름 라벨."""
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        ax.axis("off")
        n, gap = len(steps), 4.4
        bw = (100 - 2 - gap * (n - 1)) / n
        top, bh = 94, 78
        fs = FS + 1.6
        for i, (stage, vol, seat, q, num) in enumerate(steps):
            x = 1 + i * (bw + gap)
            last = i == n - 1
            ax.add_patch(FancyBboxPatch((x, top - bh), bw, bh, boxstyle="round,pad=0.4,rounding_size=1.2",
                                        fc=c["charcoal"] if last else (c["panel"] if i == 0 else "white"),
                                        ec=c["charcoal"] if last else c["gold"], lw=1.2))
            txt, sub = ("white", c["warm_grey_light"]) if last else (c["text"], c["note"])
            ax.text(x + 2.2, top - 4.5, vol, fontsize=fs, fontweight="bold", va="top", color=c["gold"])
            ax.text(x + 2.2, top - 13, stage, fontsize=FS + 7, fontweight="bold", va="top", color=c["gold"] if last else c["brown_dark"])
            ax.plot([x + 2.2, x + bw - 2.2], [top - 28, top - 28], color=c["gold"], lw=0.8)
            ax.text(x + 2.2, top - 32, seat, fontsize=fs + 0.6, fontweight="bold", va="top", color=txt)
            ax.text(x + 2.2, top - 42, q, fontsize=fs - 0.6, va="top", color=sub, wrap=True)
            ax.text(x + 2.2, top - bh + 6, num, fontsize=fs + 0.6, fontweight="bold", va="bottom", color=c["gold"])
            if i < n - 1:
                ax.add_patch(FancyArrowPatch((x + bw + 0.5, top - bh / 2), (x + bw + gap - 0.5, top - bh / 2),
                                             arrowstyle="-|>", mutation_scale=16, color=c["gold"], lw=1.6))
        ax.add_patch(FancyArrowPatch((1, 6), (99, 6), arrowstyle="-|>", mutation_scale=12, color=c["warm_grey"], lw=0.9))
        ax.text(50, 8.5, flow_label, ha="center", va="bottom", fontsize=FS, color=c["note"])
        _save(fig, path)
    return draw


def hbar_ref(labels: Sequence[str], values: Sequence[float], colors: Sequence[str], c: Mapping, fmt: Callable[[float], str],
             refs: Sequence[tuple[float, str, str]] = (), xmax: float | None = None) -> Draw:
    """가로 막대 + 세로 기준선(값, 라벨, 색). 기준선 라벨은 막대 위쪽 여백에, 가까우면 높이를 나눈다."""
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        lf = label_frac(labels, w)
        ax = fig.add_axes([lf, 0.04, 0.90 - lf, 0.84])
        n = len(labels)
        ax.barh(range(n), values, color=colors, height=0.56, zorder=2)
        top = xmax or max(list(values) + [r[0] for r in refs]) * 1.22
        for i, v in enumerate(values):
            ax.text(v + top * 0.012, i, fmt(v), va="center", fontsize=FS + 1.2, fontweight="bold", color=c["text"], zorder=4)
        placed: list[float] = []
        for k, (rv, lab, col) in enumerate(sorted(refs, key=lambda r: r[0])):
            ax.axvline(rv, color=col, lw=1.1, ls="--", zorder=3)
            near = any(abs(rv - p) < top * 0.18 for p in placed)
            ax.text(rv, -0.62 - (0.42 if near else 0.0), lab, ha="center", va="bottom", fontsize=FS - 0.2, color=col, fontweight="bold",
                    bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.4, "alpha": 0.9}, zorder=5)
            placed.append(rv)
        ax.set_yticks(range(n))
        ax.set_yticklabels(labels)
        ax.set_ylim(n - 0.45, -1.25)
        ax.set_xlim(0, top)
        ax.xaxis.set_major_locator(NullLocator())
        _style(ax, c)
        ax.spines["bottom"].set_visible(False)
        _save(fig, path)
    return draw


def spans(rows: Sequence[tuple[str, float, float, str]], c: Mapping, fmt: Callable[[float], str], xmax: float,
          gap: tuple[float, float, str] | None = None) -> Draw:
    """범위 막대: rows = [(라벨, 시작, 끝, 색)] — 시작이 0이면 막대(끝 값만), 아니면 구간(양 끝 값). gap = (시작, 끝, 라벨) 화살표."""
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        labels = [r[0] for r in rows]
        lf = label_frac(labels, w)
        ax = fig.add_axes([lf, 0.10, 0.93 - lf, 0.80])
        n = len(rows)
        for i, (_, a, b, col) in enumerate(rows):
            ax.barh(i, b - a, left=a, height=0.5, color=col, zorder=2)
            ax.text(b + xmax * 0.012, i, fmt(b), va="center", ha="left", fontsize=FS + 1.2, fontweight="bold", color=c["text"], zorder=4)
            if a > 0:
                ax.text(a - xmax * 0.012, i, fmt(a), va="center", ha="right", fontsize=FS + 1.2, fontweight="bold", color=c["text"], zorder=4)
        if gap:
            a, b, lab = gap
            y = n - 0.45
            ax.annotate("", xy=(b, y), xytext=(a, y), arrowprops={"arrowstyle": "<->", "color": c["brick"], "lw": 1.2})
            ax.text((a + b) / 2, y + 0.08, lab, ha="center", va="top", fontsize=FS + 0.4, fontweight="bold", color=c["brick"])
        ax.set_yticks(range(n))
        ax.set_yticklabels(labels)
        ax.set_ylim(n - 0.2 if gap else n - 0.5, -0.6)
        ax.set_xlim(0, xmax)
        ax.tick_params(axis="x", labelsize=FS - 0.4, colors=c["note"])
        _style(ax, c, grid_x=True)
        _save(fig, path)
    return draw


def stacked_h(cats: Sequence[str], series: Sequence[tuple[str, Sequence[int], str]], c: Mapping, totals: Sequence[str]) -> Draw:
    """편별 등급 개수 누적 가로 막대: series = [(등급, 개수들, 색)], 칸 안에 개수, 오른쪽에 합계 문구."""
    def draw(path: Path, w: float, h: float) -> None:
        fig = _fig(w, h)
        lf = label_frac(cats, w)
        ax = fig.add_axes([lf, 0.04, 0.84 - lf, 0.92])
        n = len(cats)
        left = [0.0] * n
        vmax = max(sum(s[1][i] for s in series) for i in range(n))
        for name, vals, col in series:
            ax.barh(range(n), vals, left=left, color=col, height=0.58, edgecolor="white", lw=0.8)
            for i, v in enumerate(vals):
                if v >= vmax * 0.035:
                    dark = col in (c["gold"], c["warm_grey_light"], c["panel"])
                    ax.text(left[i] + v / 2, i, f"{v}", ha="center", va="center", fontsize=FS + 0.4, fontweight="bold",
                            color=c["text"] if dark else "white")
                left[i] += v
        for i, t in enumerate(totals):
            ax.text(left[i] + vmax * 0.015, i, t, va="center", fontsize=FS + 0.6, fontweight="bold", color=c["text"])
        ax.set_yticks(range(n))
        ax.set_yticklabels(cats)
        ax.invert_yaxis()
        ax.set_xlim(0, vmax * 1.18)
        ax.xaxis.set_major_locator(NullLocator())
        _style(ax, c)
        ax.spines["bottom"].set_visible(False)
        _save(fig, path)
    return draw
