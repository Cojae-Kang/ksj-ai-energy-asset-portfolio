# Fonts

| 파일 | 서체 | 라이선스 |
|---|---|---|
| `NotoSansKR-Regular.ttf` | Noto Sans KR Regular (400) | SIL Open Font License 1.1 (`OFL.txt`) |
| `NotoSansKR-Bold.ttf` | Noto Sans KR Bold (700) | SIL Open Font License 1.1 (`OFL.txt`) |

**출처**: npm 패키지 [`@fontsource/noto-sans-kr`](https://www.npmjs.com/package/@fontsource/noto-sans-kr) 5.3.1
(Google Fonts의 Noto Sans KR, Version 2.004). 저작권자: Google Inc. (OFL 원문에 Reserved Font Name 지정 없음)

**가공 내역**: 패키지가 웹용으로 쪼개 둔 unicode-range 서브셋(woff, 굵기별 125개)을 fontTools로 하나의 정적 TTF로 병합.
글리프 윤곽은 원본 그대로이며, 서브셋 간 병합 충돌을 피하려고 GSUB/GPOS/GDEF(합자·커닝) 테이블만 제외했다.
한글 음절 11,172자 전부 포함. ReportLab·matplotlib에서 쓰기 위해 TrueType(glyf) 윤곽 형식을 유지.

**대체 순서** (`research/vol01/fonts.py`): 이 폴더의 Noto Sans KR → Windows 맑은 고딕(`C:\Windows\Fonts\malgun.ttf`, `malgunbd.ttf`)
→ 그 외 OS 기본 한글 폰트. 맑은 고딕은 Windows 라이선스 대상이라 저장소에 포함하지 않는다.
