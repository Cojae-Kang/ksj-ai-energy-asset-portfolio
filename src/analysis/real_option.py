"""2단계 증설 옵션 (케이스 A): 몬테카를로 + LSM(Longstaff–Schwartz). seed 고정, 순수 함수.

불확실성
  (a) 추가 계통 승인: 결정 시점 T_a에 확률 p로 승인(1회). 미승인이면 2단계 없음 → 옵션 가치 = p × 승인 조건부 가치
  (b) 임대료: 기하 브라운 운동, 기대 증가율 = 임대료 연 인상률, 변동성 σ
      가동률: 수요 시나리오(IEA 하단·기준·상단 성장률)를 경로마다 추첨 — 1단계 가동률로 관측 가능하므로 결정 시 알려진 상태
결정: 승인 후 T_a, T_a+1, …, T_a+W년(1단계 COD 기준)에 '지금 짓기'(무차입 NPV) vs '기다리기'(회귀로 추정한 계속가치)
2단계 사전 임대율 = 결정 연도의 1단계 가동률(같은 시나리오) — 임차 수요 확인 후 착공이라는 설정을 데이터로 연결
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from .pf_model import BASE, PFInputs, occupancy, project_npv


@dataclass(frozen=True)
class OptionInputs:
    phase2: PFInputs                       # 2단계 PF 입력 (용량 = 2단계 MW). rent_per_kw_month = 1단계 COD 시점 임대료
    phase1_prelease: float
    scenarios: Mapping[str, Mapping[str, float]]   # 시나리오 → PFInputs 덮어쓰기 (예: {"ramp_years": 2.2})
    weights: Mapping[str, float]           # 시나리오 → 확률 (합 1)
    approval_prob: float
    decision_year: int                     # T_a (1단계 COD 후 연수)
    window_years: int                      # W: T_a 이후 기다릴 수 있는 연수
    rent_volatility: float
    n_paths: int = 20000
    seed: int = 42
    basis_degree: int = 2


@dataclass
class OptionResult:
    value: float                 # 옵션 가치 (1단계 COD 시점, 금액 단위) = p × 조건부 가치
    value_conditional: float
    stderr_conditional: float
    build_now: float             # 승인 시 T_a에 바로 짓는 전략의 가치 (p 반영)
    flexibility: float           # value − max(build_now, 0)
    critical_rent: dict[str, float | None]   # 시나리오별 T_a 임계 임대료 (이 이상이면 바로 착공)
    breakeven_rent: dict[str, float | None]  # 시나리오별 NPV = 0 임대료 (T_a)
    exercise_share: float        # 승인 조건부 경로 중 착공 비율
    mean_exercise_year: float | None
    by_prob: pd.DataFrame        # approval_prob, value
    convergence: pd.DataFrame    # n_paths, value_conditional, stderr


def npv_at(o: OptionInputs, year: int, rent: float, scen: str) -> float:
    """결정 연도 year에 착공할 때 2단계 무차입 NPV (그 시점 가치). 임대료 = 그 시점 시장 임대료.

    2단계 사전 임대율 = 같은 시나리오의 1단계 가동률(결정 연도). OPEX 기준은 1단계 계획 비용을 OPEX 인상률로 키운 값
    (임대료 경로와 무관한 고정비).
    """
    ov = dict(o.scenarios[scen])
    p1 = replace(o.phase2, prelease=o.phase1_prelease, **ov)
    occ1 = float(occupancy(p1, BASE, year + 1)[-1])
    fixed = p1.opex_per_kw_year
    if p1.opex_ratio is not None:
        fixed += p1.opex_ratio * p1.stabilized_occupancy * p1.rent_per_kw_month * 12
    fixed *= (1 + p1.opex_escalation) ** year
    inp = replace(p1, rent_per_kw_month=rent, prelease=occ1, opex_ratio=None, opex_per_kw_year=fixed)
    return project_npv(inp)


def npv_grid(o: OptionInputs, years: Sequence[int], rents: np.ndarray) -> dict[tuple[str, int], np.ndarray]:
    return {(s, y): np.array([npv_at(o, y, r, s) for r in rents]) for s in o.scenarios for y in years}


def simulate_rents(o: OptionInputs, years: Sequence[int], n: int, rng: np.random.Generator) -> np.ndarray:
    """경로 × 결정 연도 임대료 (GBM, 연 단위). 기대 증가율 = rent_escalation."""
    mu = np.log1p(o.phase2.rent_escalation)
    sig = o.rent_volatility
    last = max(years)
    z = rng.standard_normal((n, last))
    logp = np.cumsum((mu - 0.5 * sig ** 2) + sig * z, axis=1)
    r0 = o.phase2.rent_per_kw_month
    return np.stack([r0 * np.exp(logp[:, y - 1]) if y > 0 else np.full(n, r0) for y in years], axis=1)


def _basis(x: np.ndarray, deg: int) -> np.ndarray:
    xs = x / (np.mean(x) or 1.0)
    return np.vstack([xs ** k for k in range(deg + 1)]).T


def lsm(o: OptionInputs, n: int | None = None, grid_pts: int = 41) -> tuple[float, float, dict]:
    """승인 조건부 옵션 가치 (1단계 COD 시점). 반환: (가치, 표준오차, 상세)."""
    n = n or o.n_paths
    rng = np.random.default_rng(o.seed)
    years = list(range(o.decision_year, o.decision_year + o.window_years + 1))
    rents = simulate_rents(o, years, n, rng)
    names = list(o.scenarios)
    w = np.array([o.weights[s] for s in names], dtype=float)
    scen = rng.choice(len(names), size=n, p=w / w.sum())
    lo, hi = float(rents.min()) * 0.98, float(rents.max()) * 1.02
    grid = np.linspace(lo, hi, grid_pts)
    table = npv_grid(o, years, grid)
    dr = o.phase2.discount_rate
    exer = np.zeros((n, len(years)))
    for k, y in enumerate(years):
        for i, s in enumerate(names):
            m = scen == i
            exer[m, k] = np.interp(rents[m, k], grid, table[(s, y)])
    # 뒤에서부터: 마지막 결정 연도는 max(NPV, 0)
    cash = np.maximum(exer[:, -1], 0.0)
    when = np.where(exer[:, -1] > 0, len(years) - 1, -1)
    boundary: dict[str, list] = {s: [None] * len(years) for s in names}
    for k in range(len(years) - 2, -1, -1):
        disc_next = cash / (1 + dr)          # 다음 결정 시점 가치 → 현재 시점
        cont = np.zeros(n)
        for i, s in enumerate(names):
            m = scen == i
            itm = m & (exer[:, k] > 0)
            if itm.sum() > o.basis_degree + 2:
                X = _basis(rents[itm, k], o.basis_degree)
                beta, *_ = np.linalg.lstsq(X, disc_next[itm], rcond=None)
                cont[itm] = X @ beta
                # 임계 임대료: 격자에서 NPV ≥ 회귀 계속가치가 처음 성립하는 임대료
                xs_mean = np.mean(rents[itm, k])                    # 회귀와 같은 정규화
                Xg = np.vstack([(grid / xs_mean) ** d for d in range(o.basis_degree + 1)]).T
                c_g = Xg @ beta
                ok = (table[(s, years[k])] >= c_g) & (table[(s, years[k])] > 0)
                boundary[s][k] = float(grid[np.argmax(ok)]) if ok.any() else None
        ex_now = (exer[:, k] > 0) & (exer[:, k] >= cont)
        cash = np.where(ex_now, exer[:, k], disc_next)
        when = np.where(ex_now, k, when)
    v0 = cash / (1 + dr) ** o.decision_year
    detail = {"years": years, "grid": grid, "table": table, "when": when, "scen": scen, "names": names,
              "boundary": boundary, "rents": rents, "exer": exer}
    return float(v0.mean()), float(v0.std(ddof=1) / np.sqrt(n)), detail


def value(o: OptionInputs, probs: Sequence[float], conv_ns: Sequence[int]) -> OptionResult:
    vc, se, d = lsm(o)
    dr = o.phase2.discount_rate
    years, names, grid, table = d["years"], d["names"], d["grid"], d["table"]
    now = d["exer"][:, 0] / (1 + dr) ** o.decision_year
    build_now = o.approval_prob * float(now.mean())
    val = o.approval_prob * vc
    crit = {s: d["boundary"][s][0] for s in names}
    be = {}
    for s in names:
        t = table[(s, years[0])]
        idx = np.where(np.diff(np.sign(t)) != 0)[0]
        be[s] = float(np.interp(0.0, t[idx[0]:idx[0] + 2], grid[idx[0]:idx[0] + 2])) if len(idx) else None
    ex = d["when"] >= 0
    mean_year = float(np.mean(np.array(years)[d["when"][ex]])) if ex.any() else None
    by_prob = pd.DataFrame({"approval_prob": list(probs), "value": [p * vc for p in probs]})
    conv = []
    for n in conv_ns:
        v, s_, _ = lsm(o, n)
        conv.append({"n_paths": n, "value_conditional": v, "stderr": s_})
    return OptionResult(val, vc, se, build_now, val - max(build_now, 0.0), crit, be, float(ex.mean()), mean_year,
                        by_prob, pd.DataFrame(conv))
