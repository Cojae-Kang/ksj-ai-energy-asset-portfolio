"""Vol.4 공식 원문 → 입력값 (재현용). 원본은 data/manual/vol04_sources/에 받은 그대로 두고 여기서만 계산한다.

    python -m research.vol04.sources          # data/processed/vol04_official.csv(+ .meta.json) 생성, 값 출력

- 전력거래소 EPSIS '계통한계가격_가중평균SMP' (월별, 육지·제주·통합): 최근 12개월 육지 평균, 연평균(1~12월 다 있는 해)
  → 연평균 로그의 AR(1) 계수·잔차 표준편차 (몬테카를로 smp_phi·smp_sigma)
- 전력거래소 EPSIS '계통한계가격_시간별SMP' (일별 24시간): 육지 파일 판정(월 가중평균과 대조) → 주간(10~16시) 평균 교차 확인
- 한전 전력통계월보 제566호(2025.12) 표 18·18-2: 2025.01~12 산업용 판매수입 ÷ 판매전력량 = 판매단가
- 에너지경제연구원 설치비 연구·LCOE는 PDF 원문 수치를 입력 파일에 직접 적고 쪽을 기록 (표 추출 없음)
"""
from __future__ import annotations

import glob
import json
import math
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from src.data_fetch.base import resolve_path, utc_now_iso

SRC = "data/manual/vol04_sources"
HOURS = [f"{h:02d}시" for h in range(1, 25)]


def _one(pattern: str, exclude: str | None = None) -> Path:
    fs = [Path(p) for p in glob.glob(str(resolve_path(SRC) / pattern)) if not (exclude and exclude in Path(p).name)]
    if not fs:
        raise FileNotFoundError(pattern)
    return sorted(fs)[0]


def monthly_smp() -> pd.DataFrame:
    f = _one("*가중평균SMP*.xlsx")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = pd.read_excel(f, header=None, skiprows=2, names=["ym", "land", "jeju", "total", "blmp"])
    m["ym"] = pd.to_datetime(m["ym"], format="%Y/%m")
    m = m.set_index("ym").sort_index()
    for c in ("land", "jeju", "total"):
        m[c] = pd.to_numeric(m[c], errors="coerce")
    m["smp"] = np.where(m["land"] > 0, m["land"], m["total"])      # 2010년 이전은 육지 구분 없음 → 통합
    m.attrs["file"] = f.name
    return m


def hourly(f: Path) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        d = pd.read_excel(f, header=0).rename(columns={"기간": "date"})
    d["date"] = pd.to_datetime(d["date"], format="%Y/%m/%d")
    for c in d.columns[1:]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d.set_index("date").sort_index()


def land_hourly(m: pd.DataFrame) -> tuple[pd.DataFrame, str, float]:
    """시간별 파일 중 육지 파일: 일 가중평균의 월평균이 월별 육지 SMP와 가장 가까운 파일."""
    best = None
    for p in glob.glob(str(resolve_path(SRC) / "*시간별SMP*.xlsx")):
        h = hourly(Path(p))
        s = h["가중평균"].resample("MS").mean()
        j = m.join(s.rename("h"), how="inner")
        j = j[j["land"] > 0]
        err = float((j["h"] - j["land"]).abs().mean())
        if best is None or err < best[2]:
            best = (h, Path(p).name, err)
    return best


def smp_stats(m: pd.DataFrame, end: str) -> dict:
    end_ts = pd.Timestamp(end)
    last = m.loc[:end_ts, "smp"].dropna().iloc[-12:]
    yr = m["smp"].resample("YS").mean()
    yr = yr[m["smp"].resample("YS").count() == 12]
    ly = np.log(yr.values)
    X = np.c_[np.ones(len(ly) - 1), ly[:-1]]
    b, *_ = np.linalg.lstsq(X, ly[1:], rcond=None)
    res = ly[1:] - X @ b
    return {"smp_base": float(last.mean()), "smp_min_month": float(last.min()), "smp_max_month": float(last.max()),
            "smp_window": f"{last.index[0]:%Y-%m}~{last.index[-1]:%Y-%m}", "smp_phi": float(b[1]),
            "smp_sigma": float(res.std(ddof=2)), "smp_years": f"{yr.index[0].year}~{yr.index[-1].year}", "smp_n_years": int(len(yr)),
            "annual": {int(k.year): round(float(v), 2) for k, v in yr.items()}}


