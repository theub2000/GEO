"""
3개 AI 호출 어댑터 — GPT / Gemini / Claude 에 같은 질문을 던지고 답변 텍스트를 받는다.

API 키는 환경변수로 주입 (코드에 하드코딩 금지):
  OPENAI_API_KEY     — GPT
  GEMINI_API_KEY     — Gemini
  ANTHROPIC_API_KEY  — Claude

모델은 환경변수로 조정 가능 (기본값은 합리적인 최신 일반 모델).
키가 없는 AI는 건너뛰고 결과에 error 를 담아 반환 (3개 중 일부만 있어도 동작).
"""

import os
import asyncio
from datetime import datetime


# 모델명 — 환경변수로 덮어쓸 수 있음
GPT_MODEL = os.environ.get("GEO_GPT_MODEL", "gpt-4o-search-preview")
GEMINI_MODEL = os.environ.get("GEO_GEMINI_MODEL", "gemini-2.5-flash")
CLAUDE_MODEL = os.environ.get("GEO_CLAUDE_MODEL", "claude-sonnet-4-20250514")

# 유저 질문을 실제 소비자처럼 — "추천해줘" 형태로 감싸 자연스러운 답변 유도.
# 주의: 측정 질문에 "지금은 N년" 같은 시점을 강요하면 AI 가 학습 컷오프를 핑계로
#   "그 시점 정보 없다"고 발뺌해서 측정이 망가진다. 그래서 시점은 넣지 않고
#   유저가 실제로 묻듯 자연스럽게 둔다. (목적은 '타겟 브랜드 노출 여부' 측정이지
#    AI 가 최신 정보를 아는지가 아니다.)
def build_user_prompt(keyword: str) -> str:
    kw = (keyword or "").strip()
    # "검색하겠습니다~" 같은 과정 설명을 빼고 추천 결과만 자연스럽게 말하도록 유도
    tail = " 검색하겠다는 말이나 과정 설명 없이, 바로 추천 제품·브랜드와 이유만 자연스럽게 알려줘."
    # keyword 가 이미 '추천/비교' 같은 완성 질문이면 그대로, 아니면 추천 요청으로 감싼다
    if any(x in kw for x in ("추천", "?", "알려", "비교", "어떤", "뭐", "골라")):
        return kw + tail
    return f"{kw} 추천해줘. 구체적인 제품/브랜드 이름과 이유를 알려줘." + tail


def _err(name, msg):
    return {"provider": name, "ok": False, "answer": "", "error": msg}


def ask_gpt(prompt: str) -> dict:
    """GPT — 웹검색 켜고 측정 (gpt-4o-search-preview + web_search_options).
    실제 소비자가 ChatGPT 앱에서 받는 것과 같은 '검색 기반' 답을 받기 위함.
    """
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return _err("gpt", "OPENAI_API_KEY 없음")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        # search-preview 모델은 web_search_options 필수, temperature 미지원 → 넣지 않음
        resp = client.chat.completions.create(
            model=GPT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            web_search_options={},
            max_tokens=1200,
        )
        return {"provider": "gpt", "ok": True, "answer": resp.choices[0].message.content or "", "error": ""}
    except Exception as e:
        # search 모델/옵션 미지원 환경이면 일반 모델로 폴백 (측정은 되게)
        try:
            from openai import OpenAI
            client = OpenAI(api_key=key)
            resp = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1200,
            )
            return {"provider": "gpt", "ok": True, "answer": resp.choices[0].message.content or "",
                    "error": f"(웹검색 폴백: {str(e)[:80]})"}
        except Exception as e2:
            return _err("gpt", str(e2)[:200])


def ask_gemini(prompt: str) -> dict:
    """Gemini — Google Search grounding 켜고 측정 (실시간 웹 기반 답)."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return _err("gemini", "GEMINI_API_KEY 없음")
    try:
        import google.generativeai as genai
        genai.configure(api_key=key)
        # 2.x 모델 = google_search tool, 안 되면 1.5식 google_search_retrieval, 그래도 안 되면 일반
        for tools in ([{"google_search": {}}], "google_search_retrieval", None):
            try:
                model = (genai.GenerativeModel(GEMINI_MODEL, tools=tools) if tools
                         else genai.GenerativeModel(GEMINI_MODEL))
                resp = model.generate_content(prompt)
                note = "" if tools else "(grounding 미적용 폴백)"
                return {"provider": "gemini", "ok": True, "answer": resp.text or "", "error": note}
            except Exception:
                continue
        return _err("gemini", "Gemini 호출 실패 (grounding/일반 모두)")
    except Exception as e:
        return _err("gemini", str(e)[:200])


def ask_claude(prompt: str) -> dict:
    """Claude — web_search tool 켜고 측정 (실시간 웹 기반 답)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return _err("claude", "ANTHROPIC_API_KEY 없음")
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1500,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return {"provider": "claude", "ok": True, "answer": text, "error": ""}
    except Exception as e:
        return _err("claude", str(e)[:200])


async def ask_all(keyword: str) -> dict:
    """3개 AI 를 병렬로 호출 (블로킹 SDK 라 스레드로 분산)."""
    prompt = build_user_prompt(keyword)
    loop = asyncio.get_event_loop()
    gpt_t = loop.run_in_executor(None, ask_gpt, prompt)
    gem_t = loop.run_in_executor(None, ask_gemini, prompt)
    cla_t = loop.run_in_executor(None, ask_claude, prompt)
    gpt, gem, cla = await asyncio.gather(gpt_t, gem_t, cla_t)
    return {"prompt": prompt, "gpt": gpt, "gemini": gem, "claude": cla}
