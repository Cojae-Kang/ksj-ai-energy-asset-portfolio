"""Vol.5 결론값 로드 (순수 함수). 새 데이터 수집 없음 — Vol.1~4의 load_facts·Story·build_summary.md에서 불러온다.

각 결론값(Ref)은 원래 편·쪽·신뢰 등급을 함께 든다.
  - 값: 각 편 data.load_facts 결과에서 계산 (숫자 하드코딩 금지)
  - 쪽: 원 편 국문 Story 페이지 문구에 그 값이 실제로 있는지 대조(page_ok)
  - 요약 대조: 원 편 build_summary.md에 같은 값이 있는지 대조(summary_ok)
  - 등급: 결론을 만든 주요 입력 중 가장 약한 등급(A 공식 원문 > D 공식 자료 계산 > B 보도·외부 보고서 > C 민간 2차 > J 저자 판단).
          계산값은 입력이 모두 A여도 최소 D. 입력 자체를 그대로 옮긴 값(예: 공개 사례 40원)은 그 입력의 등급.
판정(넣는다/기다린다/피한다)과 트리거는 저자 판단(J) — 아래 verdicts()의 규칙도 저자 판단이다.
"""
from __future__ import annotations

import csv
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from research.vol04.data import TIER_EN, TIER_KR
from src.data_fetch.base import resolve_path

logger = logging.getLogger("research.vol05.data")

VOLS = (1, 2, 3, 4)
NO_VALUE = "—"                                   # 미입력(값 없음) — 등급 집계에서 따로 센다
# J 세분 (집계 전용): J-설계 = 가상 자산·기업·거래의 정의값(출처가 존재할 수 없음) · J-가정 = 시장·재무 가정에 대한 저자 판단
J_DESIGN, J_ASSUME = "J-설계", "J-가정"
TIER_KR = {**TIER_KR, NO_VALUE: "미입력", J_DESIGN: "가상 자산 정의값", J_ASSUME: "시장·재무 가정 판단"}
TIER_EN = {**TIER_EN, NO_VALUE: "Not set", J_DESIGN: "Hypothetical-asset definition", J_ASSUME: "Market/financial assumption"}
CODE_EN = {J_DESIGN: "J-design", J_ASSUME: "J-assumption"}
CASE_KR, CASE_EN = {"A": "한국", "B": "미국"}, {"A": "Korea", "B": "U.S."}     # Vol.2 케이스 A = 한국 40MW, B = 미국 100MW
VERDICT_KR = {"invest": "넣는다", "wait": "기다린다", "avoid": "피한다"}
VERDICT_EN = {"invest": "Invest", "wait": "Wait", "avoid": "Avoid"}


# ---------------------------------------------------------------------------
# 표기
# ---------------------------------------------------------------------------
def pct(v: float, d: int = 1) -> str:
    return f"{round(v * 100, d) + 0.0:.{d}f}%"


def xx(v: float, kr: bool = True, d: int = 2) -> str:
    return f"{v:.{d}f}배" if kr else f"{v:.{d}f}x"


def num(v: float, d: int = 1) -> str:
    return f"{v:,.{d}f}"


def eok(v: float, kr: bool = True) -> str:
    """억원 → 국문 '1,885억원' · 영문 'KRW 188.5bn'."""
    return f"{v:,.0f}억원" if kr else f"KRW {v / 10:,.1f}bn"


def won(v: float, kr: bool = True, d: int = 1) -> str:
    return f"{v:,.{d}f}원" if kr else f"KRW {v:,.{d}f}"


def rng(a: float, b: float, d: int = 1, unit_kr: str = "원", unit_en: str = "", kr: bool = True) -> str:
    return f"{a:,.{d}f}~{b:,.{d}f}{unit_kr}" if kr else f"{a:,.{d}f}–{b:,.{d}f}{unit_en}"


# ---------------------------------------------------------------------------
# 자료 구조
# ---------------------------------------------------------------------------
@dataclass
class Grade:
    """원 편 입력 하나의 신뢰 등급 (집계용)."""
    vol: int
    key: str
    label_kr: str
    label_en: str
    grade: str          # A D B C J 또는 '—'(미입력)
    basis: str          # 등급 근거 (원 편 tier · 상태 · URL 판정)
    j_kind: str = ""    # J일 때 'design'(가상 자산 정의값) | 'assumption'(시장·재무 가정 판단)

    @property
    def bucket(self) -> str:
        """집계 칸: J는 J-설계 / J-가정으로 나눈다."""
        if self.grade != "J":
            return self.grade
        return J_DESIGN if self.j_kind == "design" else J_ASSUME


@dataclass
class Ref:
    """결론값 하나: 값 · 원 편·쪽 · 신뢰 등급 · 대조 결과."""
    key: str
    vol: int
    page: str
    value: Any
    kr: str
    en: str
    label_kr: str
    label_en: str
    tier: str = ""
    weakest_kr: str = ""
    weakest_en: str = ""
    needles: list[str] = field(default_factory=list)    # 원 편 국문 해당 쪽에 있어야 하는 문구
    summary: list[str] = field(default_factory=list)    # 원 편 build_summary.md에 있어야 하는 문구
    page_ok: bool | None = None
    summary_ok: bool | None = None

    def where(self, kr: bool = True) -> str:
        return f"Vol.{self.vol} p{self.page}" if kr else f"Vol.{self.vol} p.{self.page}"


@dataclass
class Asset:
    """투자 지도의 자산 한 줄."""
    key: str
    vol: int                    # 주 근거 편
    verdict: str                # invest | wait | avoid (저자 판단 J)
    base: list[str]             # 기준 수익률·핵심 숫자 Ref 키
    flip: list[str]             # 결론을 뒤집는 가정과 그 폭 Ref 키
    rule_kr: str = ""           # 판정 규칙 (저자 판단)
    rule_en: str = ""

    @property
    def refs(self) -> list[str]:
        return self.base + self.flip


