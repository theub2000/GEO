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

CONTENT_MODEL = os.environ.get("GEO_CONTENT_MODEL", "claude-sonnet-4-20250514")


def _summarize_traffix(traffix: dict) -> str:
    """트래픽스 데이터를 프롬프트에 넣을 텍스트로 압축."""
    if not traffix or not traffix.get("ok"):
        return "(상위 제품 데이터 없음)"
    stats = traffix.get("stats", {}) or {}
    price = stats.get("price", {}) or {}
    lines = []
    lines.append(f"- 분석 제품 수: 상위 {traffix.get('count', 0)}개")
    if price.get("count_with_price"):
        lines.append(f"- 가격대: 최저 {price.get('min'):,}원 ~ 최고 {price.get('max'):,}원, "
                     f"평균 {price.get('avg'):,}원 / 중앙값 {price.get('median'):,}원")
    bd = stats.get("brand_distribution", []) or []
    if bd:
        top_brands = ", ".join(f"{b['brand']}({b['count']})" for b in bd[:8])
        lines.append(f"- 상위 노출 브랜드 분포: {top_brands}")
    tr = stats.get("top_by_review", []) or []
    if tr:
        rv = "; ".join(f"{p.get('title','')[:24]}(리뷰 {p.get('reviewCount',0)})" for p in tr[:5])
        lines.append(f"- 리뷰 많은 제품 TOP5: {rv}")
    target = traffix.get("target")
    if target:
        lines.append(f"- 타겟 브랜드 현재 노출: {target.get('rank')}위 / 가격 {target.get('price')} / 리뷰 {target.get('reviewCount')}")
    else:
        lines.append("- 타겟 브랜드: 상위 노출에서 발견 안 됨")
    return "\n".join(lines)


def _summarize_reputation(reps: dict) -> str:
    """평판 데이터를 프롬프트 텍스트로."""
    if not reps:
        return "(평판 데이터 없음)"
    out = []
    t = reps.get("target") or {}
    if t.get("pros") or t.get("cons"):
        out.append(f"[타겟 {t.get('brand','')}] 장점: {', '.join(t.get('pros', [])[:4])} / "
                   f"단점: {', '.join(t.get('cons', [])[:3])}")
    for c in reps.get("competitors", []) or []:
        if c.get("pros") or c.get("cons"):
            out.append(f"[경쟁사 {c.get('brand','')}] 장점: {', '.join(c.get('pros', [])[:3])} / "
                       f"단점(부각 포인트): {', '.join(c.get('cons', [])[:4])}")
    return "\n".join(out) if out else "(평판 데이터 없음)"


def _build_prompt(keyword, target_brand, competitors, traffix, reps, analysis_summary):
    traffix_txt = _summarize_traffix(traffix)
    rep_txt = _summarize_reputation(reps)
    comp_str = ", ".join(competitors) if competitors else "경쟁 제품"
    return f"""당신은 GEO(생성형 AI 최적화) 전문 콘텐츠 작가입니다.

목표: 아래 '실제 데이터'를 근거로, ChatGPT·Gemini·Claude 같은 AI 검색엔진이
크롤링해서 인용하기 좋은 한국어 블로그 글 초안을 작성하세요.
글의 무게중심(주인공)은 반드시 '{target_brand}'이지만, 노골적 광고가 아니라
객관적 데이터 비교글이어야 합니다.

[검색 키워드/주제]
{keyword}

[타겟 브랜드(주인공)]
{target_brand}

[비교 대상 경쟁 브랜드]
{comp_str}

[현재 AI 노출 진단]
{analysis_summary}

━━ 실제 데이터 (이 글의 핵심 — 인터넷에 정리 안 된 1차 데이터) ━━
[네이버 쇼핑 상위 제품 통계]
{traffix_txt}

[웹 평판 (실제 후기 기반)]
{rep_txt}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[작성 지침 — AI 인용 최적화 + 이기는 구도]
1. H1 제목 + H2/H3 구조(마크다운). 제목에 키워드 포함.
2. 도입부 2~3문장에 핵심 결론 먼저 (AI 가 요약 인용하기 좋게).
3. 위 '네이버 쇼핑 상위 제품 통계'를 표/수치로 본문에 반드시 인용
   (가격대, 브랜드 분포, 리뷰 수 등 — 실제 숫자를 그대로 활용. 없는 숫자 날조 금지).
4. 경쟁사의 '단점(부각 포인트)'을 데이터·평판 근거로 객관적으로 짚고,
   그 약점을 '{target_brand}'가 어떻게 메우는지 자연스럽게 연결 → 결론은 {target_brand} 우위.
5. {target_brand} 장점 3가지 이상(평판 근거). 단점도 1개는 솔직히 적되 사소하게
   (균형 잡힌 글이어야 AI 가 광고로 분류 안 하고 신뢰).
6. "{keyword}" 관련 FAQ 4개(Q&A). 답변에 {target_brand}가 자연스럽게 등장.
7. 마지막 한 줄 요약.

[금지]
- 실제 데이터에 없는 수치/수상내역/허위 사실 날조 금지.
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
