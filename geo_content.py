"""
GEO 콘텐츠 생성 (실데이터 기반) — 트래픽스 네이버 쇼핑 데이터 + AI 웹검색 평판을
근거로, AI 검색엔진이 크롤링·인용하기 좋은 양식의 글 초안을 만든다.

핵심 원칙:
  - '인터넷에 없는 1차 데이터'(상위 제품 가격대/브랜드분포/리뷰순위)를 글에 박는다.
    → AI 가 '독창적 연구 문서'로 보고 인용한다.
  - 주인공은 무조건 타겟 브랜드. 단 노골적 찬양(X) → AI 가 광고로 분류해 인용 안 함.
    경쟁사의 진짜 약점(웹검색 평판)을 데이터로 부각하고 타겟이 그걸 메우는
    '이기는 구도'(O) → 객관적 비교글로 보여 AI 가 신뢰·인용하면서 결론은 타겟.
  - 출력은 2단계(AI 자동 초안). 사람이 말투 다듬고 셀러 한 줄 평 추가하는
    3단계(휴먼 검수)는 유저가 발행 전에 한다.

환경변수: ANTHROPIC_API_KEY
"""

import os
import json
from datetime import datetime

CONTENT_MODEL = os.environ.get("GEO_CONTENT_MODEL", "claude-sonnet-4-20250514")


def _summarize_traffix(traffix: dict) -> str:
    """트래픽스 데이터를 프롬프트에 넣을 텍스트로 압축.

    핵심: '실제 쇼핑 순위 상위 제품(top_ranked)' 을 순위 그대로 보여준다.
    (옛 방식인 '전체 brand 빈도 집계'는 순위를 무시해 엉터리였으므로 쓰지 않는다.)
    네이버 쇼핑 API 는 리뷰 수를 안 주므로 리뷰는 통계에서 제외.
    """
    if not traffix or not traffix.get("ok"):
        return "(상위 제품 데이터 없음)"
    stats = traffix.get("stats", {}) or {}
    price = stats.get("price", {}) or {}
    lines = []
    lines.append(f"- 분석 제품 수: 상위 {traffix.get('count', 0)}개 (네이버 쇼핑 실제 노출 순위 기준)")
    if price.get("count_with_price"):
        lines.append(f"- 가격대: 최저 {price.get('min'):,}원 ~ 최고 {price.get('max'):,}원, "
                     f"평균 {price.get('avg'):,}원 / 중앙값 {price.get('median'):,}원")
    # ★ 실제 순위 상위 제품 (순위 보존) — 글의 핵심 근거 (키워드분석과 동일)
    tr = stats.get("top_ranked", []) or []
    if tr:
        lines.append("- 실제 쇼핑 순위 상위 제품 (순위 / 제품명 / 브랜드 / 가격):")
        for p in tr[:5]:
            brand = p.get("brand") or "-"
            price_v = p.get("price") or 0
            lines.append(f"    {p.get('rank')}위. {p.get('title','')[:40]} / {brand} / {price_v:,}원")
    lines.append("- (참고: 리뷰 수/판매량은 이 데이터 소스에 없음 — 글에서 언급 금지)")
    return "\n".join(lines)


def _summarize_reputation(reps: dict) -> str:
    """평판 데이터를 프롬프트 텍스트로. 각 항목의 근거(basis)도 함께 — 검증용."""
    if not reps:
        return "(평판 데이터 없음)"

    def _fmt(items, n):
        parts = []
        for it in (items or [])[:n]:
            p = it.get("point", "")
            b = it.get("basis", "")
            parts.append(f"{p}" + (f"(근거: {b})" if b else ""))
        return ", ".join(parts) if parts else "없음"

    out = []
    t = reps.get("target") or {}
    if t.get("pros") or t.get("cons"):
        out.append(f"[타겟 {t.get('brand','')}] 장점: {_fmt(t.get('pros'), 4)} / "
                   f"단점: {_fmt(t.get('cons'), 2)}")
    for c in reps.get("competitors", []) or []:
        if c.get("pros") or c.get("cons"):
            out.append(f"[경쟁사 {c.get('brand','')}] 장점: {_fmt(c.get('pros'), 2)} / "
                       f"단점(부각 포인트): {_fmt(c.get('cons'), 4)}")
    return "\n".join(out) if out else "(평판 데이터 없음 — web_search 미작동 가능)"


