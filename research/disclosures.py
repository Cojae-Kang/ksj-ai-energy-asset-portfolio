"""Vol.1·Vol.2 공통 고지: 포트폴리오 성격·저작권(CC BY 4.0)·코드 라이선스(MIT)·연락처. 문구는 config research.* 값을 쓴다."""
from __future__ import annotations

from typing import Mapping


def license_items(cfg: Mapping, kr: bool) -> list[str]:
    """뒤표지 Disclosures에 덧붙이는 세 줄 (국문/영문)."""
    r = cfg["research"]
    cc = r.get("content_license", "CC BY 4.0")
    year = str(r.get("copyright", "© 2026")).split()[1] if len(str(r.get("copyright", "")).split()) > 1 else "2026"
    if kr:
        return [
            "이 보고서는 IB·인프라금융 직무 준비를 위한 개인 리서치 포트폴리오이며, 분석 로직과 코드를 공개한다. 특정 금융회사·부서와 무관하다.",
            f"© {year} Shinjae Kang (강신재). 보고서·도표·문장은 {cc}로 공개한다. 인용·활용 시 원저작자 'Shinjae Kang (KSJ Research)'와 출처를 표시해야 한다.",
            "코드는 MIT 라이선스(저작권 표시 유지 조건). 인용한 제3자 데이터·자료(IEA, EIA, CBRE 등)의 권리는 각 원저작자에게 있으며 해당 이용 조건을 따른다.",
        ]
    return [
        "This report is a personal research portfolio prepared for IB and infrastructure-finance roles; its analytical logic and code are public. "
        "It is not affiliated with any financial institution or department.",
        f"© {year} Shinjae Kang. The report, charts and text are released under {cc}. Any citation or reuse must credit "
        "'Shinjae Kang (KSJ Research)' and the source.",
        "Code is under the MIT License (copyright notice must be retained). Rights in cited third-party data and materials (IEA, EIA, CBRE, etc.) "
        "remain with their owners and are subject to their terms.",
    ]


def contact_line(cfg: Mapping) -> str:
    c = cfg["research"].get("contact")
    return f"Contact: {c}" if c else ""
