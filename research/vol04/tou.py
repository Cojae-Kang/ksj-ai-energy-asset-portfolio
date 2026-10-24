"""산업용(을) 계절·시간대별 요금 → '태양광 시간대 회피 전력량요금'(원/kWh, 발전량 가중). 순수 함수.

공식 원문: 기후에너지환경부·한전 보도참고자료 「계절·시간대별 전기요금 체계 개편안 공개」(2026-03-13)
  - PDF 8쪽(전체 9쪽) [붙임2]: 개편 전·후 시간대 구분표와 산업용(을) 고압A·B·C 선택Ⅰ·Ⅱ·Ⅲ 기본요금·전력량요금
  - PDF 2쪽 그림: 일요일·공휴일은 하루 종일 경부하 요금, 봄·가을 11~14시는 그 50% (고압A 선택2·봄·가을 예시)
  - PDF 3쪽·7쪽: 봄(3~5월)·가을(9~10월) 주말·공휴일 11~14시 50% 할인, 2030-12-31까지
월 가중치: 한전 전력통계월보 제566호 시트 '16-1.태양광 발전량 추계정보'(2025년 월별, 시장·한전PPA·자가용 합)

요금표는 두 경로로 옮기고 서로 대조한다: (1) 손 입력 표 HAND_RATES (PDF 8쪽 이미지를 보고 입력)
(2) sources.tou_from_pdf(): pdftotext로 같은 쪽을 기계 추출. 둘이 다르면 산출 파일을 만들지 않는다.
세 번째 대조: PDF 8쪽 머리 문구(경부하 +5.1원, 중간부하 미조정, 최대부하 여름·겨울 −16.9원·봄가을 −13.2원).

하루 시간별 발전 형상: 저장소에 공식 시간별 태양광 발전량이 없어 표준 형상(저자 판단)을 쓴다.
  출력 ∝ max(cos 천정각, 0)^p — 천정각은 Spencer(1971) 적위·균시차식, 대표 지점 위·경도, 한국 표준시(동경 135°)
  p = 1 기준, 0.5(아침·저녁 비중 큼)·2(한낮 집중) 민감도. TODO(data): 공공데이터포털 '한국전력거래소 시간별 태양광 발전량'
"""
from __future__ import annotations

import calendar
import datetime as dt
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

SEASONS = ("summer", "spring_autumn", "winter")
SEASON_KR = {"summer": "여름(6~8월)", "spring_autumn": "봄·가을(3~5, 9~10월)", "winter": "겨울(11~2월)"}
SEASON_EN = {"summer": "Summer (Jun–Aug)", "spring_autumn": "Spring/autumn (Mar–May, Sep–Oct)", "winter": "Winter (Nov–Feb)"}
SEASON_OF_MONTH = {m: ("summer" if m in (6, 7, 8) else "spring_autumn" if m in (3, 4, 5, 9, 10) else "winter") for m in range(1, 13)}
BANDS = ("off", "mid", "peak")                 # 경부하 · 중간부하 · 최대부하
BAND_KR = {"off": "경부하", "mid": "중간부하", "peak": "최대부하"}
DISCOUNT_HOURS = (11, 12, 13)                  # 11:00~14:00
VOLTAGES = ("고압A", "고압B", "고압C")
OPTIONS = ("선택Ⅰ", "선택Ⅱ", "선택Ⅲ")