@dataclass
class Facts:
    as_of: str
    vols: dict[int, Any]
    refs: dict[str, Ref]
    assets: list[Asset]
    headlines: dict[int, dict[str, str]]            # 편 → {kr, en, summary_kr, match}
    grades: list[Grade]
    dist: dict[int, dict[str, int]]                 # 편 → 등급 → 개수
    corrections: list[dict]
    pages: dict[tuple[int, str], dict[str, str]]    # (편, 언어) → 쪽 → 문구
    extra: dict = field(default_factory=dict)

    def R(self, k: str) -> Ref:
        return self.refs[k]

    def V(self, k: str) -> Any:
        return self.refs[k].value

    @property
    def total(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for d in self.dist.values():
            for g, n in d.items():
                out[g] = out.get(g, 0) + n
        return out

    def count(self, verdict: str) -> int:
        return sum(a.verdict == verdict for a in self.assets)


# ---------------------------------------------------------------------------
# Vol.1~4 불러오기
# ---------------------------------------------------------------------------
def load_vols(cfg: Mapping) -> dict[int, Any]:
    """각 편 data.load_facts (각 편 기준일). Vol.4 몬테카를로는 config vol05.vol04_mc_n(기본 0, 결정론 결과만)."""
    from research.vol01 import data as d1
    from research.vol02 import data as d2
    from research.vol03 import data as d3
    from research.vol04 import data as d4
    r = cfg["research"]
    f1 = d1.load_facts(cfg, r["vol01"].get("as_of") or r["vol02"]["as_of"])
    f2 = d2.load_facts(cfg)
    f3 = d3.load_facts(cfg)
    f4 = d4.load_facts(cfg, mc_n=int(r["vol05"].get("vol04_mc_n", 0)))
    return {1: f1, 2: f2, 3: f3, 4: f4}


def vol2_link(f2) -> dict:
    """Vol.4 Story가 쓰는 Vol.2 연결값 (research.vol04.build.vol2_link와 같은 값, Vol.2를 다시 계산하지 않음)."""
    s = f2.cases["A"].base.summary()
    return {"min_dscr": float(s["min_dscr"]), "equity_irr": float(s["equity_irr"])}


def page_text(pg) -> str:
    """Page 사양 → 문구 (제목·부제·셀 제목·주·표·글머리표·박스·목차)."""
    out = [pg.title, pg.subtitle]
    for c in pg.cells:
        out += [c.title, c.note, c.panel_lead, c.strip, c.unit]
        if c.table is not None:
            out += list(c.table.header) + [str(v) for row in c.table.rows for v in row]
        if c.bullets:
            out += list(c.bullets)
    for b in pg.boxes:
        out += [b.number, b.caption, b.title] + list(b.bullets)
    for t in pg.toc:
        out += list(t)
    return "\n".join(x for x in out if x)


def stories(cfg: Mapping, vols: Mapping[int, Any]) -> dict[tuple[int, str], dict[str, str]]:
    """각 편 Story(국문·영문) → 쪽 번호별 문구. 헤드라인은 쪽 'i'의 제목."""
    from research.vol01 import story as s1
    from research.vol02 import story as s2
    from research.vol03 import story as s3
    from research.vol04 import story as s4
    out = {}
    for lang in ("kr", "en"):
        sts = {1: s1.Story(cfg, vols[1], lang), 2: s2.Story(cfg, vols[2], lang), 3: s3.Story(cfg, vols[3], lang),
               4: s4.Story(cfg, vols[4], lang, vol2_link(vols[2]))}
        for v, st in sts.items():
            pg = {}
            for p in st.pages():
                if p.label:
                    pg[p.label] = (p.title + "\n" + page_text(p)) if p.kind == "exec" else page_text(p)
                    if p.kind == "exec":
                        pg["_headline"] = p.title
            out[(v, lang)] = pg
    return out


def summary_path(cfg: Mapping, vol: int) -> Path:
    return resolve_path(cfg["research"][f"vol0{vol}"]["output_dir"]) / "build_summary.md"


def summary_texts(cfg: Mapping) -> dict[int, str]:
    out = {}
    for v in VOLS:
        p = summary_path(cfg, v)
        out[v] = p.read_text(encoding="utf-8") if p.exists() else ""
    return out


def summary_headline(text: str) -> str:
    """build_summary.md의 헤드라인: '- 헤드라인: …' (Vol.2~4) 또는 Executive Summary 쪽 제목 '- **i** …' (Vol.1)."""
    for pat in (r"^- 헤드라인: (.+)$", r"^- \*\*i\*\* (.+)$"):
        m = re.search(pat, text, flags=re.M)
        if m:
            return m.group(1).strip()
    return ""


# ---------------------------------------------------------------------------
# 신뢰 등급
# ---------------------------------------------------------------------------
def _official(url: str | None, domains: list[str]) -> bool:
    for u in re.split(r"\s*;\s*", url or ""):
        host = urlparse(u.strip()).netloc.lower()
        if host and any(host == d or host.endswith("." + d) or host.endswith(d) for d in domains):
            return True
    return False


def grade_assumption(a, g: Mapping) -> tuple[str, str]:
    """Vol.2·3 Assumption → (등급, 근거). 규칙은 config vol05.grading (저자 판단)."""
    sm = g["status_map"]
    if a.value is None:
        return NO_VALUE, "미입력"
    if getattr(a, "origin", "") == "evidence":                 # Vol.3 IPO 할인율: DART 증권신고서로 저자 계산
        return sm["evidence"], "origin=evidence"
    st = a.status
    if st == "sourced":
        return ("A", "sourced·공식 도메인") if _official(a.url, g["official_domains"]) else ("B", "sourced·보도/외부 보고서")
    return sm[st], f"status={st}"


def j_kind_status(a) -> str:
    """Vol.2·3 J 세분: 원 편 상태 design(가상 케이스·기업·거래 설정) → design, judgment·neutral → assumption."""
    return "design" if a.status == "design" else "assumption"


def j_kind_text(source: str, pattern: str) -> str:
    """Vol.4 J 세분: 입력 출처 문구가 '저자 설계(값)' 표기면 design, 아니면 assumption (패턴은 config vol05.grading.j_design_pattern)."""
    return "design" if re.search(pattern, source or "") else "assumption"


def grade_inputs(cfg: Mapping, vols: Mapping[int, Any]) -> list[Grade]:
    """Vol.1~4 입력 전체의 등급. Vol.1 = 공식 원자료 소스, Vol.2 = 케이스 A·B 가정표, Vol.3 = 가정표, Vol.4 = 입력 CSV."""
    from research.vol02 import data as d2
    from research.vol03 import data as d3
    from research.vol04 import data as d4
    g = cfg["research"]["vol05"]["grading"]
    out: list[Grade] = []
    src = {s["id"]: s for s in vols[1].sources}
    for sid in g["vol01_sources"]:
        s = src[sid]
        out.append(Grade(1, sid, s["org_kr"], s["org_en"], "A", "공식 원자료(config vol05.grading.vol01_sources)"))
    for case, d in vols[2].assumptions.items():
        for k in d2.table_keys(case, d):
            gr, basis = grade_assumption(d[k], g)
            kr, en = d2.LABELS.get(k, (k, k))
            out.append(Grade(2, f"{case}.{k}", f"{kr}({CASE_KR.get(case, case)})", f"{en} ({CASE_EN.get(case, case)})", gr, basis,
                             j_kind_status(d[k]) if gr == "J" else ""))
    a3 = vols[3].assumptions
    for k in d3.table_keys(a3):
        gr, basis = grade_assumption(a3[k], g)
        kr, en = d3.LABELS.get(k, (k, k))
        out.append(Grade(3, k, kr, en, gr, basis, j_kind_status(a3[k]) if gr == "J" else ""))
    for k, x in vols[4].inputs.items():
        kr, en = d4.LABELS.get(k, (k, k))
        out.append(Grade(4, k, kr, en, x.tier, "vol04_inputs.csv tier", j_kind_text(x.source, g["j_design_pattern"]) if x.tier == "J" else ""))
    return out


def bucket_keys(order: list[str]) -> list[str]:
    """집계 칸 순서: A D B C J-설계 J-가정 — (J를 두 칸으로)."""
    out = []
    for k in order:
        out += [J_DESIGN, J_ASSUME] if k == "J" else [k]
    return out + [NO_VALUE]


def distribution(grades: list[Grade], order: list[str]) -> dict[int, dict[str, int]]:
    keys = bucket_keys(order)
    return {v: {k: sum(1 for x in grades if x.vol == v and x.bucket == k) for k in keys} for v in VOLS}


def sourceable(dist_row: Mapping[str, int]) -> tuple[int, int]:
    """(출처가 있을 수 있는 입력 수, 그중 A·D 수). 분모 = 값이 있는 입력 − J-설계 (가상 자산 정의값은 출처가 존재할 수 없음)."""
    n = sum(v for k, v in dist_row.items() if k not in (J_DESIGN, NO_VALUE))
    return n, dist_row.get("A", 0) + dist_row.get("D", 0)


def weakest(drivers: list[tuple[int, str]], gmap: Mapping[tuple[int, str], Grade], order: list[str],
            floor: str | None = "D") -> tuple[str, str, str]:
    """(등급, 가장 약한 입력 국문, 영문). floor = 계산값의 최소 등급(D). 입력이 없으면 floor."""
    rank = {k: i for i, k in enumerate(order)}
    best: Grade | None = None
    for d in drivers:
        x = gmap[d]
        if best is None or rank.get(x.grade, -1) > rank.get(best.grade, -1):
            best = x
    if best is None:
        return floor or "D", "", ""
    t = best.grade
    if floor and rank[t] < rank[floor]:
        return floor, "", ""                       # 입력이 모두 floor보다 강함 → 공식 자료로 저자가 계산한 값
    return t, best.label_kr, best.label_en


# ---------------------------------------------------------------------------
# 결론값
# ---------------------------------------------------------------------------
def premium_range(cfg: Mapping, f4) -> tuple[dict, dict]:
    """Vol.4 Story.prem_rng와 같은 값: (스프레드 최소, 최대) @ 몬테카를로 해지 확률."""
    v = cfg["research"]["vol04"]
    hz, sp = float(v["monte_carlo"]["hazard"]), v["risk_spreads"]
    pick = lambda s: next(p for p in f4.extra["premium_grid"] if abs(p["hazard"] - hz) < 1e-12 and abs(p["spread"] - float(s)) < 1e-12)  # noqa: E731
    return pick(min(sp)), pick(max(sp))


def rec_end_year(f4) -> int | None:
    """REC 현물시장 종료 연도 — Vol.4 입력 rec_eligible 출처 문구('REC 현물시장은 YYYY년 말까지')에서 읽는다(B)."""
    m = re.search(r"REC 현물시장은\s*(\d{4})년", f4.inputs["rec_eligible"].source)
    return int(m.group(1)) if m else None


def build_refs(cfg: Mapping, vols: Mapping[int, Any]) -> dict[str, Ref]:
    f1, f2, f3, f4 = (vols[v] for v in VOLS)
    R: dict[str, Ref] = {}

    def add(key, vol, page, value, kr, en, lkr, len_, needles=(), summary=()):
        R[key] = Ref(key, vol, page, value, kr, en, lkr, len_, needles=list(needles), summary=list(summary))

    # ---- Vol.1: 시총 분해 (DART·KRX → 저자 계산 D)
    dc = f1.decomp
    ag, op = dc.agg, dc.op_all
    add("v1_mult_ni", 1, "4", ag["mult_share"], pct(ag["mult_share"], 0), pct(ag["mult_share"], 0),
        "멀티플 기여 · 3사 순이익 기준", "Multiple contribution · 3-name net income", [pct(ag["mult_share"], 0)], [f"멀티플 기여 {pct(ag['mult_share'])}"])
    add("v1_earn_ni", 1, "4", ag["earn_share"], pct(ag["earn_share"], 0), pct(ag["earn_share"], 0),
        "이익 기여 · 3사 순이익 기준", "Earnings contribution · 3-name net income", [pct(ag["earn_share"], 0)], [f"이익 기여 {pct(ag['earn_share'])}"])
    add("v1_cover", 1, "4", ag["coverage_t0"], pct(ag["coverage_t0"], 0), pct(ag["coverage_t0"], 0),
        "3사 분해 대상의 시작 시총 비중", "3-name split's share of starting cap", [f"시작 시총의 {pct(ag['coverage_t0'], 0)}"], [f"시작 시총의 {pct(ag['coverage_t0'], 0)}"])
    add("v1_mult_op", 1, "4", op["mult_share"], pct(op["mult_share"], 0), pct(op["mult_share"], 0),
        "멀티플 기여 · 4사 영업이익 기준", "Multiple contribution · 4-name operating income", [f"멀티플 {pct(op['mult_share'], 0)}"], [f"멀티플 {pct(op['mult_share'], 0)}"])
    add("v1_per", 1, "4", (ag["per0"], ag["per1"]), f"{ag['per0']:.1f}배 → {ag['per1']:.1f}배", f"{ag['per0']:.1f}x → {ag['per1']:.1f}x",
        "3사 합산 PER (2023년 초 → 현재)", "3-name P/E (start-2023 → now)", [f"{ag['per0']:.1f}배", f"{ag['per1']:.1f}배"], [f"PER {ag['per0']:.1f} → {ag['per1']:.1f}배"])

    # ---- Vol.2: 한국 40MW 데이터센터 PF (케이스 A)
    a = f2.cases["A"]
    s = a.base.summary()
    pt_r, gr_r = a.power_pair()
    gross = a.alts["gross"]
    tgt = float(f2.assumptions["A"]["target_dscr"].value)
    add("v2_min_dscr", 2, "3", s["min_dscr"], xx(s["min_dscr"]), xx(s["min_dscr"], False), "최소 DSCR (전력비 별도 청구)", "Min DSCR (power billed separately)",
        [xx(s["min_dscr"])], [f"최소 DSCR {xx(s['min_dscr'])}"])
    add("v2_target_dscr", 2, "3", tgt, xx(tgt), xx(tgt, False), "목표 DSCR (sizing 기준)", "Target DSCR (sizing)", [xx(tgt)])
    add("v2_debt", 2, "3", a.base.debt, eok(a.base.debt), eok(a.base.debt, False), "대출 한도", "Debt capacity", [eok(a.base.debt)], [eok(a.base.debt)])
    add("v2_gearing", 2, "3", s["gearing"], pct(s["gearing"], 0), pct(s["gearing"], 0), "대출 비율 (총사업비 대비)", "Gearing (of total cost)",
        [f"총사업비의 {pct(s['gearing'], 0)}"], [f"총사업비의 {pct(s['gearing'], 0)}"])
    add("v2_irr_pt", 2, "7", pt_r.summary()["equity_irr"], pct(pt_r.summary()["equity_irr"]), pct(pt_r.summary()["equity_irr"]),
        "Equity IRR · 전력비 별도 청구", "Equity IRR · power billed separately", [pct(pt_r.summary()["equity_irr"])], [f"Equity IRR {pct(pt_r.summary()['equity_irr'])}"])
    add("v2_irr_gross", 2, "7", gr_r.summary()["equity_irr"], pct(gr_r.summary()["equity_irr"]), pct(gr_r.summary()["equity_irr"]),
        "Equity IRR · 전력비 포함 임대", "Equity IRR · power included in rent", [pct(gr_r.summary()["equity_irr"])], [f"{pct(gr_r.summary()['equity_irr'])}(전력 포함)"])
    add("v2_debt_gross", 2, "7", gross.debt, eok(gross.debt), eok(gross.debt, False), "대출 한도 · 전력 포함 임대로 다시 sizing", "Debt capacity · re-sized with power in rent",
        [eok(gross.debt)], [eok(gross.debt)])
    sg = a.stresses["power_gross"].summary()["min_dscr"]
    add("v2_dscr_gross", 2, "4", sg, xx(sg), xx(sg, False), "최소 DSCR · 같은 대출에 전력 포함 임대", "Min DSCR · same debt, power in rent", [xx(sg)])

    # ---- Vol.3: Target Co. IPO
    b, val = f3.band, f3.val
    req_dp, alt = f3.mc_dp.required[0.5], f3.dp_floor_alt
    req_alt = alt["mc"].required[0.5]
    npm0 = float(f3.assumptions["npm_low"].value)
    fy0 = min(f3.der.hist)
    add("v3_band", 3, "6", (b.low, b.high), f"{b.low:,.0f}~{b.high:,.0f}원", f"KRW {b.low:,.0f}–{b.high:,.0f}", "희망공모가 밴드 (현재 기준)", "Indicative range (current basis)",
        [f"{b.low:,.0f}~{b.high:,.0f}"], [f"{b.low:,.0f}~{b.high:,.0f}원"])
    add("v3_band_disc", 3, "A2", (b.d_low, b.d_high), f"{pct(b.d_low)}~{pct(b.d_high)}", f"{pct(b.d_low)}–{pct(b.d_high)}", "밴드 할인율 (평가가액 대비)", "Range discount (to value)",
        [pct(b.d_low), pct(b.d_high)], [f"할인율 {b.d_low * 100:.1f}~{pct(b.d_high)}"])
    add("v3_value", 3, "6", val.per_share["current"], f"{val.per_share['current']:,.0f}원", f"KRW {val.per_share['current']:,.0f}", "주당 평가가액", "Value per share",
        [f"{val.per_share['current']:,.0f}"], [f"{val.per_share['current']:,.0f}원"])
    add("v3_req_dp", 3, "7", req_dp, pct(req_dp), pct(req_dp), f"필요 할인율 P50 · 순이익률 하한 FY{fy0}A({pct(npm0)})", f"Required discount P50 · margin floor FY{fy0}A ({pct(npm0)})",
        [pct(req_dp), f"FY{fy0}A"], [pct(req_dp)])
    add("v3_req_alt", 3, "7", req_alt, pct(req_alt), pct(req_alt), f"필요 할인율 P50 · 순이익률 하한 FY{alt['fy']}A({pct(alt['npm_low'])})",
        f"Required discount P50 · margin floor FY{alt['fy']}A ({pct(alt['npm_low'])})", [pct(req_alt), f"FY{alt['fy']}A"], [pct(req_alt)])
    add("v3_npm_floor", 3, "7", (npm0, alt["npm_low"]), f"{pct(npm0)} / {pct(alt['npm_low'])}", f"{pct(npm0)} / {pct(alt['npm_low'])}",
        f"순이익률 하한 FY{fy0}A / FY{alt['fy']}A", f"Net-margin floor FY{fy0}A / FY{alt['fy']}A", [pct(npm0), pct(alt["npm_low"])])
    npm_now = float(f3.assumptions["npm"].value)
    add("v3_npm_now", 3, "2", npm_now, pct(npm_now), pct(npm_now), f"3사 합산 지배순이익률 FY{max(f3.der.hist)}A", f"3-name net margin FY{max(f3.der.hist)}A",
        [pct(npm_now)])
    pc, pn = f3.mult.applied("current"), f3.mult.applied("normalized")
    add("v3_per", 3, "5", (pc, pn), f"{pc:.1f}배 → {pn:.1f}배", f"{pc:.1f}x → {pn:.1f}x", "적용 PER → 정상화 PER", "Applied P/E → normalised P/E",
        [f"{pc:.1f}배", f"{pn:.1f}배"], [f"적용 PER {pc:.1f}배", f"정상화 {pn:.1f}배"])

    # ---- Vol.4: 가상 태양광 35MW 지분
    irr = {k: r.irr for k, r in f4.base.items()}
    hurdle = f4.V("equity_hurdle")
    add("v4_hurdle", 4, "4", hurdle, pct(hurdle, 0), pct(hurdle, 0), "지분 요구수익률", "Equity hurdle", [f"요구수익률 {pct(hurdle, 0)}"])
    for k, lk, le in (("cfd", "한전 CfD", "KEPCO CfD"), ("ppa", "직접 PPA", "direct PPA"), ("merchant", "시장 판매", "merchant")):
        add(f"v4_irr_{k}", 4, "4", irr[k], pct(irr[k], 2), pct(irr[k], 2), f"지분 IRR · {lk}", f"Equity IRR · {le}", [pct(irr[k])], [pct(irr[k], 2)])
    c = f4.base["cfd"]
    add("v4_cfd_gearing", 4, "4", c.gearing, pct(c.gearing, 0), pct(c.gearing, 0), "대출 비율 · 한전 CfD", "Gearing · KEPCO CfD", [pct(c.gearing, 0)], [pct(c.gearing)])
    add("v4_cfd_dscr", 4, "4", c.min_dscr, xx(c.min_dscr), xx(c.min_dscr, False), "최소 DSCR · 한전 CfD", "Min DSCR · KEPCO CfD", [xx(c.min_dscr)], [f"{c.min_dscr:.3f}"])
    add("v4_cfd_dscr_target", 4, "2", f4.V("dscr_cfd"), xx(f4.V("dscr_cfd")), xx(f4.V("dscr_cfd"), False), "목표 DSCR · 한전 CfD", "Target DSCR · KEPCO CfD",
        [f"{f4.V('dscr_cfd'):.2f} · {pct(f4.V('gearing_cfd'), 0)}"])
    sens = {r["key"]: r for r in f4.sens}
    cf, cx, smp = sens["capacity_factor"], sens["capex"], sens["smp_base"]
    add("v4_cfd_cf_low", 4, "4", (cf["lo_v"], cf["low"]["cfd"]), f"이용률 {pct(cf['lo_v'], 0)} → {pct(cf['low']['cfd'])}",
        f"CF {pct(cf['lo_v'], 0)} → {pct(cf['low']['cfd'])}", "한전 CfD 지분 IRR · 이용률 범위 하단", "KEPCO CfD equity IRR · CF at range low",
        [pct(cf["low"]["cfd"]), pct(cf["lo_v"], 0)])
    add("v4_cf_base", 4, "1", f4.asset.capacity_factor, pct(f4.asset.capacity_factor, 0), pct(f4.asset.capacity_factor, 0), "이용률 (기준)", "Capacity factor (base)",
        [pct(f4.asset.capacity_factor, 0)], [f"이용률 {pct(f4.asset.capacity_factor, 0)}"])
    add("v4_cfd_capex_hi", 4, "4", cx["high"]["cfd"], pct(cx["high"]["cfd"]), pct(cx["high"]["cfd"]), "한전 CfD 지분 IRR · 사업비 KEEI 상단", "KEPCO CfD equity IRR · CAPEX at KEEI top",
        [pct(cx["high"]["cfd"])])
    add("v4_merchant_smp_hi", 4, "4", (smp["hi_v"], smp["high"]["merchant"]), f"SMP {smp['hi_v']:,.1f}원 → {pct(smp['high']['merchant'])}",
        f"SMP {smp['hi_v']:,.1f} → {pct(smp['high']['merchant'])}", "시장 판매 지분 IRR · SMP 범위 상단", "Merchant equity IRR · SMP at range top",
        [pct(smp["high"]["merchant"])])
    add("v4_merchant_smp_lo", 4, "4", (smp["lo_v"], smp["low"]["merchant"]), f"SMP {smp['lo_v']:,.1f}원 → {pct(smp['low']['merchant'])}",
        f"SMP {smp['lo_v']:,.1f} → {pct(smp['low']['merchant'])}", "시장 판매 지분 IRR · SMP 범위 하단", "Merchant equity IRR · SMP at range low",
        [pct(smp["low"]["merchant"])])
    add("v4_smp_base", 4, "3", f4.V("smp_base"), won(f4.V("smp_base")), won(f4.V("smp_base"), False), "SMP 기준값 (최근 12개월 육지 평균)", "SMP base (12-month mainland average)",
        [f"{f4.V('smp_base'):,.1f}"])
    add("v4_ktb", 4, "A4", (f4.ktb, f4.ktb_date), f"{pct(f4.ktb, 2)} ({f4.ktb_date})", f"{pct(f4.ktb, 2)} ({f4.ktb_date})", "국고채 3년", "KTB 3-yr",
        [f"{pct(f4.ktb, 2)}({f4.ktb_date})"])
    am = f4.lcoe_check["actual_irr"]["merchant"]
    add("v4_merchant_actual", 4, "4", am, pct(am), pct(am), "시장 판매 지분 IRR · 2022년 실제 설치비", "Merchant equity IRR · 2022 actual unit cost", [pct(am)], [f"시장 {pct(am)}"])
    add("v4_cfd_price", 4, "3", f4.corridor[0], won(f4.corridor[0]), won(f4.corridor[0], False), "한전 계약가 (2026년 1차 입찰 상한)", "KEPCO contract price (2026 round-1 cap)",
        [f"{f4.corridor[0]:,.1f}원"])
    add("v4_ppa_mid", 4, "4", f4.ppa_mid, won(f4.ppa_mid), won(f4.ppa_mid, False), "직접 PPA 가격 (회랑 중간)", "Direct PPA price (corridor mid)", [], [f"회랑 중간 {f4.ppa_mid:,.1f}원"])
    lo, hi = premium_range(cfg, f4)
    add("v4_room", 4, "5", (hi["max_fee"], lo["max_fee"]), f"{hi['max_fee']:.1f}~{lo['max_fee']:.1f}원", f"KRW {hi['max_fee']:.1f}–{lo['max_fee']:.1f}",
        "데이터센터 망이용료 여유 (kWh당)", "Buyer's room for network charges (per kWh)", [f"{hi['max_fee']:.0f}~{lo['max_fee']:.0f}원"], [f"여유 {hi['max_fee']:.1f}~{lo['max_fee']:.1f}원"])
    add("v4_ppa_need", 4, "i", (lo["price"], hi["price"]), f"{lo['price']:.1f}~{hi['price']:.1f}원", f"KRW {lo['price']:.1f}–{hi['price']:.1f}",
        "발전사 필요 PPA 가격 (kWh당)", "Seller's required PPA price (per kWh)", [f"{lo['price']:.1f}~{hi['price']:.1f}원"], [f"필요 PPA {lo['price']:.1f}~{hi['price']:.1f}원"])
    net = f4.V("net_charge_example")
    add("v4_net_charge", 4, "5", net, f"약 {net:.0f}원", f"~KRW {net:.0f}", "공개 사례 부대비용 (한전 중개 제3자 PPA, 태양광 Case 1)", "Public example of charges (KEPCO-brokered 3rd-party PPA)",
        [f"{net:.0f}원(B)"], [f"망이용료 {net:.0f}원(B)"])
    room_cap = float(f4.extra["tou"]["room_cap"])
    gap = max(0.0, lo["price"] + net - room_cap)
    add("v4_gap", 4, "A1", gap, f"{gap:,.0f}원", f"KRW {gap:,.0f}", "성립에 필요한 부대비용 감소분(또는 구매자 추가 지불)", "Charge cut (or buyer premium) needed to close",
        [f"{gap:,.0f}원 이상"])
    nb = cfg["research"]["vol04"]["net_charge_basis"]
    add("v4_proviso", 4, "A4", nb["proviso_kr"], nb["proviso_kr"].replace("단서: ", "").split(" · ")[0], nb["proviso_en"].replace("Proviso: ", "").split(" · ")[0],
        "직접 PPA 고시 단서 (망 미이용)", "Direct-PPA notice proviso (no grid use)", ["송·배전망을 이용하지 않으면"])
    yr = rec_end_year(f4)
    add("v4_rec_end", 4, "2", yr, f"{yr}년 말" if yr else "TODO(data)", f"end-{yr}" if yr else "TODO(data)", "REC 현물시장 존속 시한", "REC spot market ends",
        [f"REC 현물시장은 {yr}년 말까지"] if yr else [])
    add("v4_rec_none", 4, "2", f4.V("rec_eligible"), "REC 없음" if f4.V("rec_eligible") == 0 else "REC 있음", "no RECs" if f4.V("rec_eligible") == 0 else "RECs",
        "2027년 이후 신규 사업자 REC 수익", "REC revenue for post-2027 entrants", ["REC가 없다"])
    return R


# 결론값 → 등급을 정하는 주요 입력 (편, 키). 비어 있으면 원 편 공식 자료로 저자가 계산한 값(D)
DRIVERS: dict[str, list[tuple[int, str]]] = {
    **{k: [(1, "dart"), (1, "krx")] for k in ("v1_mult_ni", "v1_earn_ni", "v1_cover", "v1_mult_op", "v1_per")},
    **{k: [(2, "A.capex_per_mw"), (2, "A.rent_per_kw_month"), (2, "A.power_passthrough"), (2, "A.target_dscr"), (2, "A.max_gearing")]
       for k in ("v2_min_dscr", "v2_debt", "v2_gearing", "v2_irr_pt", "v2_irr_gross", "v2_debt_gross", "v2_dscr_gross")},
    "v2_target_dscr": [(2, "A.target_dscr")],
    "v3_band": [(3, "band_discount_low"), (3, "band_discount_high"), (3, "revenue"), (3, "npm"), (3, "shares_pre")],
    "v3_band_disc": [(3, "band_discount_low"), (3, "band_discount_high")],
    "v3_value": [(3, "revenue"), (3, "npm"), (3, "shares_pre")],
    "v3_req_dp": [(3, "npm_low"), (3, "npm_mode"), (3, "npm_high"), (3, "npm_shape"), (3, "per_shape"), (3, "growth_mean")],
    "v3_req_alt": [(3, "npm_mode"), (3, "npm_high"), (3, "npm_shape"), (3, "per_shape"), (3, "growth_mean")],
    "v3_npm_floor": [(3, "npm_low")],
    "v3_per": [],
    "v4_hurdle": [(4, "equity_hurdle")],
    **{k: [(4, "cfd_price"), (4, "lcoe_target"), (4, "capacity_factor"), (4, "gearing_cfd"), (4, "dscr_cfd")]
       for k in ("v4_irr_cfd", "v4_cfd_gearing", "v4_cfd_dscr", "v4_cfd_cf_low", "v4_cfd_capex_hi")},
    "v4_cfd_dscr_target": [(4, "dscr_cfd")],
    "v4_cf_base": [(4, "capacity_factor")],
    "v4_irr_ppa": [(4, "cfd_price"), (4, "tou_tariff"), (4, "lcoe_target"), (4, "capacity_factor"), (4, "gearing_ppa"), (4, "dscr_ppa")],
    "v4_ppa_mid": [(4, "cfd_price"), (4, "tou_tariff"), (4, "fuel_adj"), (4, "climate_env"), (4, "solar_shape_p")],
    **{k: [(4, "smp_base"), (4, "rec_eligible"), (4, "lcoe_target"), (4, "gearing_merchant"), (4, "dscr_merchant")]
       for k in ("v4_irr_merchant", "v4_merchant_smp_hi", "v4_merchant_smp_lo", "v4_merchant_actual")},
    "v4_smp_base": [(4, "smp_base")],
    "v4_ktb": [(4, "ktb_3y")],
    "v3_npm_now": [(3, "npm")],
    "v4_cfd_price": [(4, "cfd_price")],
    **{k: [(4, "tou_tariff"), (4, "fuel_adj"), (4, "climate_env"), (4, "power_fund_rate"), (4, "solar_shape_p"), (4, "cfd_price"), (4, "gearing_ppa")]
       for k in ("v4_room", "v4_ppa_need")},
    "v4_net_charge": [(4, "net_charge_example")],
    "v4_gap": [(4, "net_charge_example"), (4, "tou_tariff"), (4, "fuel_adj"), (4, "power_fund_rate"), (4, "solar_shape_p"), (4, "cfd_price")],
    "v4_rec_end": [(4, "rec_eligible")],
    "v4_rec_none": [(4, "rec_eligible")],
}
DIRECT = {"v2_target_dscr", "v4_hurdle", "v4_cfd_dscr_target", "v4_cf_base", "v4_cfd_price", "v4_net_charge", "v4_rec_end", "v4_rec_none",
          "v3_npm_floor", "v3_npm_now", "v4_smp_base", "v4_ktb"}      # 입력을 그대로 옮긴 값 → 그 입력의 등급 (계산값 최소 D 규칙 미적용)
DOC_REFS = {"v4_proviso": "A"}  # 고시 원문 조항 (Vol.4 입력 아님, config net_charge_basis에 출처 A로 기록)


def assign_tiers(refs: dict[str, Ref], grades: list[Grade], order: list[str]) -> None:
    gmap = {(g.vol, g.key): g for g in grades}
    for k, r in refs.items():
        if k in DOC_REFS:
            r.tier = DOC_REFS[k]
            continue
        t, wk, we = weakest(DRIVERS.get(k, []), gmap, order, floor=None if k in DIRECT else "D")
        r.tier, r.weakest_kr, r.weakest_en = t, wk, we


def check_refs(refs: dict[str, Ref], pages: Mapping[tuple[int, str], Mapping[str, str]], summaries: Mapping[int, str]) -> None:
    for r in refs.values():
        txt = pages.get((r.vol, "kr"), {}).get(r.page, "")
        r.page_ok = bool(txt) and all(n in txt for n in r.needles)
        r.summary_ok = (all(n in summaries.get(r.vol, "") for n in r.summary)) if r.summary else None


# ---------------------------------------------------------------------------
# 판정 (저자 판단 J — 규칙도 판단)
# ---------------------------------------------------------------------------
def verdicts(refs: Mapping[str, Ref]) -> list[Asset]:
    V = lambda k: refs[k].value  # noqa: E731
    h = V("v4_hurdle")
    out = []
    v = "invest" if V("v4_irr_cfd") >= h else "wait"
    out.append(Asset("cfd_equity", 4, v, ["v4_irr_cfd", "v4_cfd_gearing", "v4_cfd_dscr"], ["v4_cfd_cf_low", "v4_cfd_capex_hi"],
                     "지분 IRR ≥ 요구수익률, 매출은 한전 장기 계약 — 뒤집는 가정(이용률)은 P90 실사를 선행조건으로 관리", "Equity IRR ≥ hurdle; revenue under a long KEPCO contract — the flipping assumption (output) is managed by a P90 study as a CP"))
    v = "invest" if V("v2_min_dscr") >= V("v2_target_dscr") else "wait"
    out.append(Asset("dc_pf_loan", 2, v, ["v2_min_dscr", "v2_debt", "v2_gearing"], ["v2_dscr_gross", "v2_irr_gross", "v2_debt_gross"],
                     "최소 DSCR ≥ 목표 DSCR — 단, 전력비 별도 청구가 선행조건", "Min DSCR ≥ target — with separate power billing as a condition precedent"))
    lo_room = max(V("v4_room"))
    v = "avoid" if V("v4_irr_ppa") < h else ("wait" if lo_room < V("v4_net_charge") else "invest")
    out.append(Asset("direct_ppa", 4, v, ["v4_irr_ppa"], ["v4_room", "v4_net_charge", "v4_gap"],
                     "수익률은 되지만 구매자 여유 < 공개 사례 부대비용 → 거래가 아직 안 닫힘", "Returns clear, but the buyer's room < public charges, so the deal does not close yet"))
    v = "wait" if V("v3_req_alt") > max(V("v3_band_disc")) else "invest"
    out.append(Asset("target_ipo", 3, v, ["v3_band", "v3_band_disc"], ["v3_req_dp", "v3_req_alt"],
                     "필요 할인율(이익률 하한 두 가정 모두) > 밴드 최대 할인율", "Required discount (both margin floors) > the range's widest discount"))
    v = "avoid" if V("v4_irr_merchant") < h else "wait"
    out.append(Asset("merchant_solar", 4, v, ["v4_irr_merchant", "v4_rec_none"], ["v4_merchant_smp_hi", "v4_merchant_actual"],
                     "지분 IRR < 요구수익률, REC 없음", "Equity IRR < hurdle; no RECs"))
    out.append(Asset("legacy_rec", 4, "avoid", ["v4_rec_end"], [],
                     "REC 현물시장 종료 예정(보도 B) — 수치 모델 없이 정성 판단", "REC spot market set to end (press B) — qualitative, no model"))
    v = "avoid" if V("v1_mult_op") > 0.5 else "wait"
    out.append(Asset("listed_equip", 1, v, ["v1_per", "v1_mult_ni", "v1_mult_op"], ["v3_per"],
                     "4사 영업이익 기준 멀티플 기여 > 50%(멀티플 주도) — 추격 매수는 배수 유지에 기대는 것", "Multiple-led on 4-name operating income (> 50%) — chasing relies on the multiple holding"))
    return out


# ---------------------------------------------------------------------------
# 정정 기록 (git 대조)
# ---------------------------------------------------------------------------
def _git_show(rev: str, path: str) -> str | None:
    try:
        r = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=resolve_path("."), capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def load_corrections(cfg: Mapping, verify: bool = True) -> list[dict]:
    """정정 기록 CSV + git 대조: 첫 커밋의 부모 build_summary에 check_before, 마지막 커밋에 check_after가 있고 check_before는 사라졌는지."""
    p = resolve_path(cfg["research"]["vol05"]["corrections_csv"])
    with open(p, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["vol"] = int(r["vol"])
        r["verified"] = None
        if not verify:
            continue
        path = f"{cfg['research'][f'vol0{r['vol']}']['output_dir']}/build_summary.md"
        before, after = _git_show(f"{r['commit_first']}^", path), _git_show(r["commit_last"], path)
        if before is None or after is None:
            continue                                            # git 없음·얕은 이력 → 미확인
        r["verified"] = (r["check_before"] in before) and (r["check_after"] in after) and (r["check_before"] not in after)
    return rows


# ---------------------------------------------------------------------------
# 전체
# ---------------------------------------------------------------------------
def load_facts(cfg: Mapping, vols: Mapping[int, Any] | None = None) -> Facts:
    v = cfg["research"]["vol05"]
    order = list(v["grading"]["order"])
    vols = dict(vols or load_vols(cfg))
    pages = stories(cfg, vols)
    sums = summary_texts(cfg)
    grades = grade_inputs(cfg, vols)
    refs = build_refs(cfg, vols)
    assign_tiers(refs, grades, order)
    check_refs(refs, pages, sums)
    heads = {}
    for n in VOLS:
        kr, sk = pages[(n, "kr")].get("_headline", ""), summary_headline(sums[n])
        heads[n] = {"kr": sk or kr, "en": pages[(n, "en")].get("_headline", ""), "story_kr": kr, "match": bool(sk) and sk == kr}
    return Facts(v["as_of"], vols, refs, verdicts(refs), heads, grades, distribution(grades, order), load_corrections(cfg), pages,
                 {"order": order})
