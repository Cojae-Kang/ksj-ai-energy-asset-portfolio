"""데이터센터 PF 모델 엔진 (케이스 공용, 순수 함수 — 네트워크·파일 입출력 없음).

시간축: 건설기간은 분기(FC = 0분기), 운영기간은 연 단위(COD 이후 1년차 = COD + 4분기 시점의 현금흐름).
금액 단위: 입력 money_scale로 정한다. 원화 케이스 = KRW 억원(원 ÷ 1e8), 달러 케이스 = USD mn(USD ÷ 1e6).

흐름
  1) 운영: 가동률(사전 임대율에서 수요 성장률로 램프업, 안정화 가동률 상한) × 임대료(kW·월) → 매출
     − 고정 OPEX(설치 kW 기준) + 전력비 순액(패스스루 비율 < 100%일 때만 발생) = EBITDA
     − 법인세(감가상각·이자 공제, 결손금 이월) = CFADS
  2) 대출 한도(Debt sizing) = min(목표 DSCR 기반 sculpting 한도, 최대 대출 비율 × 총사업비)
     sculpting: 상환기간 원리금 = CFADS ÷ 목표 DSCR, 거치기간(이자만)에도 DSCR ≥ 목표
     최대 대출 비율이 묶이면 같은 모양으로 축소(유효 DSCR > 목표)
  3) 건설 자금: 분기별 CAPEX(S-curve) + 건설이자(IDC, 자본화) + 초기 DSRA를 대출·자기자본 비율대로 조달
  4) Waterfall: CFADS → 이자 → 원금 → DSRA 적립(다음 해 원리금 × 개월/12) → 배당
     (거치기간 이자를 자본화하면 그 기간 배당은 잠그고 거치 종료 다음 해에 해제)
  5) 지표: 최소·평균 DSCR, LLCR(COD), Project IRR(무차입 세후), Equity IRR, 회수기간, 계약 현금흐름만의 DSCR

스트레스(fixed 모드): 대출은 기준 케이스에서 정해진 금액·원금 스케줄을 유지하고(대주가 FC에 확정),
현금흐름만 바뀐다. 단 CAPEX 증가·건설 지연의 추가 자금은 기준 대출 비율대로 조달(대출·상환 스케줄 비례 확대).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Callable

import numpy as np
import pandas as pd

QUARTERS_PER_YEAR = 4


# ---------------------------------------------------------------------------
# 입력
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PFInputs:
    """한 케이스(한 단계)의 PF 입력. 비율은 소수(0.025 = 2.5%)."""
    mw: float                          # IT 부하 기준 용량 (MW)
    capex_per_mw: float                # 금액 단위 / MW (억원 또는 USD mn)
    construction_quarters: int
    rent_per_kw_month: float           # 원 또는 USD / kW·월 (COD 연도 기준)
    money_scale: float                 # 원→억원 1e8, USD→USD mn 1e6
    rent_escalation: float
    prelease: float                    # COD 시점 사전 임대율 (장기 책임임대 계약분)
    stabilized_occupancy: float
    ramp_growth: float                 # 연 수요 성장률 (시나리오) — ramp_years가 없을 때 램프업 속도
    ramp_elasticity: float             # 임차 부하 성장 = 수요 성장 × 탄력성
    opex_per_kw_year: float            # 원 또는 USD / 설치 kW·년 (전력비 제외, 고정분)
    opex_escalation: float
    tax_rate: float                    # 단일 세율 (tax_brackets가 있으면 무시)
    dep_years: int | None              # None = 감가상각 미반영 (법인세 보수적으로 과대)
    operating_years: int
    base_rate_construction: float
    base_rate_term: float
    margin: float
    target_dscr: float
    max_gearing: float                 # 대출 ÷ 총사업비(CAPEX + IDC + 초기 DSRA)
    tenor_years: int                   # COD부터 만기까지 (거치 포함)
    grace_years: int                   # COD 이후 원금 거치(이자만)
    dsra_months: float
    discount_rate: float | None        # 자기자본 할인율 (NPV·옵션). None이면 NPV 생략
    power_passthrough: float = 1.0     # 전력비 중 임차인 부담 비율
    power_price: float | None = None   # 원 또는 USD / kWh
    pue: float | None = None
    it_load_factor: float | None = None
    exit_cap_rate: float | None = None  # 잔존가치 = 마지막 다음 해 EBITDA ÷ cap rate (없으면 잔존가치 제외)
    drawdown: str = "s_curve"
    grace_interest: str = "paid"       # 거치기간 이자: paid(현금 지급, DSCR 검사) | capitalized(원금 가산, 램프업 구간)
    opex_ratio: float | None = None    # OPEX = 비율 × 안정화 매출(1년차 임대료 기준), 이후 opex_escalation으로 증가
    ramp_years: float | None = None    # 선형 램프업: 1년차 사전 임대율 → (ramp_years+1)년차 안정화 가동률
    lease_term_years: int | None = None   # 사전 임대 계약 기간 (None = 운영기간 전체)
    tax_brackets: tuple | None = None  # 누진세율 ((상한, 세율), …) 금액 단위 기준, 마지막 상한 = inf
    tax_surcharge: float = 0.0         # 국세 대비 부가세율 (한국 지방소득세 = 0.10)

    def __post_init__(self):
        if self.construction_quarters < 1 or self.operating_years < 1 or self.tenor_years < 1:
            raise ValueError("건설 분기·운영기간·만기는 1 이상")
        if not 0 <= self.grace_years < self.tenor_years:
            raise ValueError("거치기간은 0 이상, 만기 미만")
        if self.tenor_years > self.operating_years:
            raise ValueError("대출 만기는 운영기간 이내")
        if self.target_dscr <= 0 or not 0 < self.max_gearing < 1:
            raise ValueError("목표 DSCR > 0, 최대 대출 비율은 0~1")
        if self.grace_interest not in ("paid", "capitalized"):
            raise ValueError("grace_interest = paid | capitalized")

    @property
    def kw(self) -> float:
        return self.mw * 1000.0

    @property
    def capex_total(self) -> float:
        return self.mw * self.capex_per_mw

    @property
    def term_rate(self) -> float:
        return self.base_rate_term + self.margin

    @property
    def construction_rate(self) -> float:
        return self.base_rate_construction + self.margin

    def power_modeled(self) -> bool:
        return None not in (self.power_price, self.pue, self.it_load_factor)


@dataclass(frozen=True)
class Stress:
    rent_mult: float = 1.0
    occ_mult: float = 1.0
    prelease: float | None = None      # 사전 임대율 대체값
    capex_mult: float = 1.0
    rate_shift: float = 0.0            # 기준금리 이동 (0.01 = +100bp), 건설·운영 모두
    delay_quarters: int = 0            # 준공 지연 (CAPEX 집행 완료 후 COD까지 추가 분기)
    passthrough: float | None = None   # 전력비 패스스루 비율 대체값
    opex_mult: float = 1.0

    def label(self) -> str:
        parts = [f"{k}={v}" for k, v in self.__dict__.items() if v not in (None, 1.0, 0.0, 0)]
        return ", ".join(parts) or "base"


BASE = Stress()


# ---------------------------------------------------------------------------
# 구성 요소
# ---------------------------------------------------------------------------
def drawdown_weights(n: int, kind: str = "s_curve") -> np.ndarray:
    """분기별 CAPEX 집행 비중 (합 1). s_curve: 누적 (1 − cos πx)/2 → 중간이 두꺼운 종 모양."""
    if n < 1:
        raise ValueError("n >= 1")
    if kind == "linear":
        return np.full(n, 1.0 / n)
    if kind != "s_curve":
        raise ValueError(f"알 수 없는 집행 곡선: {kind}")
    x = np.arange(n + 1) / n
    cum = (1 - np.cos(np.pi * x)) / 2
    return np.diff(cum)


def occupancy_path(prelease: float, stabilized: float, growth: float, elasticity: float, years: int,
                   occ_mult: float = 1.0) -> np.ndarray:
    """연 평균 가동률: 1년차 = 사전 임대율, 이후 임차 부하가 (1 + 수요 성장률 × 탄력성)로 증가, 안정화 가동률 상한."""
    t = np.arange(years)
    path = np.minimum(stabilized, prelease * (1 + growth * elasticity) ** t)
    return np.clip(path * occ_mult, 0.0, 1.0)


def occupancy(inp: PFInputs, st: "Stress", years: int) -> np.ndarray:
    """케이스 가동률 경로: ramp_years가 있으면 선형 램프업, 없으면 수요 성장률 램프업."""
    pre = inp.prelease if st.prelease is None else st.prelease
    if inp.ramp_years is None:
        return occupancy_path(pre, inp.stabilized_occupancy, inp.ramp_growth, inp.ramp_elasticity, years, st.occ_mult)
    t = np.arange(years, dtype=float)
    frac = np.minimum(1.0, t / inp.ramp_years) if inp.ramp_years > 0 else np.ones(years)
    path = pre + (max(inp.stabilized_occupancy, pre) - pre) * frac
    return np.clip(path * st.occ_mult, 0.0, 1.0)


def growth_to_stabilize(prelease: float, stabilized: float, growth: float, elasticity: float) -> float:
    """사전 임대율 → 안정화 가동률 도달 연수 (성장률 0 이하이면 inf)."""
    g = growth * elasticity
    if prelease >= stabilized:
        return 0.0
    if g <= 0 or prelease <= 0:
        return math.inf
    return math.log(stabilized / prelease) / math.log(1 + g)


def operations(inp: PFInputs, st: Stress = BASE) -> pd.DataFrame:
    """연도별 운영 현금흐름 (금액 단위 = money_scale). contracted_* = 사전 임대 계약분만."""
    n = inp.operating_years
    pre = inp.prelease if st.prelease is None else st.prelease
    occ = occupancy(inp, st, n)
    t = np.arange(n)
    rent = inp.rent_per_kw_month * st.rent_mult * (1 + inp.rent_escalation) ** t
    rev = occ * inp.kw * rent * 12 / inp.money_scale
    contracted_occ = np.minimum(np.full(n, pre), occ)        # 장기 책임임대
    if inp.lease_term_years is not None:
        contracted_occ = np.where(t < inp.lease_term_years, contracted_occ, 0.0)
    rev_c = contracted_occ * inp.kw * rent * 12 / inp.money_scale
    opex0 = inp.kw * inp.opex_per_kw_year
    if inp.opex_ratio is not None:                           # 계획 기준 비용: 임대료 스트레스와 무관
        opex0 += inp.opex_ratio * inp.stabilized_occupancy * inp.kw * inp.rent_per_kw_month * 12
    opex = np.full(n, opex0) * (1 + inp.opex_escalation) ** t / inp.money_scale * st.opex_mult
    pt = inp.power_passthrough if st.passthrough is None else st.passthrough
    if inp.power_modeled():
        kwh = occ * inp.kw * inp.it_load_factor * 8760 * inp.pue
        power_cost = kwh * inp.power_price / inp.money_scale
        power_cost_c = contracted_occ * inp.kw * inp.it_load_factor * 8760 * inp.pue * inp.power_price / inp.money_scale
    else:
        power_cost = power_cost_c = np.zeros(n)
    net_power = -(1 - pt) * power_cost                       # 패스스루 100%면 0
    net_power_c = -(1 - pt) * power_cost_c
    return pd.DataFrame({
        "year": t + 1, "occupancy": occ, "contracted_occupancy": contracted_occ, "rent": rent,
        "revenue": rev, "revenue_contracted": rev_c, "opex": opex, "power_cost": power_cost,
        "power_recovery": pt * power_cost, "net_power": net_power,
        "ebitda": rev - opex + net_power, "ebitda_contracted": rev_c - opex + net_power_c,
    })


def progressive_tax(base: float, brackets, surcharge: float = 0.0) -> float:
    """누진세: brackets = ((상한, 세율), …). 국세 × (1 + surcharge). 예) 한국 2026~: 2억 10%, 200억 20%, 3,000억 22%, 초과 25%."""
    tax, lo = 0.0, 0.0
    for hi, rate in brackets:
        if base <= lo:
            break
        tax += (min(base, hi) - lo) * rate
        lo = hi
    return tax * (1 + surcharge)


def tax_schedule(ebit_before_interest: np.ndarray, interest: np.ndarray, rate: float, brackets=None,
                 surcharge: float = 0.0) -> np.ndarray:
    """법인세 = 세율(또는 누진세율) × max(0, 과세소득 − 이월결손금). 결손금은 무기한 이월 (단순화)."""
    nol, out = 0.0, np.zeros(len(ebit_before_interest))
    for i, (e, it) in enumerate(zip(ebit_before_interest, interest)):
        taxable = e - it
        if taxable <= 0:
            nol += -taxable
            continue
        use = min(nol, taxable)
        nol -= use
        out[i] = progressive_tax(taxable - use, brackets, surcharge) if brackets else rate * (taxable - use)
    return out


def inp_tax(inp: PFInputs, ebit: np.ndarray, interest: np.ndarray) -> np.ndarray:
    return tax_schedule(ebit, interest, inp.tax_rate, inp.tax_brackets, inp.tax_surcharge)


def depreciation(cost: float, years: int | None, horizon: int) -> np.ndarray:
    d = np.zeros(horizon)
    if years:
        d[:min(years, horizon)] = cost / years
    return d


@dataclass
class Construction:
    quarters: pd.DataFrame          # quarter, capex, idc, dsra, uses, debt_draw, equity, debt_balance
    capex: float
    idc: float
    dsra_initial: float
    uses: float
    debt: float
    equity: float
    debt_share: float
    cod_quarter: int


def _construction_arrays(inp: PFInputs, st: Stress, debt_share: float, dsra_initial: float) -> dict[str, np.ndarray]:
    q = inp.construction_quarters
    cod = q + st.delay_quarters
    capex_q = np.zeros(cod)
    capex_q[:q] = drawdown_weights(q, inp.drawdown) * inp.capex_total * st.capex_mult
    r = (inp.construction_rate + st.rate_shift) / QUARTERS_PER_YEAR
    idc, dsra, draw, bal = np.zeros(cod), np.zeros(cod), np.zeros(cod), np.zeros(cod)
    dsra[-1] = dsra_initial
    b = 0.0
    for i in range(cod):
        idc[i] = b * r
        draw[i] = debt_share * (capex_q[i] + idc[i] + dsra[i])
        b += draw[i]
        bal[i] = b
    uses = capex_q + idc + dsra
    return {"capex": capex_q, "idc": idc, "dsra": dsra, "uses": uses, "debt_draw": draw, "equity": uses - draw,
            "debt_balance": bal}


def construction(inp: PFInputs, st: Stress, debt_share: float, dsra_initial: float) -> Construction:
    """분기별 건설 자금. 각 분기 소요(CAPEX + IDC [+ COD에 초기 DSRA])를 대출 debt_share, 나머지 자기자본으로 조달.

    IDC = 분기 초 대출 잔액 × (기준금리 + 가산금리) ÷ 4, 자본화. 지연 분기는 CAPEX 없이 IDC만 발생.
    """
    a = _construction_arrays(inp, st, debt_share, dsra_initial)
    df = pd.DataFrame({"quarter": np.arange(len(a["capex"])), **a})
    return Construction(df, float(a["capex"].sum()), float(a["idc"].sum()), dsra_initial, float(a["uses"].sum()),
                        float(a["debt_draw"].sum()), float(a["equity"].sum()), debt_share, len(a["capex"]))


def _solve_share(inp: PFInputs, st: Stress, debt_target: float, dsra0: float) -> Construction:
    """대출 총액(= Σ draw)이 debt_target이 되는 조달 비율을 이분법으로 찾는다 (IDC가 비율에 따라 변하므로)."""
    lo, hi = 0.0, 0.999
    if _construction_arrays(inp, st, hi, dsra0)["debt_draw"].sum() < debt_target:
        return construction(inp, st, hi, dsra0)
    for _ in range(80):
        mid = (lo + hi) / 2
        if _construction_arrays(inp, st, mid, dsra0)["debt_draw"].sum() < debt_target:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-13:
            break
    return construction(inp, st, (lo + hi) / 2, dsra0)


# ---------------------------------------------------------------------------
# 대출 한도: sculpting
# ---------------------------------------------------------------------------
def sculpt(cfads: np.ndarray, rate: float, dscr: float, tenor: int, grace: int,
           grace_interest: str = "paid") -> tuple[float, np.ndarray]:
    """목표 DSCR 기반 대출 한도와 연도별 원리금(길이 = tenor).

    상환기간(grace+1..tenor) 원리금 = CFADS ÷ DSCR → 거치 종료 시점 잔액 = 그 현재가치(B).
    paid: 거치기간 이자를 현금으로 내므로 대출 = min(B, min(CFADS_거치) ÷ (DSCR × 금리)).
    capitalized: 거치기간 이자를 원금에 가산(원리금 0) → 대출 = B ÷ (1 + 금리)^거치.
    """
    cf = np.asarray(cfads[:tenor], dtype=float)
    amort = np.arange(grace, tenor)
    w = np.maximum(cf[amort], 0.0) / dscr
    disc = (1 + rate) ** -(amort - grace + 1.0)
    b_grace = float((w * disc).sum())
    ds = np.zeros(tenor)
    if grace_interest == "capitalized":
        debt = b_grace / (1 + rate) ** grace
        if b_grace > 0:
            ds[grace:] = w
        return debt, ds
    cap = math.inf
    if grace > 0:
        cap = float(np.min(np.maximum(cf[:grace], 0.0))) / (dscr * rate) if rate > 0 else math.inf
    debt = max(min(b_grace, cap), 0.0)
    ds[:grace] = debt * rate
    if b_grace > 0:
        ds[grace:] = w * debt / b_grace
    return debt, ds


def amortize(debt: float, ds: np.ndarray, rate: float) -> pd.DataFrame:
    """원리금 스케줄 → 이자·원금·잔액 (연말). 마지막 해 잔액 오차는 원금으로 정리."""
    bal, rows = debt, []
    for t, d in enumerate(ds):
        interest = bal * rate
        principal = d - interest
        if t == len(ds) - 1:
            principal = bal
        rows.append({"year": t + 1, "opening": bal, "interest": interest, "principal": principal,
                     "debt_service": interest + principal, "closing": bal - principal})
        bal -= principal
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 결과
# ---------------------------------------------------------------------------
@dataclass
class PFResult:
    inp: PFInputs
    stress: Stress
    ops: pd.DataFrame                 # 운영 + 세금 + CFADS + 상환 + waterfall (연)
    cons: Construction
    debt: float
    sculpt_debt: float
    gearing_debt: float
    binding: str                      # "dscr" | "gearing" | "fixed"
    effective_dscr: float
    min_dscr: float
    avg_dscr: float
    llcr: float
    min_dscr_contracted: float
    project_irr: float | None
    equity_irr: float | None
    equity_npv: float
    payback_years: float | None       # FC부터
    equity_flows: pd.DataFrame        # quarter, flow
    project_flows: pd.DataFrame
    warnings: list[str] = field(default_factory=list)

    @property
    def gearing(self) -> float:
        return self.debt / self.cons.uses if self.cons.uses else float("nan")

    @property
    def debt_per_mw(self) -> float:
        return self.debt / self.inp.mw

    def summary(self) -> dict:
        return {"debt": self.debt, "gearing": self.gearing, "binding": self.binding, "min_dscr": self.min_dscr,
                "avg_dscr": self.avg_dscr, "llcr": self.llcr, "project_irr": self.project_irr,
                "equity_irr": self.equity_irr, "payback_years": self.payback_years, "uses": self.cons.uses,
                "equity": self.cons.equity, "idc": self.cons.idc, "min_dscr_contracted": self.min_dscr_contracted}


def irr(flows: np.ndarray, periods_per_year: int = QUARTERS_PER_YEAR) -> float | None:
    """분기 현금흐름의 연 환산 IRR. 부호 변화가 없거나 해가 없으면 None."""
    from scipy.optimize import brentq

    f = np.asarray(flows, dtype=float)
    if not (np.any(f < 0) and np.any(f > 0)):
        return None
    t = np.arange(len(f))

    def npv(r):
        return float((f / (1 + r) ** t).sum())
    lo, hi = -0.99, 1.0
    if npv(lo) * npv(hi) > 0:
        hi = 10.0
        if npv(lo) * npv(hi) > 0:
            return None
    r_q = brentq(npv, lo, hi, xtol=1e-12, maxiter=500)
    return (1 + r_q) ** periods_per_year - 1


def npv_annual_rate(flows: np.ndarray, rate: float) -> float:
    t = np.arange(len(flows)) / QUARTERS_PER_YEAR
    return float((np.asarray(flows) / (1 + rate) ** t).sum())


def payback(flows: np.ndarray) -> float | None:
    """누적 현금흐름이 0 이상이 되는 시점 (연, 분기 선형보간)."""
    cum = np.cumsum(flows)
    for i in range(1, len(cum)):
        if cum[i] >= 0 > cum[i - 1]:
            frac = -cum[i - 1] / (cum[i] - cum[i - 1])
            return (i - 1 + frac) / QUARTERS_PER_YEAR
    return None


def _cfads(inp: PFInputs, ops: pd.DataFrame, dep: np.ndarray, interest: np.ndarray, col: str = "ebitda") -> np.ndarray:
    ebit = ops[col].to_numpy() - dep
    return ops[col].to_numpy() - inp_tax(inp, ebit, interest)


def _pad(x: np.ndarray, n: int) -> np.ndarray:
    out = np.zeros(n)
    out[:len(x)] = x[:n]
    return out


def run(inp: PFInputs, st: Stress = BASE, fixed: PFResult | None = None, max_iter: int = 60) -> PFResult:
    """기준(sizing) 모드: fixed=None → 대출 한도 산정. 스트레스 모드: fixed=기준 결과 → 대출 스케줄 고정."""
    n, tenor, grace = inp.operating_years, inp.tenor_years, inp.grace_years
    rate = inp.term_rate + st.rate_shift
    ops = operations(inp, st)
    warnings: list[str] = []
    if fixed is None:
        interest = np.zeros(n)
        debt = sculpt_debt = gearing_debt = 0.0
        ds = np.zeros(tenor)
        dsra0 = 0.0
        cons = construction(inp, st, 0.0, 0.0)
        for _ in range(max_iter):
            dep = depreciation(cons.capex + cons.idc, inp.dep_years, n)
            cf = _cfads(inp, ops, dep, interest)
            sculpt_debt, ds_s = sculpt(cf, rate, inp.target_dscr, tenor, grace, inp.grace_interest)
            # 최대 대출 비율 한도: 조달 비율 = max_gearing일 때의 대출 총액 (초기 DSRA는 직전 반복값)
            cons_g = construction(inp, st, inp.max_gearing, dsra0)
            gearing_debt = cons_g.debt
            new_debt = min(sculpt_debt, gearing_debt)
            ds = ds_s * (new_debt / sculpt_debt) if sculpt_debt > 0 else np.zeros(tenor)
            dsra_new = inp.dsra_months / 12 * (ds[0] if tenor else 0.0)
            cons = _solve_share(inp, st, new_debt, dsra_new)
            sched = amortize(cons.debt, ds * (cons.debt / new_debt) if new_debt > 0 else ds, rate)
            new_interest = _pad(sched["interest"].to_numpy(), n)
            done = abs(new_debt - debt) <= 1e-9 * max(1.0, abs(new_debt)) and abs(dsra_new - dsra0) <= 1e-9 * max(1.0, dsra_new)
            debt, interest, dsra0 = new_debt, new_interest, dsra_new
            if done:
                break
        else:
            warnings.append("sizing 반복 미수렴")
        binding = "dscr" if sculpt_debt <= gearing_debt else "gearing"
        debt = cons.debt                                         # sched = 마지막 반복의 상환 스케줄
        if debt <= 1e-9 * max(cons.uses, 1.0):                  # 사실상 대출 불가 → 0으로 정리
            debt, cons = 0.0, construction(inp, st, 0.0, 0.0)
            sched = amortize(0.0, np.zeros(tenor), rate)
            warnings.append("대출 한도 0: 목표 DSCR을 만족하는 원리금 상환 여력 없음")
        eff_dscr = inp.target_dscr * (sculpt_debt / debt) if debt > 0 else float("inf")
    else:
        base = fixed
        # 추가 자금(CAPEX 증가·지연 IDC)은 기준 조달 비율대로 → 대출 금액·원금 스케줄 비례 확대
        cons = construction(inp, st, base.cons.debt_share, base.cons.dsra_initial)
        factor = cons.debt / base.debt if base.debt else 0.0
        principal = base.ops["principal"].to_numpy()[:tenor] * factor
        bal, rows = cons.debt, []
        for t in range(tenor):
            it = bal * rate
            pr = principal[t] if t < tenor - 1 else bal
            rows.append({"year": t + 1, "opening": bal, "interest": it, "principal": pr, "debt_service": it + pr,
                         "closing": bal - pr})
            bal -= pr
        sched = pd.DataFrame(rows)
        debt, sculpt_debt, gearing_debt, binding = cons.debt, base.sculpt_debt, base.gearing_debt, "fixed"
        eff_dscr = base.effective_dscr

    interest = _pad(sched["interest"].to_numpy(), n)
    principal = _pad(sched["principal"].to_numpy(), n)
    dsv = interest + principal
    dep = depreciation(cons.capex + cons.idc, inp.dep_years, n)
    ebit = ops["ebitda"].to_numpy() - dep
    tax = inp_tax(inp, ebit, interest)
    cfads = ops["ebitda"].to_numpy() - tax
    tax_c = inp_tax(inp, ops["ebitda_contracted"].to_numpy() - dep, interest)
    cfads_c = ops["ebitda_contracted"].to_numpy() - tax_c
    neg_from = grace if inp.grace_interest == "capitalized" else 0     # 이자 자본화 구간의 음수 원금은 설계상 정상
    if (principal[neg_from:tenor] < -1e-9).any():
        warnings.append("일부 연도 원금 음수(원리금 < 이자) — sculpting 결과 잔액 증가 구간 존재")

    # waterfall (이자 자본화 거치기간에는 배당 잠금 → 거치 종료 다음 해에 해제)
    dsra_open = cons.dsra_initial
    lock_bal = 0.0
    lock_years = grace if inp.grace_interest == "capitalized" else 0
    wf = []
    for t in range(n):
        nxt = dsv[t + 1] if t + 1 < n else 0.0
        target = inp.dsra_months / 12 * nxt
        cash = cfads[t] - dsv[t]
        draw = topup = release = shortfall = 0.0
        if cash < 0:
            draw = min(dsra_open, -cash)
            shortfall = -cash - draw
            cash = 0.0
        else:
            topup = min(cash, max(0.0, target - (dsra_open - draw)))
            cash -= topup
        bal_after = dsra_open - draw + topup
        if bal_after > target:
            release = bal_after - target
            bal_after = target
        dist = cash + release
        lock_in = lock_out = 0.0
        if t < lock_years:
            lock_in, dist = dist, 0.0
        elif lock_bal > 0:
            lock_out = lock_bal
            dist += lock_out
        lock_bal += lock_in - lock_out
        wf.append({"dsra_open": dsra_open, "dsra_draw": draw, "dsra_topup": topup, "dsra_release": release,
                   "dsra_close": bal_after, "shortfall": shortfall, "lockup_in": lock_in, "lockup_release": lock_out,
                   "distribution": dist})
        dsra_open = bal_after
    wf = pd.DataFrame(wf)
    ops = ops.assign(depreciation=dep, interest=interest, principal=principal, debt_service=dsv, tax=tax,
                     cfads=cfads, cfads_contracted=cfads_c,
                     debt_closing=_pad(sched["closing"].to_numpy(), n), **{c: wf[c].to_numpy() for c in wf})
    with np.errstate(divide="ignore", invalid="ignore"):
        dscr = np.where(dsv[:tenor] > 0, cfads[:tenor] / dsv[:tenor], np.nan)
        dscr_c = np.where(dsv[:tenor] > 0, cfads_c[:tenor] / dsv[:tenor], np.nan)
    ops["dscr"] = _pad(dscr, n)
    ops.loc[ops["year"] > tenor, "dscr"] = np.nan
    min_dscr = float(np.nanmin(dscr)) if np.isfinite(dscr).any() else float("nan")
    avg_dscr = float(np.nanmean(dscr)) if np.isfinite(dscr).any() else float("nan")
    min_dscr_c = float(np.nanmin(dscr_c)) if np.isfinite(dscr_c).any() else float("nan")
    disc = (1 + rate) ** -np.arange(1, tenor + 1)
    llcr = float((cfads[:tenor] * disc).sum() / debt) if debt > 0 else float("nan")
    if ops["shortfall"].sum() > 1e-9:
        warnings.append(f"원리금 부족(DSRA 소진 후) 합계 {ops['shortfall'].sum():,.2f}")

    # 분기 타임라인: 건설 0..cod-1, 운영 t년차 현금흐름 = cod − 1 + 4t 분기 말
    cod = cons.cod_quarter
    horizon = cod + QUARTERS_PER_YEAR * n
    eq = np.zeros(horizon)
    eq[:cod] -= cons.quarters["equity"].to_numpy()
    pj = np.zeros(horizon)
    pj[:cod] -= cons.quarters["capex"].to_numpy()
    dep_u = depreciation(cons.capex, inp.dep_years, n)
    tax_u = inp_tax(inp, ops["ebitda"].to_numpy() - dep_u, np.zeros(n))
    tv = 0.0
    if inp.exit_cap_rate:
        nxt_ebitda = float(ops["ebitda"].iloc[-1]) * (1 + inp.rent_escalation)
        tv = nxt_ebitda / inp.exit_cap_rate
    for t in range(n):
        qi = cod - 1 + QUARTERS_PER_YEAR * (t + 1)
        eq[qi] += ops["distribution"].iloc[t] - ops["shortfall"].iloc[t]
        pj[qi] += ops["ebitda"].iloc[t] - tax_u[t]
    eq[-1] += float(ops["dsra_close"].iloc[-1]) + tv - float(ops["debt_closing"].iloc[-1])
    pj[-1] += tv
    eq_df = pd.DataFrame({"quarter": np.arange(horizon), "flow": eq})
    pj_df = pd.DataFrame({"quarter": np.arange(horizon), "flow": pj})
    return PFResult(inp, st, ops, cons, debt, sculpt_debt, gearing_debt, binding, eff_dscr, min_dscr, avg_dscr, llcr,
                    min_dscr_c, irr(pj), irr(eq),
                    npv_annual_rate(eq, inp.discount_rate) if inp.discount_rate is not None else float("nan"), payback(eq), eq_df, pj_df,
                    warnings)


def interest_cover_cap(r: PFResult) -> float:
    """진단: 매년 이자를 현금으로 내면서 CFADS ≥ 목표 DSCR × 이자를 지키는 최대 대출 (같은 상환 모양, 비례 축소).

    sculpting은 램프업 초기 원리금이 이자보다 작아(음수 원금) 잔액이 늘 수 있다. 실무에서는 램프업 이자 적립·자본화가
    없으면 허용되지 않으므로, 그 제약을 걸었을 때의 한도를 따로 보여준다.
    """
    o = r.ops.iloc[: r.inp.tenor_years]
    it = o["interest"].to_numpy()
    cf = o["cfads"].to_numpy()
    m = it > 1e-12
    if not m.any() or r.debt <= 0:
        return r.debt
    factor = float(np.min(np.maximum(cf[m], 0.0) / (r.inp.target_dscr * it[m])))
    return r.debt * min(1.0, factor)


def negative_amortization_years(r: PFResult) -> list[int]:
    """COD 이후(거치 자본화 구간 제외) 원금이 음수인 연차 — 원리금 < 이자."""
    start = r.inp.grace_years if r.inp.grace_interest == "capitalized" else 0
    o = r.ops.iloc[start: r.inp.tenor_years]
    return [int(y) for y, p in zip(o["year"], o["principal"]) if p < -1e-9]


def stress(base: PFResult, st: Stress) -> PFResult:
    """기준 결과의 대출 스케줄을 고정하고 스트레스 적용."""
    return run(base.inp, st, fixed=base)


# ---------------------------------------------------------------------------
# 검산 (테스트·빌드 요약에서 사용)
# ---------------------------------------------------------------------------
def identity_checks(r: PFResult, tol: float = 1e-6) -> dict[str, float]:
    """회계 항등식 오차 (모두 0에 가까워야 한다).

    sources_uses: 대출 + 자기자본 − 총사업비
    debt_rollforward: 대출 − Σ원금 − 만기 잔액
    cash_waterfall: CFADS + DSRA 인출 + 부족분 + DSRA 해제 + 잠금 해제 − (원리금 + DSRA 적립 + 배당 + 잠금)
    dsra_rollforward: 초기 DSRA + Σ적립 − Σ인출 − Σ해제 − 기말 DSRA
    dscr_definition: max |DSCR − CFADS ÷ 원리금|
    """
    o = r.ops
    tenor = r.inp.tenor_years
    d = o.iloc[:tenor]
    dscr_err = float(np.nanmax(np.abs(d["dscr"] - d["cfads"] / d["debt_service"]))) if len(d) else 0.0
    return {
        "sources_uses": r.cons.debt + r.cons.equity - r.cons.uses,
        "debt_rollforward": r.debt - float(o["principal"].sum()) - float(o["debt_closing"].iloc[-1]),
        "cash_waterfall": float((o["cfads"] + o["dsra_draw"] + o["shortfall"] + o["dsra_release"] + o["lockup_release"]
                                 - (o["debt_service"] + o["dsra_topup"] + o["distribution"] + o["lockup_in"])).abs().max()),
        "lockup_rollforward": float(o["lockup_in"].sum() - o["lockup_release"].sum()),
        "dsra_rollforward": r.cons.dsra_initial + float(o["dsra_topup"].sum() - o["dsra_draw"].sum()
                                                       - o["dsra_release"].sum()) - float(o["dsra_close"].iloc[-1]),
        "dscr_definition": dscr_err,
    }


# ---------------------------------------------------------------------------
# 민감도·손익분기
# ---------------------------------------------------------------------------
STRESS_FIELDS = ("rent_mult", "occ_mult", "prelease", "capex_mult", "rate_shift", "delay_quarters", "opex_mult")


def stressed_metric(base: PFResult, field_: str, value: float, metric: str = "min_dscr") -> float:
    v = int(round(value)) if field_ == "delay_quarters" else value
    r = stress(base, replace(BASE, **{field_: v}))
    return float(getattr(r, metric) if getattr(r, metric) is not None else float("nan"))


def breakeven(base: PFResult, field_: str, level: float, lo: float, hi: float, metric: str = "min_dscr",
              steps: int = 40, near: float | None = None) -> float | None:
    """metric(field=x) = level 이 되는 x (구간 [lo, hi], 격자 탐색 후 이분법). 교차가 여럿이면 near(기준값)에
    가장 가까운 것. 없으면 None."""
    xs = np.linspace(lo, hi, steps + 1)
    if near is not None:
        xs = np.unique(np.append(xs, near))
    if field_ == "delay_quarters":
        xs = np.unique(np.round(xs)).astype(float)
    ys = [stressed_metric(base, field_, x, metric) - level for x in xs]
    roots = []
    for (x0, y0), (x1, y1) in zip(zip(xs, ys), zip(xs[1:], ys[1:])):
        if y0 * y1 >= 0:
            continue
        if field_ == "delay_quarters":
            roots.append(float(x1 if y1 < 0 else x0))
            continue
        a, b, fa = x0, x1, y0
        for _ in range(60):
            m = (a + b) / 2
            fm = stressed_metric(base, field_, m, metric) - level
            if fa * fm <= 0:
                b = m
            else:
                a, fa = m, fm
        roots.append(float((a + b) / 2))
    if not roots:
        return None
    ref = near if near is not None else lo
    return min(roots, key=lambda r: abs(r - ref))


def tornado(base: PFResult, cases: dict[str, tuple[Stress, Stress]], metric: str = "min_dscr") -> pd.DataFrame:
    """변수별 (낮은 쪽, 높은 쪽) 스트레스 → 지표. 범위가 큰 순서."""
    b = getattr(base, metric)
    rows = []
    for name, (lo, hi) in cases.items():
        vl, vh = getattr(stress(base, lo), metric), getattr(stress(base, hi), metric)
        vl = float("nan") if vl is None else vl
        vh = float("nan") if vh is None else vh
        rows.append({"variable": name, "low": vl, "high": vh, "base": b, "span": abs(vh - vl)})
    return pd.DataFrame(rows).sort_values("span", ascending=False).reset_index(drop=True)


def heatmap(base: PFResult, rent_mults: list[float], capex_mults: list[float],
            metric: str = "min_dscr") -> pd.DataFrame:
    """임대료 배수(행) × CAPEX 배수(열) → 지표 (대출 스케줄 고정, 추가 CAPEX는 기준 조달 비율)."""
    data = [[getattr(stress(base, Stress(rent_mult=r, capex_mult=c)), metric) for c in capex_mults] for r in rent_mults]
    return pd.DataFrame(data, index=rent_mults, columns=capex_mults)


# ---------------------------------------------------------------------------
# 무차입 프로젝트 가치 (실물옵션용)
# ---------------------------------------------------------------------------
def project_npv(inp: PFInputs, st: Stress = BASE) -> float:
    """무차입 세후 프로젝트 NPV (FC 시점, 자기자본 할인율). 대출 sizing 없이 빠르게 계산."""
    if inp.discount_rate is None:
        raise ValueError("project_npv: 할인율 필요")
    n = inp.operating_years
    ops = operations(inp, st)
    q = inp.construction_quarters
    cod = q + st.delay_quarters
    capex_q = drawdown_weights(q, inp.drawdown) * inp.capex_total * st.capex_mult
    dep = depreciation(inp.capex_total * st.capex_mult, inp.dep_years, n)
    tax = inp_tax(inp, ops["ebitda"].to_numpy() - dep, np.zeros(n))
    cf = ops["ebitda"].to_numpy() - tax
    t_ops = (cod - 1 + QUARTERS_PER_YEAR * np.arange(1, n + 1)) / QUARTERS_PER_YEAR
    v = float((cf / (1 + inp.discount_rate) ** t_ops).sum())
    if inp.exit_cap_rate:
        tv = float(ops["ebitda"].iloc[-1]) * (1 + inp.rent_escalation) / inp.exit_cap_rate
        v += tv / (1 + inp.discount_rate) ** t_ops[-1]
    v -= float((capex_q / (1 + inp.discount_rate) ** (np.arange(q) / QUARTERS_PER_YEAR)).sum())
    return v


# ---------------------------------------------------------------------------
# 환율
# ---------------------------------------------------------------------------
def usd_mn_to_krw_100m(x: float, usdkrw: float) -> float:
    """USD mn → KRW 억원: x × 1e6 × 환율 ÷ 1e8 = x × 환율 ÷ 100."""
    return x * usdkrw / 100.0


def apply(fn: Callable[[float], float], xs) -> list[float]:
    return [fn(x) for x in xs]
