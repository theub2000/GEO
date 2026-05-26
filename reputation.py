"""
브랜드 평판 파싱 — AI(Claude)의 웹검색 기능으로 브랜드 실제 평판(긍/부정)을 수집.

리뷰 본문을 직접 크롤링하면 무겁고 차단 위험이 크므로, AI 웹검색에 위임한다.
(트래픽스 크롤링 부담 0, 차단 위험 0)

환경변수: ANTHROPIC_API_KEY
"""

import os
import json

REPUTATION_MODEL = os.environ.get("GEO_REPUTATION_MODEL", "claude-sonnet-4-20250514")


def fetch_reputation(brand: str, keyword: str) -> dict:
    """브랜드 1개의 평판을 웹검색으로 수집 → {pros:[...], cons:[...]}.

    웹검색이 안 되는 환경/키 없음이면 ok=False 로 graceful 반환.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return {"ok": False, "brand": brand, "pros": [], "cons": [], "error": "ANTHROPIC_API_KEY 없음"}
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        prompt = (
            f"'{brand}' {keyword} 제품에 대한 실제 사용자 평판을 웹에서 찾아 정리해줘.\n"
            f"실제 후기/기사에서 자주 나오는 장점과 단점을 각각 핵심만 뽑아.\n"
            f"반드시 아래 JSON 형식으로만 답해 (설명/머리말 없이):\n"
            f'{{"pros": ["장점1", "장점2", "장점3"], "cons": ["단점1", "단점2"]}}'
        )
        resp = client.messages.create(
            model=REPUTATION_MODEL,
            max_tokens=1000,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
            messages=[{"role": "user", "content": prompt}],
        )
        # 텍스트 블록만 모아서 JSON 추출
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        parsed = _extract_json(text)
        if parsed is None:
            return {"ok": True, "brand": brand, "pros": [], "cons": [], "raw": text[:500],
                    "error": "JSON 파싱 실패 (raw 참고)"}
        return {"ok": True, "brand": brand,
                "pros": parsed.get("pros", []) or [], "cons": parsed.get("cons", []) or [], "error": ""}
    except Exception as e:
        return {"ok": False, "brand": brand, "pros": [], "cons": [], "error": str(e)[:160]}


def _extract_json(text: str):
    """텍스트에서 첫 JSON 오브젝트를 뽑아 파싱."""
    if not text:
        return None
    t = text.replace("```json", "").replace("```", "").strip()
    start = t.find("{")
    end = t.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(t[start:end + 1])
    except Exception:
        return None


def fetch_all_reputations(target_brand: str, competitors: list, keyword: str) -> dict:
    """타겟 + 경쟁사 평판을 한 번에 (순차 — 웹검색은 호출당 무거워 병렬 회피)."""
    out = {"target": fetch_reputation(target_brand, keyword), "competitors": []}
    for c in (competitors or [])[:4]:  # 경쟁사는 최대 4개까지만 (비용/시간)
        out["competitors"].append(fetch_reputation(c, keyword))
    return out