def kepco_industrial(year: int = 2025) -> dict:
    f = _one("*전력통계월보*.xlsx")
    vol = pd.read_excel(f, sheet_name="18.계약종별 판매전력량", header=None)
    rev = pd.read_excel(f, sheet_name="18-2.계약종별 판매수입", header=None)
    key = f"{year}.01~12"
    col = next(i for i, v in enumerate(vol.iloc[3]) if isinstance(v, str) and v.replace(" ", "") == "산업용")
    rv = vol[vol[0].astype(str).str.strip() == key]
    rr = rev[rev[0].astype(str).str.strip() == key]
    mwh, mn = float(rv.iloc[0, col]), float(rr.iloc[0, col])
    return {"kepco_industrial_price": mn * 1e6 / (mwh * 1e3), "industrial_mwh": mwh, "industrial_rev_mn": mn, "file": f.name,
            "sheets": "18.계약종별 판매전력량 · 18-2.계약종별 판매수입", "row": key}


def solar_cf(year: int = 2025) -> dict:
    """전력통계월보 16-1(태양광 발전량 추계: 시장·한전PPA·자가용) 연간 합 ÷ 2-1(연말 태양광 설비 kW × 8,760h)."""
    f = _one("*전력통계월보*.xlsx")
    g = pd.read_excel(f, sheet_name="16-1.태양광 발전량 추계정보", header=None)
    r = g[g[0].astype(str).str.startswith(f"{year}.")]
    num = lambda v: float(str(v).replace(",", ""))  # noqa: E731
    mwh = sum(num(v) for c in (1, 2, 3) for v in r[c])
    cap = pd.read_excel(f, sheet_name="2-1. 발전설비용량(발전원별에너지원별)", header=None)
    row = cap[cap[0].astype(str).str.strip() == "태양에너지"].iloc[0]
    kw = max(float(v) for v in row.tolist()[1:] if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)))
    return {"solar_mwh": mwh, "solar_kw_yearend": kw, "solar_cf_check": mwh * 1000 / (kw * 8760), "solar_months": int(len(r))}