# --- (1) 손 입력: PDF 8쪽 [붙임2] 표 (계절 순서 여름 · 봄가을 · 겨울) ----------------------------------
# {regime: {(전압, 선택): (기본요금 원/kW, {band: (여름, 봄가을, 겨울)})}}
HAND_RATES: dict[str, dict[tuple[str, str], tuple[int, dict[str, tuple[float, float, float]]]]] = {
    "before": {
        ("고압A", "선택Ⅰ"): (7220, {"off": (116.4, 116.4, 123.4), "mid": (169.3, 138.9, 169.5), "peak": (251.4, 169.6, 227.0)}),
        ("고압A", "선택Ⅱ"): (8320, {"off": (110.9, 110.9, 117.9), "mid": (163.8, 133.4, 164.0), "peak": (245.9, 164.1, 221.5)}),
        ("고압A", "선택Ⅲ"): (9810, {"off": (110.0, 110.0, 117.3), "mid": (163.2, 132.1, 163.4), "peak": (233.5, 155.8, 210.3)}),
        ("고압B", "선택Ⅰ"): (6630, {"off": (126.3, 126.3, 133.3), "mid": (178.6, 148.6, 178.6), "peak": (259.8, 178.9, 234.8)}),
        ("고압B", "선택Ⅱ"): (7380, {"off": (122.5, 122.5, 129.5), "mid": (174.8, 144.8, 174.8), "peak": (256.0, 175.1, 231.0)}),
        ("고압B", "선택Ⅲ"): (8190, {"off": (120.8, 120.8, 127.9), "mid": (173.1, 143.2, 173.1), "peak": (254.4, 173.5, 229.3)}),
        ("고압C", "선택Ⅰ"): (6590, {"off": (125.8, 125.8, 132.7), "mid": (178.7, 148.7, 178.3), "peak": (259.6, 179.1, 234.9)}),
        ("고압C", "선택Ⅱ"): (7520, {"off": (121.1, 121.1, 128.0), "mid": (174.0, 144.0, 173.6), "peak": (254.9, 174.4, 230.2)}),
        ("고압C", "선택Ⅲ"): (8090, {"off": (120.0, 120.0, 126.9), "mid": (172.9, 142.9, 172.5), "peak": (253.8, 173.3, 229.1)}),
    },
    "after": {
        ("고압A", "선택Ⅰ"): (7220, {"off": (121.5, 121.5, 128.5), "mid": (169.3, 138.9, 169.5), "peak": (234.5, 156.4, 210.1)}),
        ("고압A", "선택Ⅱ"): (8320, {"off": (116.0, 116.0, 123.0), "mid": (163.8, 133.4, 164.0), "peak": (229.0, 150.9, 204.6)}),
        ("고압A", "선택Ⅲ"): (9810, {"off": (115.1, 115.1, 122.4), "mid": (163.2, 132.1, 163.4), "peak": (216.6, 142.6, 193.4)}),
        ("고압B", "선택Ⅰ"): (6630, {"off": (131.4, 131.4, 138.4), "mid": (178.6, 148.6, 178.6), "peak": (242.9, 165.7, 217.9)}),
        ("고압B", "선택Ⅱ"): (7380, {"off": (127.6, 127.6, 134.6), "mid": (174.8, 144.8, 174.8), "peak": (239.1, 161.9, 214.1)}),
        ("고압B", "선택Ⅲ"): (8190, {"off": (125.9, 125.9, 133.0), "mid": (173.1, 143.2, 173.1), "peak": (237.5, 160.3, 212.4)}),
        ("고압C", "선택Ⅰ"): (6590, {"off": (130.9, 130.9, 137.8), "mid": (178.7, 148.7, 178.3), "peak": (242.7, 165.9, 218.0)}),
        ("고압C", "선택Ⅱ"): (7520, {"off": (126.2, 126.2, 133.1), "mid": (174.0, 144.0, 173.6), "peak": (238.0, 161.2, 213.3)}),
        ("고압C", "선택Ⅲ"): (8090, {"off": (125.1, 125.1, 132.0), "mid": (172.9, 142.9, 172.5), "peak": (236.9, 160.1, 212.2)}),
    },
}
# PDF 8쪽 머리 문구: 개편 후 − 개편 전 (원/kWh) — 세 번째 대조
STATED_CHANGE = {"off": (5.1, 5.1, 5.1), "mid": (0.0, 0.0, 0.0), "peak": (-16.9, -13.2, -16.9)}

# 시간대 구분 (평일, PDF 8쪽 상단 표) — (시작시, 끝시) 반열린 구간 [시작, 끝), 22~08은 자정을 넘김
HAND_BANDS: dict[str, dict[str, dict[str, tuple[tuple[int, int], ...]]]] = {
    "before": {
        "summer": {"off": ((22, 8),), "mid": ((8, 11), (12, 13), (18, 22)), "peak": ((11, 12), (13, 18))},
        "spring_autumn": {"off": ((22, 8),), "mid": ((8, 11), (12, 13), (18, 22)), "peak": ((11, 12), (13, 18))},
        "winter": {"off": ((22, 8),), "mid": ((8, 9), (12, 16), (19, 22)), "peak": ((9, 12), (16, 19))},
    },
    "after": {
        "summer": {"off": ((22, 8),), "mid": ((8, 15), (21, 22)), "peak": ((15, 21),)},
        "spring_autumn": {"off": ((22, 8),), "mid": ((8, 15), (21, 22)), "peak": ((15, 21),)},
        "winter": {"off": ((22, 8),), "mid": ((8, 9), (12, 16), (19, 22)), "peak": ((9, 12), (16, 19))},
    },
}


