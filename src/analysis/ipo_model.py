"""IPO 희망공모가 산정 엔진 (순수 함수). Vol.3에서 사용.

구조 (국내 IPO 실무의 평가가액 산정 → 할인 → 밴드 순서를 따르되 특정 증권신고서를 복제하지 않음):
    비교기업 배수(PER 주, EV/EBITDA 보조) → 적정 시가총액 = 적용 이익 × 적용 배수
    → 공모 후 주식수(신주·구주) → 주당 평가가액 = 적정 시총 ÷ 공모 후 주식수
    → 할인율 시나리오 → 희망공모가 밴드
몬테카를로: 1년 후 주당가치 = 적용 이익 × (1 + 성장률) × 1년 후 PER × (1년 후 순이익률 ÷ 현재 순이익률) ÷ 공모 후 주식수.
  순이익률을 고정하면 '현재 기준', 순이익률도 확률변수(정점 이익)로 두면 '이중 고점(정점 이익 × 정점 배수)'.
  상관은 가우스 코퓰라(표준정규 상관 → 각 주변분포의 역함수)로 준다. 상관 0이면 독립.
금액 단위: 시총·이익 = KRW 억원(또는 같은 단위끼리), 주당 가격 = 원.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

KRW_PER_100M = 1e8


def finite(x) -> bool:
    return x is not None and isinstance(x, (int, float, np.floating)) and math.isfinite(float(x))


# ---------------------------------------------------------------------------
# 배수
# ---------------------------------------------------------------------------
def multiple(value: float | None, base: float | None) -> float:
    """value ÷ base. base ≤ 0 또는 결측이면 nan (적자 PER 등은 의미 없음)."""
    if not finite(value) or not finite(base) or base <= 0:
        return float("nan")
    return float(value) / float(base)


def enterprise_value(mcap: float | None, net_debt: float | None) -> float:
    """EV = 시가총액 + 순차입금 (리스부채·비지배지분 제외 — 단순화)."""
    if not finite(mcap) or not finite(net_debt):
        return float("nan")
    return float(mcap) + float(net_debt)


@dataclass
class Screen:
    """이상치 규칙 적용 결과."""
    value: float
    included: bool
    rule: str = ""          # R1..R5 (제외 사유 코드) 또는 R4(표시만)
    flagged: bool = False


def screen_per(per: float, ni: float | None, *, per_max: float, entity_warn: bool = False,
               exclude_nonpositive: bool = True, exclude_entity_warn: bool = True) -> Screen:
    """R1 적자 → 제외, R2 PER > per_max → 제외, R3 재무 주체 WARN → 제외."""
    if exclude_entity_warn and entity_warn:
        return Screen(per, False, "R3")
    if not finite(ni):
        return Screen(float("nan"), False, "missing")
    if exclude_nonpositive and ni <= 0:
        return Screen(float("nan"), False, "R1")
    if not finite(per):
        return Screen(float("nan"), False, "missing")
    if per > per_max:
        return Screen(per, False, "R2")
    return Screen(per, True)


def screen_ev(ev_mult: float, ebitda: float | None, ev: float | None, *, ev_max: float) -> Screen:
    """R5: EBITDA ≤ 0 또는 EV/EBITDA > ev_max → 제외. EV(순차입금) 결측 → 제외."""
    if not finite(ev):
        return Screen(float("nan"), False, "no_ev")
    if not finite(ebitda):
        return Screen(float("nan"), False, "missing")
    if ebitda <= 0:
        return Screen(float("nan"), False, "R5")
    if ev_mult > ev_max:
        return Screen(ev_mult, False, "R5")
    return Screen(ev_mult, True)


def flag_high(values: Mapping[str, float], factor: float) -> set[str]:
    """R4: 그룹 중앙값의 factor배 초과 → 표시 (제외하지 않음). 2개 이하면 표시하지 않음."""
    v = {k: x for k, x in values.items() if finite(x)}
    if len(v) < 3:
        return set()
    med = float(np.median(list(v.values())))
    return {k for k, x in v.items() if x > factor * med}


@dataclass
class GroupMultiple:
    n: int
    aggregate: float        # Σ분자 ÷ Σ분모 (이익 가중)
    mean: float
    median: float
    members: list[str] = field(default_factory=list)

    def pick(self, method: str) -> float:
        return {"aggregate": self.aggregate, "mean": self.mean, "median": self.median}[method]


def group_multiple(rows: Iterable[tuple[str, float, float]]) -> GroupMultiple:
    """rows = (이름, 분자(시총·EV), 분모(이익)) — 같은 통화·단위. 분모 ≤ 0은 호출 전에 걸러야 한다."""
    rows = [(k, float(a), float(b)) for k, a, b in rows if finite(a) and finite(b) and b > 0]
    if not rows:
        return GroupMultiple(0, float("nan"), float("nan"), float("nan"), [])
    m = [a / b for _, a, b in rows]
    return GroupMultiple(len(rows), sum(a for _, a, _ in rows) / sum(b for _, _, b in rows),
                         float(np.mean(m)), float(np.median(m)), [k for k, _, _ in rows])


def combine_groups(values: Sequence[float], method: str = "group_mean") -> float:
    """국내·해외 그룹 배수 결합. group_mean = 단순평균 (결측 그룹은 제외)."""
    v = [float(x) for x in values if finite(x)]
    if not v:
        return float("nan")
    if method != "group_mean":
        raise ValueError("combine = group_mean")
    return float(np.mean(v))


def normalized_multiple(current: float, conservative: float, weight: float = 0.5, method: str = "geometric") -> float:
    """정상화 배수: 현재 → 보수 쪽으로 weight만큼. geometric = exp((1−w)·ln 현재 + w·ln 보수), arithmetic = 선형."""
    if not (finite(current) and finite(conservative)) or current <= 0 or conservative <= 0:
        return float("nan")
    if method == "geometric":
        return math.exp((1 - weight) * math.log(current) + weight * math.log(conservative))
    if method == "arithmetic":
        return (1 - weight) * current + weight * conservative
    raise ValueError("normalization method = geometric | arithmetic")


# ---------------------------------------------------------------------------
# 공모 구조·주당 가격
# ---------------------------------------------------------------------------
@dataclass
class Shares:
    pre: float              # 상장 전 주식수
    post: float             # 공모 후 주식수
    new: float              # 신주
    old: float              # 구주매출
    offered: float          # 공모주식 = 신주 + 구주

    @property
    def dilution(self) -> float:
        return self.new / self.post

    @property
    def overhang(self) -> float:
        """공모 후 기존 주주 보유 = 보호예수 해제 후 잠재 매도 물량 (주식수)."""
        return self.pre - self.old


def deal_shares(pre: float, offer_ratio: float, new_ratio: float) -> Shares:
    """공모주식 = offer_ratio × 공모 후 주식수, 그중 신주 비중 new_ratio. 공모 후 = 상장 전 + 신주."""
    if not (0 < offer_ratio < 1 and 0 <= new_ratio <= 1 and pre > 0):
        raise ValueError("offer_ratio ∈ (0,1), new_ratio ∈ [0,1], pre > 0")
    post = pre / (1 - offer_ratio * new_ratio)
    offered = offer_ratio * post
    new = offered * new_ratio
    return Shares(pre, post, new, offered - new, offered)


def per_share(equity_100m: float, shares: float) -> float:
    """주당 가치(원) = 시총(억원) × 1억 ÷ 주식수."""
    return equity_100m * KRW_PER_100M / shares


def round_price(x: float, tick: float) -> float:
    return float(round(x / tick) * tick) if tick and finite(x) else x


def discounted(value: float, discount: float) -> float:
    return value * (1 - discount)


def implied_discount(value: float, price: float) -> float:
    """가격이 평가가액 대비 몇 % 할인인지."""
    return 1 - price / value if value else float("nan")


def sensitivity(ni_100m: float, shares: float, pers: Sequence[float], discounts: Sequence[float]) -> pd.DataFrame:
    """적용 PER × 할인율 → 주당 공모가(원). 행 = PER, 열 = 할인율."""
    base = {p: per_share(ni_100m * p, shares) for p in pers}
    return pd.DataFrame({d: [base[p] * (1 - d) for p in pers] for d in discounts}, index=list(pers))


# ---------------------------------------------------------------------------
# 몬테카를로
# ---------------------------------------------------------------------------
@dataclass
class MCResult:
    values: np.ndarray      # 1년 후 주당가치 (원)
    growth: np.ndarray      # 이익 성장률 표본
    per: np.ndarray         # 1년 후 PER 표본
    quantiles: dict[float, float]
    convergence: pd.DataFrame   # n, P10, P50, P90, mean, rel_change_p50
    converged: bool
    seed: int
    npm: np.ndarray | None = None   # 1년 후 순이익률 표본 (이중 고점일 때)

    def q(self, p: float) -> float:
        return float(np.quantile(self.values, p))

    def prob_below(self, price: float) -> float:
        """1년 후 주당가치 < price 확률 (= 그 가격에 공모받은 투자자의 1년 후 손실 확률)."""
        return float(np.mean(self.values < price))

    def percentile_of(self, price: float) -> float:
        return self.prob_below(price)


def log_growth_params(growth: Sequence[float]) -> tuple[float, float]:
    """연간 성장률 관측치(소수) → ln(1 + g)의 평균·표본표준편차."""
    x = np.log1p(np.asarray([g for g in growth if finite(g) and g > -1], dtype=float))
    if len(x) < 2:
        raise ValueError("성장률 관측치 2개 이상 필요")
    return float(x.mean()), float(x.std(ddof=1))


def tri_ppf(u: np.ndarray, lo: float, mode: float, hi: float) -> np.ndarray:
    """삼각분포 역누적분포함수 (u ∈ [0, 1])."""
    u = np.asarray(u, dtype=float)
    if hi <= lo:
        return np.full(u.shape, lo)
    fc = (mode - lo) / (hi - lo)
    left = lo + np.sqrt(u * (hi - lo) * (mode - lo))
    right = hi - np.sqrt((1 - u) * (hi - lo) * (hi - mode))
    return np.where(u < fc, left, right)


def corr_matrix(rho_gp: float = 0.0, rho_gm: float = 0.0, rho_pm: float = 0.0, k: int = 3) -> np.ndarray:
    """[성장률, PER, 순이익률] 상관행렬 (k=2면 앞 둘만). 양의 정부호가 아니면 ValueError."""
    c = np.array([[1.0, rho_gp, rho_gm], [rho_gp, 1.0, rho_pm], [rho_gm, rho_pm, 1.0]])[:k, :k]
    np.linalg.cholesky(c)
    return c


def monte_carlo(ni_100m: float, shares: float, log_g_mean: float, log_g_sd: float,
                per_tri: tuple[float, float, float], n: int, seed: int,
                checkpoints: Sequence[int] = (), tolerance: float = 0.01, horizon_years: int = 1,
                quantiles: Sequence[float] = (0.10, 0.25, 0.50, 0.75, 0.90),
                npm_tri: tuple[float, float, float] | None = None, npm_base: float | None = None,
                corr: np.ndarray | None = None) -> MCResult:
    """1년 후 주당가치 분포. 성장률: ln(1+g) ~ N(mean, sd) × horizon. PER: 삼각분포(최소, 최빈, 최대).

    npm_tri가 없고 corr도 없으면 이익률 고정·독립 추출(현재 기준, 이전 버전과 같은 난수열).
    npm_tri가 있으면 1년 후 순이익률 ~ 삼각분포, 이익 = 적용 이익 × (1+g) × npm ÷ npm_base.
    corr = [성장률, PER(, 순이익률)] 상관행렬 → 가우스 코퓰라. 같은 seed면 같은 결과.
    수렴 = 마지막 두 checkpoint의 P50 상대 차이 ≤ tolerance.
    """
    lo, mode, hi = sorted(per_tri)[0], per_tri[1], sorted(per_tri)[-1]
    mode = min(max(mode, lo), hi)
    rng = np.random.default_rng(seed)
    npm = None
    if npm_tri is None and corr is None:
        lg = rng.normal(log_g_mean * horizon_years, log_g_sd * math.sqrt(horizon_years), n)
        per = rng.triangular(lo, mode, hi, n) if hi > lo else np.full(n, lo)
        factor = 1.0
    else:
        from scipy.special import ndtr
        k = 3 if npm_tri is not None else 2
        c = np.eye(k) if corr is None else np.asarray(corr, dtype=float)[:k, :k]
        z = rng.standard_normal((n, k)) @ np.linalg.cholesky(c).T
        lg = log_g_mean * horizon_years + log_g_sd * math.sqrt(horizon_years) * z[:, 0]
        per = tri_ppf(ndtr(z[:, 1]), lo, mode, hi)
        factor = 1.0
        if npm_tri is not None:
            a, m, b = sorted(npm_tri)[0], npm_tri[1], sorted(npm_tri)[-1]
            npm = tri_ppf(ndtr(z[:, 2]), a, min(max(m, a), b), b)
            factor = npm / float(npm_base)
    g = np.expm1(lg)
    vals = ni_100m * np.exp(lg) * per * factor * KRW_PER_100M / shares
    rows = []
    for k in sorted({c for c in checkpoints if 0 < c <= n} | {n}):
        s = vals[:k]
        rows.append({"n": k, "P10": float(np.quantile(s, 0.1)), "P50": float(np.quantile(s, 0.5)),
                     "P90": float(np.quantile(s, 0.9)), "mean": float(s.mean())})
    conv = pd.DataFrame(rows)
    conv["rel_change_p50"] = conv["P50"].pct_change().abs()
    converged = bool(len(conv) < 2 or conv["rel_change_p50"].iloc[-1] <= tolerance)
    return MCResult(vals, g, per, {q: float(np.quantile(vals, q)) for q in quantiles}, conv, converged, seed, npm)
