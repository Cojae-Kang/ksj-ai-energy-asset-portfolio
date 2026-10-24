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


def run(as_of: str = "2026-10-20") -> dict:
    m = monthly_smp()
    s = smp_stats(m, as_of)
    h, hname, herr = land_hourly(m)
    w = h.loc[pd.Timestamp(s["smp_window"][:7] + "-01"): pd.Timestamp(s["smp_window"][-7:] + "-01") + pd.offsets.MonthEnd(0)]
    s.update(hourly_file=hname, hourly_match_err=herr, smp_allhours=float(np.nanmean(w[HOURS].values)),
             smp_daylight=float(np.nanmean(w[[f"{x:02d}시" for x in range(10, 17)]].values)), monthly_file=m.attrs["file"])
    k = kepco_industrial()
    out = {**s, **k}
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


def main() -> int:
    r = run()
    for k, v in r.items():
        print(f"{k}: {v if not isinstance(v, float) else round(v, 4)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