def rates_frame(src: Mapping = HAND_RATES) -> pd.DataFrame:
    """요금 dict → 긴 표 (regime, voltage, option, basic_krw_per_kw, season, band, krw_per_kwh)."""
    rows = []
    for regime, tab in src.items():
        for (v, o), (basic, bands) in tab.items():
            for b, vals in bands.items():
                for s, x in zip(SEASONS, vals):
                    rows.append({"regime": regime, "voltage": v, "option": o, "basic_krw_per_kw": int(basic), "season": s, "band": b,
                                 "krw_per_kwh": float(x)})
    return pd.DataFrame(rows)


def bands_frame(src: Mapping = HAND_BANDS) -> pd.DataFrame:
    """시간대 구분 → 시간별 표 (regime, season, hour 0~23, band). hour h = h:00~h+1:00."""
    rows = []
    for regime, seasons in src.items():
        for s, bands in seasons.items():
            hb = hour_bands(bands)
            rows += [{"regime": regime, "season": s, "hour": h, "band": hb[h]} for h in range(24)]
    return pd.DataFrame(rows)


def hour_bands(bands: Mapping[str, Sequence[tuple[int, int]]]) -> list[str]:
    out: list[str | None] = [None] * 24
    for b, spans in bands.items():
        for a, e in spans:
            hrs = range(a, e) if a < e else list(range(a, 24)) + list(range(0, e))
            for h in hrs:
                if out[h] is not None:
                    raise ValueError(f"시간대 중복: {h}시 {out[h]}/{b}")
                out[h] = b
    if any(x is None for x in out):
        raise ValueError(f"시간대 누락: {[h for h, x in enumerate(out) if x is None]}")
    return out  # type: ignore[return-value]


def check_stated_change(rates: pd.DataFrame, tol: float = 1e-6) -> list[str]:
    """개편 후 − 개편 전 = PDF 8쪽 머리 문구. 어긋나는 칸 목록(빈 목록이면 통과)."""
    piv = rates.pivot_table(index=["voltage", "option", "season", "band"], columns="regime", values="krw_per_kwh")
    bad = []
    for (v, o, s, b), r in piv.iterrows():
        want = STATED_CHANGE[b][SEASONS.index(s)]
        if abs((r["after"] - r["before"]) - want) > tol + 1e-9:
            bad.append(f"{v} {o} {s} {b}: {r['after'] - r['before']:+.1f} ≠ {want:+.1f}")
    return bad


