"""발전자산(태양광) 지분투자 모델 — 판매 경로 3개(한전 CfD · 데이터센터 직접 PPA · 시장 SMP) 비교.

연 단위, 명목, 금액 억원 · 가격 원/kWh · 발전량 GWh.
  발전량_t = MW × 1,000 × 이용률 × 8,760 × (1 − 열화율)^(t−1) ÷ 1e6  [GWh]
  매출_t   = 발전량_t(GWh) × 가격_t(원/kWh) ÷ 100                    [억원]  (1 GWh × 1원/kWh = 0.01억원)
  EBITDA   = 매출 − OPEX,  CFADS = EBITDA − 법인세
  대출     = 목표 DSCR sculpting(pf_model.sculpt, 거치 없음) 과 최대 대출 비율 중 작은 값
  지분 흐름 = −(CAPEX − 대출) at t=0, 이후 CFADS − 원리금
경로별 가격:
  cfd      : 계약가 고정(cfd_term년) → 이후 SMP
  ppa      : PPA 가격 × (1+인상률)^(t−1) (ppa_term년, 해지 전까지) → 해지·만기 후 SMP
  merchant : SMP (+ REC × 가중치, rec_eligible일 때만)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Mapping

import numpy as np

from src.analysis import pf_model as pf

ROUTES = ("cfd", "ppa", "merchant")
HOURS = 8760.0


@dataclass(frozen=True)
class Asset:
    mw: float
    capacity_factor: float
    degradation: float
    capex: float                      # 억원
    opex_pct: float                   # CAPEX 대비 연 비율
    opex_escalation: float
    years: int
    dep_years: int
    tax_brackets: tuple[tuple[float, float], ...]
    tax_local: float


@dataclass(frozen=True)
class Market:
    smp0: float                       # 원/kWh, 1년차
    smp_escalation: float = 0.0
    cfd_price: float = 0.0
    cfd_term: int = 20
    ppa_price: float = 0.0
    ppa_term: int = 20
    ppa_escalation: float = 0.0


@dataclass(frozen=True)
class Debt:
    rate: float
    dscr: float
    gearing: float
    tenor: int


@dataclass
class Result:
    route: str
    gen: np.ndarray                   # GWh
    price: np.ndarray                 # 원/kWh
    revenue: np.ndarray
    ebitda: np.ndarray
    tax: np.ndarray
    cfads: np.ndarray
    ds: np.ndarray
    debt: float
    equity: float
    equity_flows: np.ndarray          # t = 0..N
    dscr: np.ndarray                  # 상환 연도
    info: dict = field(default_factory=dict)

    @property
    def irr(self) -> float | None:
        return pf.irr(self.equity_flows, periods_per_year=1)

    @property
    def moic(self) -> float:
        return float(np.clip(self.equity_flows[1:], 0, None).sum() / self.equity) if self.equity > 0 else math.nan

    @property
    def gearing(self) -> float:
        return self.debt / (self.debt + self.equity)

    @property
    def min_dscr(self) -> float:
        d = self.dscr[np.isfinite(self.dscr)]
        return float(d.min()) if d.size else math.nan

    def exit_irr(self, year: int, buyer_return: float) -> tuple[float | None, float]:
        """year년 말 매각: 매각가 = 이후 지분 흐름을 buyer_return으로 할인한 값. (IRR, 매각가)."""
        f = self.equity_flows
        rest = f[year + 1:]
        price = float((rest / (1 + buyer_return) ** np.arange(1, len(rest) + 1)).sum())
        g = f[:year + 1].copy()
        g[-1] += price
        return pf.irr(g, periods_per_year=1), price


def generation(a: Asset, cf_path: np.ndarray | None = None) -> np.ndarray:
    t = np.arange(a.years)
    cf = a.capacity_factor if cf_path is None else cf_path
    return a.mw * 1000 * cf * HOURS * (1 - a.degradation) ** t / 1e6


def smp_path(m: Market, years: int) -> np.ndarray:
    return m.smp0 * (1 + m.smp_escalation) ** np.arange(years)


def price_path(route: str, m: Market, years: int, smp: np.ndarray | None = None, default_year: int | None = None) -> np.ndarray:
    """default_year: PPA 해지 연도(1부터, 그 해부터 SMP). None이면 해지 없음."""
    s = smp_path(m, years) if smp is None else np.asarray(smp, float)
    t = np.arange(years)
    if route == "cfd":
        return np.where(t < m.cfd_term, m.cfd_price, s)
    if route == "ppa":
        end = m.ppa_term if default_year is None else min(m.ppa_term, default_year - 1)
        return np.where(t < end, m.ppa_price * (1 + m.ppa_escalation) ** t, s)
    if route == "merchant":
        return s.copy()
    raise ValueError(route)


def opex(a: Asset) -> np.ndarray:
    return a.capex * a.opex_pct * (1 + a.opex_escalation) ** np.arange(a.years)


def taxes(a: Asset, ebitda: np.ndarray, interest: np.ndarray) -> np.ndarray:
    """누진 법인세 × (1 + 지방세), 결손금 이월(기한 무시)."""
    dep = np.where(np.arange(a.years) < a.dep_years, a.capex / a.dep_years, 0.0)
    base, nol, out = ebitda - dep - interest, 0.0, np.zeros(a.years)
    for i, b in enumerate(base):
        b2 = b - nol
        if b2 <= 0:
            nol = -b2
            continue
        nol = 0.0
        out[i] = pf.progressive_tax(b2, a.tax_brackets, a.tax_local)
    return out


def size_debt(a: Asset, ebitda: np.ndarray, d: Debt, iters: int = 30) -> tuple[float, np.ndarray, np.ndarray]:
    """sculpting(거치 0) + 최대 대출 비율 캡. 이자 → 세금 → CFADS 순환은 반복으로 수렴. (대출, 원리금[N], 세금)."""
    interest = np.zeros(a.years)
    debt, ds = 0.0, np.zeros(a.years)
    for _ in range(iters):
        tax = taxes(a, ebitda, interest)
        cfads = ebitda - tax
        b, ds_t = pf.sculpt(cfads, d.rate, d.dscr, d.tenor, 0)
        cap = a.capex * d.gearing
        if b > cap and b > 0:
            ds_t = ds_t * cap / b
            b = cap
        new_int = np.zeros(a.years)
        if b > 0:
            sch = pf.amortize(b, ds_t, d.rate)
            new_int[:d.tenor] = sch["interest"].to_numpy()
        ds = np.zeros(a.years)
        ds[:d.tenor] = ds_t
        if np.allclose(new_int, interest, atol=1e-7) and abs(b - debt) < 1e-7:
            debt, interest = b, new_int
            break
        debt, interest = b, new_int
    return debt, ds, taxes(a, ebitda, interest)


def run(route: str, a: Asset, m: Market, d: Debt, *, smp: np.ndarray | None = None, cf_path: np.ndarray | None = None,
        default_year: int | None = None, fixed_debt: tuple[float, np.ndarray] | None = None) -> Result:
    """fixed_debt=(대출, 원리금): 스트레스·몬테카를로에서 대출을 기준 sizing으로 고정."""
    gen = generation(a, cf_path)
    price = price_path(route, m, a.years, smp, default_year)
    rev = gen * price / 100.0
    ebitda = rev - opex(a)
    if fixed_debt is None:
        debt, ds, tax = size_debt(a, ebitda, d)
    else:
        debt, ds = fixed_debt
        interest = np.zeros(a.years)
        if debt > 0:
            interest[:d.tenor] = pf.amortize(debt, ds[:d.tenor], d.rate)["interest"].to_numpy()
        tax = taxes(a, ebitda, interest)
    cfads = ebitda - tax
    equity = a.capex - debt
    flows = np.concatenate([[-equity], cfads - ds])
    with np.errstate(divide="ignore", invalid="ignore"):
        dscr = np.where(ds > 1e-9, cfads / ds, np.nan)
    return Result(route, gen, price, rev, ebitda, tax, cfads, ds, debt, equity, flows, dscr)


# ---------------------------------------------------------------------------
# 역산·손익분기
# ---------------------------------------------------------------------------
def capex_from_lcoe(mw: float, cf: float, degradation: float, years: int, lcoe: float, rate: float,
                    opex_pct: float, opex_esc: float) -> float:
    """LCOE = [CAPEX + Σ OPEX_t/(1+r)^t] ÷ Σ 발전량_t/(1+r)^t 를 CAPEX에 대해 풂 (OPEX = CAPEX × 비율). 억원."""
    t = np.arange(1, years + 1)
    disc = (1 + rate) ** -t
    gen = mw * 1000 * cf * HOURS * (1 - degradation) ** (t - 1) / 1e6      # GWh
    g = float((gen * disc).sum()) * lcoe / 100.0                            # 억원
    o = float((opex_pct * (1 + opex_esc) ** (t - 1) * disc).sum())
    return g / (1 + o)


def lcoe(a: Asset, rate: float) -> float:
    """세전 단순 LCOE(원/kWh) = [CAPEX + Σ OPEX_t/(1+r)^t] ÷ Σ 발전량_t/(1+r)^t — 사업비의 교차 확인용."""
    t = np.arange(1, a.years + 1)
    disc = (1 + rate) ** -t
    return float((a.capex + (opex(a) * disc).sum()) / (generation(a) * disc).sum() * 100.0)


def solve(f, lo: float, hi: float, target: float, tol: float = 1e-6) -> float | None:
    """f(x) = target 이분법 (f 단조 증가 가정)."""
    flo, fhi = f(lo) - target, f(hi) - target
    if not (math.isfinite(flo) and math.isfinite(fhi)) or flo * fhi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = f(mid) - target
        if abs(hi - lo) < tol:
            break
        if fm * flo > 0:
            lo, flo = mid, fm
        else:
            hi = mid
    return (lo + hi) / 2


def expected_npv_ppa(a: Asset, m: Market, d: Debt, hazard: float, rate: float, sizing: tuple[float, np.ndarray]) -> float:
    """연 해지 확률 hazard(기하분포, PPA 기간 안)일 때 지분 NPV 기대값 @rate. 대출은 해지 없는 sizing으로 고정."""
    T = m.ppa_term
    probs, total = [], 0.0
    surv = 1.0
    for y in range(1, T + 1):
        p = surv * hazard
        probs.append((y, p))
        surv *= 1 - hazard
    probs.append((None, surv))
    disc = (1 + rate) ** -np.arange(a.years + 1)
    for y, p in probs:
        r = run("ppa", a, m, d, default_year=y, fixed_debt=sizing)
        total += p * float((r.equity_flows * disc).sum())
    return total


def npv(flows: np.ndarray, rate: float) -> float:
    return float((np.asarray(flows) / (1 + rate) ** np.arange(len(flows))).sum())


# ---------------------------------------------------------------------------
# 몬테카를로
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MCSpec:
    n: int
    seed: int
    smp_sigma: float
    smp_phi: float
    cf_sd_annual: float
    cf_sd_resource: float
    hazard: float                     # PPA 연 해지 확률


def simulate(a: Asset, m: Market, debts: Mapping[str, Debt], sizing: Mapping[str, tuple[float, np.ndarray]],
             spec: MCSpec) -> dict[str, np.ndarray]:
    """경로별 지분 IRR 표본. 같은 난수(SMP·발전량)를 세 경로에 공통 적용 → 차이는 계약 구조에서만 나온다."""
    rng = np.random.default_rng(spec.seed)
    N, Y = spec.n, a.years
    eps = rng.standard_normal((N, Y))
    x = np.zeros((N, Y))
    x[:, 0] = eps[:, 0] * spec.smp_sigma / math.sqrt(max(1 - spec.smp_phi ** 2, 1e-9))
    for t in range(1, Y):
        x[:, t] = spec.smp_phi * x[:, t - 1] + spec.smp_sigma * eps[:, t]
    base = smp_path(m, Y)
    smp = base * np.exp(x - 0.5 * spec.smp_sigma ** 2 / max(1 - spec.smp_phi ** 2, 1e-9))   # 평균 보존
    cf = a.capacity_factor * (1 + spec.cf_sd_resource * rng.standard_normal((N, 1))) * (1 + spec.cf_sd_annual * rng.standard_normal((N, Y)))
    cf = np.clip(cf, 0.01, None)
    dflt = rng.geometric(spec.hazard, N) if spec.hazard > 0 else np.full(N, 10 ** 6)
    out = {k: np.full(N, np.nan) for k in ROUTES}
    for i in range(N):
        for k in ROUTES:
            dy = int(dflt[i]) if (k == "ppa" and dflt[i] <= m.ppa_term) else None
            r = run(k, a, m, debts[k], smp=smp[i], cf_path=cf[i], default_year=dy, fixed_debt=sizing[k])
            v = r.irr
            out[k][i] = v if v is not None else -1.0
    out["_default"] = np.where(dflt <= m.ppa_term, dflt, 0)
    return out


def parse_brackets(s: str) -> tuple[tuple[float, float], ...]:
    out = []
    for part in str(s).split(","):
        hi, r = part.split(":")
        out.append((math.inf if hi.strip() == "inf" else float(hi), float(r) / 100))
    return tuple(out)
