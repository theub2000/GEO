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
            f"'{brand}' {keyword}에 대한 실제 사용자 평판을 웹에서 검색해서 정리해줘.\n"
            f"반드시 web_search 도구로 실제 검색을 먼저 해. 검색하지 않고 추측으로 답하지 마.\n\n"
            f"규칙:\n"
            f"- 검색 결과(실제 후기/기사/블로그)에서 '실제로 확인된' 장점/단점만 적어.\n"
            f"- 검색으로 확인 안 되는 내용은 절대 지어내지 마. 없으면 빈 배열로 둬.\n"
            f"- 각 항목에 근거(어디서 나온 의견인지, 출처 성격)를 'basis'에 짧게 적어.\n"
            f"- 과장·단정 표현 금지. '~라는 후기가 있다' 수준의 객관 서술로.\n\n"
            f"아래 JSON 형식으로만 답해 (설명/머리말 없이):\n"
            f'{{"pros": [{{"point": "장점", "basis": "근거/출처성격"}}], '
            f'"cons": [{{"point": "단점", "basis": "근거/출처성격"}}]}}'
        )
        resp = client.messages.create(
            model=REPUTATION_MODEL,
            max_tokens=1500,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
            messages=[{"role": "user", "content": prompt}],
        )
        # 실제 web_search 가 실행됐는지 확인 (server_tool_use / web_search_tool_result 블록)
        searched = any(getattr(b, "type", "") in ("server_tool_use", "web_search_tool_result")
                       for b in resp.content)
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        parsed = _extract_json(text)
        if parsed is None:
            return {"ok": True, "brand": brand, "pros": [], "cons": [], "searched": searched,
                    "raw": text[:500], "error": "JSON 파싱 실패 (raw 참고)"}
        return {"ok": True, "brand": brand,
                "pros": _norm(parsed.get("pros")), "cons": _norm(parsed.get("cons")),
                "searched": searched, "error": ""}
    except Exception as e:
        return {"ok": False, "brand": brand, "pros": [], "cons": [], "error": str(e)[:160]}


def _norm(items):
    """[{point,basis}] 또는 ['문자열'] 둘 다 [{point,basis}] 로 정규화."""
    out = []
    for it in (items or []):
        if isinstance(it, dict):
            p = (it.get("point") or "").strip()
            if p:
                out.append({"point": p, "basis": (it.get("basis") or "").strip()})
        elif isinstance(it, str) and it.strip():
            out.append({"point": it.strip(), "basis": ""})
    return out


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