# --- 태양 위치·발전 형상 ----------------------------------------------------------------------------
def solar_hourly_shape(year: int, lat: float, lon: float, p: float = 1.0, step_min: int = 1) -> pd.DataFrame:
    """월별 하루 시간대 발전 비중 (행 = 월 1~12, 열 = 시 0~23, 행 합 = 1).
    출력 ∝ max(cos 천정각, 0)^p를 그 달 모든 날에 대해 분 단위로 적분. 시각은 한국 표준시(UTC+9, 기준 경도 135°E)."""
    days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    n = days.dayofyear.values.astype(float)
    B = 2 * np.pi * (n - 1) / 365.0
    decl = (0.006918 - 0.399912 * np.cos(B) + 0.070257 * np.sin(B) - 0.006758 * np.cos(2 * B) + 0.000907 * np.sin(2 * B)
            - 0.002697 * np.cos(3 * B) + 0.00148 * np.sin(3 * B))
    eot = 229.18 * (0.000075 + 0.001868 * np.cos(B) - 0.032077 * np.sin(B) - 0.014615 * np.cos(2 * B) - 0.040849 * np.sin(2 * B))
    t = (np.arange(0, 1440, step_min) + step_min / 2) / 60.0                               # 표준시(시)
    solar_t = t[None, :] + ((4 * (lon - 135.0) + eot) / 60.0)[:, None]
    omega = np.radians(15.0 * (solar_t - 12.0))
    phi = np.radians(lat)
    cz = np.sin(phi) * np.sin(decl)[:, None] + np.cos(phi) * np.cos(decl)[:, None] * np.cos(omega)
    g = np.clip(cz, 0, None) ** p
    hour = (t // 1).astype(int)
    by_hour = np.stack([g[:, hour == h].sum(axis=1) for h in range(24)], axis=1)          # 일 × 24
    m = pd.DataFrame(by_hour, index=days.month).groupby(level=0).sum()
    return m.div(m.sum(axis=1), axis=0)


def day_counts(year: int) -> pd.DataFrame:
    """월별 평일·토요일·일요일 수 (평일 공휴일은 반영하지 않음 — 공휴일 목록 원문 없음)."""
    rows = []
    for mth in range(1, 13):
        wd = [dt.date(year, mth, d).weekday() for d in range(1, calendar.monthrange(year, mth)[1] + 1)]
        rows.append({"month": mth, "weekday": sum(x < 5 for x in wd), "saturday": sum(x == 5 for x in wd), "sunday": sum(x == 6 for x in wd)})
    return pd.DataFrame(rows).set_index("month")


def day_rates(rates: pd.DataFrame, bands: pd.DataFrame, voltage: str, option: str, regime: str = "after",
              saturday: str = "weekday", discount: float = 0.5) -> dict[str, dict[str, np.ndarray]]:
    """계절 × 요일 유형 → 24시간 전력량요금(원/kWh).
    평일 = 시간대 구분표 · 일요일(공휴일) = 하루 종일 경부하 · 토요일 = 평일과 같음(saturday='weekday') 또는 최대부하를 중간부하로('peak_to_mid')
    봄·가을 토·일 11~14시 = (1 − discount) 배 (개편 후만, discount=0이면 할인 없음)."""
    r = rates[(rates.regime == regime) & (rates.voltage == voltage) & (rates.option == option)]
    if r.empty:
        raise KeyError(f"요금 없음: {regime} {voltage} {option}")
    out: dict[str, dict[str, np.ndarray]] = {}
    for s in SEASONS:
        price = {b: float(r[(r.season == s) & (r.band == b)]["krw_per_kwh"].iloc[0]) for b in BANDS}
        hb = bands[(bands.regime == regime) & (bands.season == s)].sort_values("hour")["band"].tolist()
        wk = np.array([price[b] for b in hb])
        sat = wk.copy() if saturday == "weekday" else np.array([price["mid" if b == "peak" else b] for b in hb])
        sun = np.full(24, price["off"])
        if regime == "after" and s == "spring_autumn" and discount:
            for arr in (sat, sun):
                arr[list(DISCOUNT_HOURS)] *= (1 - discount)
        out[s] = {"weekday": wk, "saturday": sat, "sunday": sun}
    return out


def avoided_rate(rates: pd.DataFrame, bands: pd.DataFrame, month_gen: Mapping[int, float], shape: pd.DataFrame, days: pd.DataFrame,
                 voltage: str = "고압A", option: str = "선택Ⅱ", regime: str = "after", saturday: str = "weekday",
                 discount: float = 0.5) -> dict:
    """태양광이 대신하는 전력량요금(원/kWh): 월 = Σ_요일유형 일수 × Σ_시 형상 × 요금 ÷ 일수, 계절·연간 = 월 발전량 가중평균.
    기본요금(원/kW)은 PPA로 줄지 않아 넣지 않는다."""
    dr = day_rates(rates, bands, voltage, option, regime, saturday, discount)
    month = {}
    for m in range(1, 13):
        s = SEASON_OF_MONTH[m]
        w = shape.loc[m].values
        n = days.loc[m]
        month[m] = float(sum(n[k] * float(w @ dr[s][k]) for k in ("weekday", "saturday", "sunday")) / n.sum())
    g = {m: float(month_gen[m]) for m in range(1, 13)}

    def wavg(ms: Sequence[int]) -> float:
        return sum(month[m] * g[m] for m in ms) / sum(g[m] for m in ms)
    season = {s: wavg([m for m in range(1, 13) if SEASON_OF_MONTH[m] == s]) for s in SEASONS}
    share = {s: sum(g[m] for m in range(1, 13) if SEASON_OF_MONTH[m] == s) / sum(g.values()) for s in SEASONS}
    return {"annual": wavg(range(1, 13)), "season": season, "month": month, "gen_share": share,
            "voltage": voltage, "option": option, "regime": regime, "saturday": saturday, "discount": discount}


def band_shares(bands: pd.DataFrame, shape: pd.DataFrame, month_gen: Mapping[int, float], regime: str = "after") -> dict[str, dict[str, float]]:
    """평일 기준: 계절별 발전량이 경부하·중간·최대 시간대에 떨어지는 비중 (발전량 가중)."""
    out = {}
    for s in SEASONS:
        hb = bands[(bands.regime == regime) & (bands.season == s)].sort_values("hour")["band"].values
        ms = [m for m in range(1, 13) if SEASON_OF_MONTH[m] == s]
        w = sum(shape.loc[m].values * float(month_gen[m]) for m in ms)
        w = w / w.sum()
        out[s] = {b: float(w[hb == b].sum()) for b in BANDS}
    return out