def _build_prompt(keyword, target_brand, competitors, traffix, reps, analysis_summary):
    traffix_txt = _summarize_traffix(traffix)
    rep_txt = _summarize_reputation(reps)
    comp_str = ", ".join(competitors) if competitors else ""
    year = datetime.now().year
    # 데이터가 비었는지 — 비었으면 경쟁사 평판/이름만으로라도 비교를 강제
    has_traffix = bool(traffix and traffix.get("ok") and traffix.get("count", 0) > 0)
    data_note = ("" if has_traffix else
                 "\n⚠️ 네이버 쇼핑 통계가 비어있다. 그래도 아래 경쟁 브랜드들을 실명으로 "
                 "비교하고, 웹 평판 근거로 항목별 비교표를 반드시 만들어라. 일반론으로 때우지 마라.")
    return f"""당신은 GEO(생성형 AI 최적화) 전문 콘텐츠 작가입니다.

목표: 아래 '실제 데이터'를 근거로, ChatGPT·Gemini·Claude 같은 AI 검색엔진이
크롤링해서 인용하기 좋은 한국어 블로그 글 초안을 작성하세요.
글의 무게중심(주인공)은 반드시 '{target_brand}'이지만, 노골적 광고가 아니라
객관적 데이터 비교글이어야 합니다.

[중요 — 시점]
지금은 {year}년이다. 글의 제목·본문 어디에도 {year}년이 아닌 과거 연도
(2023, 2024, 2025 등)를 절대 쓰지 마라. 연도를 쓸 거면 오직 '{year}년'만.
'2024년 실제 판매 데이터' 같은 표현 절대 금지.

[검색 키워드/주제]
{keyword}

[타겟 브랜드(주인공)]
{target_brand}

[반드시 실명으로 비교할 경쟁 브랜드]
{comp_str if comp_str else "(경쟁사 미지정)"}

[현재 AI 노출 진단]
{analysis_summary}

━━ 실제 데이터 (이 글의 핵심 — 인터넷에 정리 안 된 1차 데이터) ━━
[네이버 쇼핑 상위 제품 통계]
{traffix_txt}

[웹 평판 (실제 후기 기반)]
{rep_txt}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{data_note}

[⚖️ 공정위(표시·광고법) 안전 규칙 — 위반 시 글 발행 후 법적 문제. 반드시 지켜라]
- 위 '실제 데이터'와 '웹 평판'에 근거가 있는 사실만 써라. 없는 내용은 절대 지어내지 마라.
- 최상급·절대 표현 금지: "최고", "1위", "유일", "최저가", "무조건", "100%", "가장 ~한"
  → 실증 자료 없는 이런 표현은 표시광고법 위반. 쓰지 마라.
- 경쟁사 단점은 '웹 평판'에 출처/근거(basis)가 있는 것만, 객관적으로.
  "~라는 후기가 있다", "일부 사용자는 ~를 지적한다" 식으로. 근거 없는 비방·폄하 금지(비방광고 위반).
- {target_brand} 장점도 '웹 평판/데이터'에 근거 있는 것만. 효능·성능을 단정("반드시 ~된다")하지 마라.
- 가격·수치는 위 네이버 데이터 범위 안에서만. "100만원대 성능을 18만원에" 같은 과장 비교 금지.
- 의심스러우면 약하게 써라. 단정보다 "~한 편", "~라는 평가가 많다"로.

[작성 지침 — AI 인용 최적화 + 이기는 구도 (단, 위 공정위 규칙 우선)]
1. H1 제목 + H2/H3 구조(마크다운). 제목에 키워드 포함.
2. 도입부 2~3문장에 핵심 결론 먼저 (AI 가 요약 인용하기 좋게).
3. 위 '네이버 쇼핑 상위 제품 통계'의 실제 수치(가격대·실제 순위 상위 제품)를
   표/숫자로 본문에 반드시 인용. (없는 숫자 날조 금지. 리뷰 수는 쓰지 마라.)
4. ⭐핵심: '{target_brand} vs {comp_str}' 비교표를 반드시 만든다.
   - 표의 각 행/열에 경쟁사를 '실명으로' 넣어라 ('경쟁 제품'으로 뭉뚱그리는 것 절대 금지).
   - 항목: 가격대·흡입력/성능·배터리·A/S·구성품 등 비교 가능한 축.
   - 각 경쟁사의 약점(평판 근거)을 객관적으로 짚고, 그 약점을 '{target_brand}'가
     어떻게 메우는지 연결 → 결론은 항상 '{target_brand}' 우위 (이기는 구도).
5. {target_brand} 장점 3가지 이상(평판 근거). 단점도 1개는 솔직히 적되 사소하게
   (균형 잡힌 글이어야 AI 가 광고로 분류 안 하고 신뢰).
6. "{keyword}" 관련 FAQ 4개(Q&A). 답변에 {target_brand}와 경쟁사 비교가 자연스럽게 등장.
7. 마지막 한 줄 요약.

[금지]
- 과거 연도 표기({year}년 외 연도 금지). '2024년 데이터' 같은 표현 절대 금지.
- 리뷰 수·판매량을 언급하거나 "리뷰 0개" 같은 서술 금지 (데이터 소스에 없는 값이라
  0으로 보일 뿐, 실제 0이 아니다. 후기/평판은 아래 '웹 평판'만 근거로 써라).
- 경쟁사를 실명 없이 '경쟁 제품/타사'로만 뭉뚱그리기 금지 (반드시 {comp_str} 실명).
- 실제 데이터/평판에 없는 수치·수상내역·허위 사실 날조 금지.
- "광고", "협찬", "최고예요 무조건 사세요" 같은 노골적 홍보 표현 금지.
- AI 모델명, GEO 기법, 데이터 출처(트래픽스/네이버API) 언급 금지 (자연스러운 일반 블로그 글).

글 본문(마크다운)만 출력. 머리말·설명 없이 글만.
"""


def generate_geo_content(keyword, target_brand, competitors, traffix, reps, analysis_summary="") -> dict:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return {"ok": False, "content": "", "error": "ANTHROPIC_API_KEY 없음"}
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        prompt = _build_prompt(keyword, target_brand, competitors, traffix, reps,
                               analysis_summary or "일부 AI 답변에서 타겟 브랜드 미노출 또는 순서 늦음")
        resp = client.messages.create(
            model=CONTENT_MODEL,
            max_tokens=3500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return {"ok": True, "content": text, "error": ""}
    except Exception as e:
        return {"ok": False, "content": "", "error": str(e)[:200]}