def run(as_of: str = "2026-10-20") -> dict:
    m = monthly_smp()
    s = smp_stats(m, as_of)
    h, hname, herr = land_hourly(m)
    w = h.loc[pd.Timestamp(s["smp_window"][:7] + "-01"): pd.Timestamp(s["smp_window"][-7:] + "-01") + pd.offsets.MonthEnd(0)]
    s.update(hourly_file=hname, hourly_match_err=herr, smp_allhours=float(np.nanmean(w[HOURS].values)),
             smp_daylight=float(np.nanmean(w[[f"{x:02d}시" for x in range(10, 17)]].values)), monthly_file=m.attrs["file"])
    k = kepco_industrial()
    out = {**s, **k, **solar_cf()}
    rows = [{"key": a, "value": v} for a, v in out.items() if not isinstance(v, dict)]
    p = resolve_path("data/processed/vol04_official.csv")
    p.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(p, index=False, encoding="utf-8-sig")
    meta = {"source": "전력거래소 EPSIS(계통한계가격 가중평균·시간별 SMP 엑셀), 한전 전력통계월보 제566호(2025.12) 엑셀",
            "endpoint": None, "params": {"as_of": as_of}, "fetched_at": utc_now_iso(), "as_of": as_of,
            "files": [m.attrs["file"], hname, k["file"]],
            "method": "SMP 기준값 = 최근 12개월 월별 육지 가중평균 SMP 평균; 변동성·평균회귀 = 연평균(12개월 완비 연도) 로그의 AR(1) 회귀 잔차 표준편차·계수; "
                      "2010년 이전은 육지 구분이 없어 통합 SMP; 산업용 판매단가 = 2025.01~12 산업용 판매수입(백만원) ÷ 판매전력량(MWh)",
            "license_note": "공공기관 공개 통계(전력거래소·한전) — 출처 표시"}
    p.with_suffix(".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


TOU_PDF = "계절*시간대별*개편안*.pdf"
TOU_PAGE = 8          # PDF 8쪽(전체 9쪽) [붙임2]


def tou_from_pdf() -> dict | None:
    """요금표 기계 추출: pdftotext -layout으로 8쪽을 읽어 '경·중간·최대부하' 줄(숫자 6개 = 개편 전 3계절 + 개편 후 3계절) 27개를
    고압A·B·C × 선택Ⅰ·Ⅱ·Ⅲ × 경·중간·최대 순서로 읽는다. pdftotext가 없으면 None (손 입력 표만 사용)."""
    import re
    import shutil
    import subprocess

    from . import tou
    if shutil.which("pdftotext") is None:
        return None
    f = _one(TOU_PDF)
    txt = subprocess.run(["pdftotext", "-layout", "-f", str(TOU_PAGE), "-l", str(TOU_PAGE), str(f), "-"],
                         capture_output=True, text=True, check=True).stdout
    band_re = re.compile(r"(경|중간|최대)\s*부\s*하")
    lines = [ln for ln in txt.splitlines() if band_re.search(ln) and len(re.findall(r"\b\d{2,3}\.\d\b", ln)) == 6]
    if len(lines) != 27:
        raise ValueError(f"요금 줄 {len(lines)}개 (27개여야 함) — PDF 형식 확인")
    out: dict = {"before": {}, "after": {}}
    word = {"경": "off", "중간": "mid", "최대": "peak"}
    i = 0
    for v in tou.VOLTAGES:
        for o in tou.OPTIONS:
            bands_b, bands_a, basic = {}, {}, None
            for b in tou.BANDS:
                ln = lines[i]
                i += 1
                if word[band_re.search(ln).group(1)] != b:
                    raise ValueError(f"줄 순서 어긋남: {ln}")
                x = [float(s) for s in re.findall(r"\b\d{2,3}\.\d\b", ln)]
                bands_b[b], bands_a[b] = tuple(x[:3]), tuple(x[3:])
                ks = re.findall(r"\b\d,\d{3}\b", ln)
                if ks:
                    if len(ks) != 2 or ks[0] != ks[1]:
                        raise ValueError(f"기본요금 읽기 실패: {ln}")
                    basic = int(ks[0].replace(",", ""))
            if basic is None:
                raise ValueError(f"기본요금 없음: {v} {o}")
            out["before"][(v, o)] = (basic, bands_b)
            out["after"][(v, o)] = (basic, bands_a)
    return out


def solar_monthly(year: int = 2025) -> pd.DataFrame:
    """전력통계월보 16-1: 월별 태양광 발전량(MWh) = 전력시장 참여(실적) + 한전PPA(실적) + 자가용(추계).
    엑셀에서 10월이 숫자 2025.1로 읽혀 행 순서(1~12월)로 월을 매기고 첫 행이 'YYYY.01'인지 확인한다."""
    f = _one("*전력통계월보*.xlsx")
    g = pd.read_excel(f, sheet_name="16-1.태양광 발전량 추계정보", header=None)
    r = g[g[0].astype(str).str.startswith(f"{year}.")]
    if len(r) != 12 or str(r.iloc[0, 0]).strip() != f"{year}.01":
        raise ValueError(f"{year}년 월별 행 12개가 아님: {r[0].tolist()}")
    num = lambda v: float(str(v).replace(",", ""))  # noqa: E731
    d = pd.DataFrame({"month": range(1, 13), "market_mwh": [num(v) for v in r[1]], "kepco_ppa_mwh": [num(v) for v in r[2]],
                      "self_use_mwh": [num(v) for v in r[3]]})
    d["total_mwh"] = d[["market_mwh", "kepco_ppa_mwh", "self_use_mwh"]].sum(axis=1)
    d = d.round(3)
    d.attrs["file"] = f.name
    return d


def tou_run(year: int = 2025) -> dict:
    """요금표·시간대·월별 태양광 → data/processed/vol04_tou_tariff.csv · vol04_tou_timebands.csv · vol04_solar_monthly.csv (+ .meta.json).
    손 입력 표와 PDF 기계 추출이 한 칸이라도 다르거나, 개편 전후 차이가 PDF 문구와 다르면 저장하지 않고 멈춘다."""
    from . import tou
    hand = tou.rates_frame(tou.HAND_RATES)
    pdf = tou_from_pdf()
    machine = "pdftotext 미설치 — 손 입력 표만 사용"
    if pdf is not None:
        m = tou.rates_frame(pdf)
        key = ["regime", "voltage", "option", "season", "band"]
        j = hand.merge(m, on=key, suffixes=("_hand", "_pdf"))
        diff = j[(j.krw_per_kwh_hand != j.krw_per_kwh_pdf) | (j.basic_krw_per_kw_hand != j.basic_krw_per_kw_pdf)]
        if len(j) != len(hand) or not diff.empty:
            raise ValueError(f"손 입력 ≠ PDF 추출:\n{diff}")
        machine = f"pdftotext 기계 추출 {len(m)}칸 = 손 입력 {len(hand)}칸 (전부 일치)"
    bad = tou.check_stated_change(hand)
    if bad:
        raise ValueError("개편 전후 차이가 PDF 문구와 다름: " + "; ".join(bad))
    bands = tou.bands_frame()
    sol = solar_monthly(year)
    f_pdf = _one(TOU_PDF).name
    out = resolve_path("data/processed")
    common = {"endpoint": None, "fetched_at": utc_now_iso(), "license_note": "정부·공공기관 공개 자료(기후에너지환경부·한전) — 출처 표시"}
    files = {
        "vol04_tou_tariff.csv": (hand, {
            "source": "기후에너지환경부·한국전력공사 보도참고자료 「계절·시간대별 전기요금 체계 개편안 공개」(2026-03-13)",
            "file": f_pdf, "page": f"PDF {TOU_PAGE}쪽(전체 9쪽) [붙임2] 산업용(을) 전기요금 개편 내용 — 하단 요금표(개편 前·後)",
            "params": {"regime": "before = 개편 전(현재), after = 개편 후(2026-04-16 시행, 유예 신청 시 2026-10-01)"},
            "as_of": "2026-03-13",
            "columns": {"basic_krw_per_kw": "기본요금 원/kW", "krw_per_kwh": "전력량요금 원/kWh", "season": "summer 6~8월 · spring_autumn 3~5, 9~10월 · winter 11~2월",
                        "band": "off 경부하 · mid 중간부하 · peak 최대부하"},
            "check": [machine, "개편 후 − 개편 전 = 8쪽 머리 문구(경부하 +5.1, 중간 0, 최대 여름·겨울 −16.9·봄가을 −13.2) 81칸 전부 일치",
                      "PDF 8쪽 이미지(130dpi 렌더링)와 육안 대조"]}),
        "vol04_tou_timebands.csv": (bands, {
            "source": "기후에너지환경부·한국전력공사 보도참고자료(2026-03-13)", "file": f_pdf,
            "page": f"PDF {TOU_PAGE}쪽 [붙임2] 상단 시간대 구분표(평일) · 2쪽 본문(11~12·13~15시 최대→중간, 18~21시 중간→최대) · 7쪽 [붙임1] 그림",
            "params": {"hour": "h = h:00~h+1:00 (한국 표준시)", "day": "평일 기준. 일요일·공휴일·토요일 규칙은 research/vol04/tou.py day_rates 주석"},
            "as_of": "2026-03-13"}),
        "vol04_solar_monthly.csv": (sol, {
            "source": "한국전력공사 전력통계월보 제566호(2025.12)", "file": sol.attrs["file"], "page": "시트 '16-1.태양광 발전량 추계정보'",
            "params": {"year": year, "total_mwh": "전력시장 참여(실적) + 한전PPA(실적) + 자가용태양광(추계) — 시트 주4: 자가용은 전력거래소 추정치"},
            "as_of": "2026-02"}),
    }
    for name, (df, meta) in files.items():
        p = out / name
        df.to_csv(p, index=False, encoding="utf-8-sig")
        p.with_suffix(".meta.json").write_text(json.dumps({**meta, **common}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"rates": len(hand), "machine": machine, "solar_total_mwh": float(sol["total_mwh"].sum())}


def main() -> int:
    r = run()
    for k, v in r.items():
        print(f"{k}: {v if not isinstance(v, float) else round(v, 4)}")
    for k, v in tou_run().items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
