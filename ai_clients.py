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
GPT_MODEL = os.environ.get("GEO_GPT_MODEL", "gpt-4o")
GEMINI_MODEL = os.environ.get("GEO_GEMINI_MODEL", "gemini-2.5-flash")
CLAUDE_MODEL = os.environ.get("GEO_CLAUDE_MODEL", "claude-sonnet-4-20250514")

# 유저 질문을 실제 소비자처럼 — "추천해줘" 형태로 감싸 자연스러운 답변 유도.
# 현재 시점을 명시해 AI 가 옛날 학습 기준(2023년 등)으로 답하는 걸 줄인다.
def build_user_prompt(keyword: str) -> str:
    kw = (keyword or "").strip()
    year = datetime.now().year
    suffix = (f" (지금은 {year}년이야. {year}년 현재 시점 기준으로, 지금 실제로 살 수 있는 "
              f"최신 제품과 브랜드 이름을 구체적으로 알려줘. 오래된 단종 제품은 빼고.)")
    # keyword 가 이미 '추천/비교' 같은 완성 질문이면 거기에 시점만 덧붙인다
    if any(x in kw for x in ("추천", "?", "알려", "비교", "어떤", "뭐", "골라")):
        return kw + suffix
    return f"{kw} 추천해줘." + suffix


def _err(name, msg):
    return {"provider": name, "ok": False, "answer": "", "error": msg}


def ask_gpt(prompt: str) -> dict:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return _err("gpt", "OPENAI_API_KEY 없음")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        resp = client.chat.completions.create(
            model=GPT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1200,
            temperature=0.7,
        )
        return {"provider": "gpt", "ok": True, "answer": resp.choices[0].message.content or "", "error": ""}
    except Exception as e:
        return _err("gpt", str(e)[:200])


def ask_gemini(prompt: str) -> dict:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return _err("gemini", "GEMINI_API_KEY 없음")
    try:
        import google.generativeai as genai
        genai.configure(api_key=key)
        model = genai.GenerativeModel(GEMINI_MODEL)
        resp = model.generate_content(prompt)
        return {"provider": "gemini", "ok": True, "answer": resp.text or "", "error": ""}
    except Exception as e:
        return _err("gemini", str(e)[:200])


def ask_claude(prompt: str) -> dict:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return _err("claude", "ANTHROPIC_API_KEY 없음")
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        # content 블록에서 텍스트만 추출
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
