"""
GEO 브랜드 판정 로직 — AI 답변 텍스트에서 타겟 브랜드 노출을 측정.

키 없이 순수 텍스트 분석만 한다 (API 호출은 ai_clients.py 가 담당).
입력: AI 답변 raw text + 타겟 브랜드(+별칭) + 경쟁사 목록
출력: 탐지 여부 / 언급 횟수 / 등장 순서 / 감성 / 노출비중(SoV)
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional


# ── 감성 신호 사전 (한국어 이커머스 맥락) ───────────────────────
POSITIVE_WORDS = [
    "추천", "가성비", "최고", "우수", "뛰어", "좋", "강력", "만족", "인기",
    "합리적", "훌륭", "탁월", "강점", "장점", "1순위", "best", "가장", "압도적",
]
NEGATIVE_WORDS = [
    "단점", "아쉬", "비싸", "비쌈", "약점", "별로", "부족", "불만", "최악",
    "떨어", "구식", "느리", "약하", "주의", "한계",
]


def _normalize(text: str) -> str:
    """비교용 정규화 — 소문자 + 공백/특수문자 제거."""
    return re.sub(r"[\s\-_/().]+", "", (text or "").lower())


@dataclass
class BrandMention:
    brand: str
    aliases: List[str] = field(default_factory=list)
    mentioned: bool = False
    mention_count: int = 0
    first_order: int = 0      # 답변 안에서 몇 번째로 등장한 브랜드인가 (1=가장 먼저)
    first_pos: int = -1       # 첫 등장 문자 위치 (순서 계산용)
    sentiment: str = "none"   # positive / negative / mixed / neutral / none
    matched_alias: str = ""   # 실제로 매칭된 표기


@dataclass
class GeoResult:
    keyword: str
    ai_provider: str
    raw_answer: str
    target: BrandMention
    competitors: List[BrandMention] = field(default_factory=list)
    share_of_voice: float = 0.0   # 타겟 언급횟수 / 전체 브랜드 언급횟수


def _count_and_locate(text: str, brand: str, aliases: List[str]):
    """본문에서 브랜드(+별칭) 등장 횟수, 첫 위치, 매칭된 표기를 찾는다.

    공백/특수문자 무시 매칭을 위해 정규화 본문에서 찾되,
    첫 위치는 원본 기준 근사값(정규화 인덱스)으로 잡는다.
    """
    norm_text = _normalize(text)
    candidates = [brand] + list(aliases or [])
    total = 0
    first_pos = -1
    matched = ""
    for cand in candidates:
        nc = _normalize(cand)
        if not nc:
            continue
        # 등장 횟수
        cnt = norm_text.count(nc)
        if cnt > 0:
            total += cnt
            pos = norm_text.find(nc)
            if first_pos == -1 or pos < first_pos:
                first_pos = pos
                matched = cand
    return total, first_pos, matched


def _sentiment_for(text: str, brand: str, aliases: List[str]) -> str:
    """브랜드가 포함된 '문장'들만 모아 감성을 본다.

    옛 버그: 고정 글자수 윈도우로 보면 옆 브랜드의 단점 평가가 섞여 mixed 오판.
    개선: 문장 단위로 쪼개 브랜드가 들어간 문장만 평가한다.
    """
    candidates = [_normalize(c) for c in ([brand] + list(aliases or [])) if c]
    sentences = re.split(r"[.!?。\n]", text or "")
    pos = neg = 0
    for s in sentences:
        ns = _normalize(s)
        if not any(c in ns for c in candidates):
            continue
        if any(_normalize(w) in ns for w in POSITIVE_WORDS):
            pos += 1
        if any(_normalize(w) in ns for w in NEGATIVE_WORDS):
            neg += 1
    if pos and neg:
        return "mixed"
    if pos:
        return "positive"
    if neg:
        return "negative"
    return "neutral"


def _to_brand(entry) -> BrandMention:
    """문자열 또는 {'name':..., 'aliases':[...]} 형태를 BrandMention 으로."""
    if isinstance(entry, dict):
        return BrandMention(brand=entry.get("name", ""), aliases=entry.get("aliases", []) or [])
    return BrandMention(brand=str(entry), aliases=[])


def analyze_answer(ai_provider: str, keyword: str, raw_answer: str,
                   target_brand: str, target_aliases: Optional[List[str]] = None,
                   competitors: Optional[List] = None) -> GeoResult:
    """AI 답변 1건을 분석해 GeoResult 반환."""
    target = BrandMention(brand=target_brand, aliases=target_aliases or [])
    comp_brands = [_to_brand(c) for c in (competitors or [])]

    # 타겟 측정
    t_cnt, t_pos, t_alias = _count_and_locate(raw_answer, target.brand, target.aliases)
    target.mention_count = t_cnt
    target.mentioned = t_cnt > 0
    target.first_pos = t_pos
    target.matched_alias = t_alias
    target.sentiment = _sentiment_for(raw_answer, target.brand, target.aliases) if t_cnt else "none"

    # 경쟁사 측정
    for c in comp_brands:
        c_cnt, c_pos, c_alias = _count_and_locate(raw_answer, c.brand, c.aliases)
        c.mention_count = c_cnt
        c.mentioned = c_cnt > 0
        c.first_pos = c_pos
        c.matched_alias = c_alias
        c.sentiment = _sentiment_for(raw_answer, c.brand, c.aliases) if c_cnt else "none"

    # 등장 순서 계산 — 언급된 브랜드(타겟+경쟁사)를 첫 위치로 정렬
    appeared = [b for b in ([target] + comp_brands) if b.mentioned]
    appeared.sort(key=lambda b: b.first_pos)
    for order, b in enumerate(appeared, start=1):
        b.first_order = order

    # 노출비중(SoV) = 타겟 언급횟수 / 전체 브랜드 언급횟수
    total_mentions = sum(b.mention_count for b in ([target] + comp_brands))
    sov = round(target.mention_count / total_mentions, 3) if total_mentions else 0.0

    return GeoResult(
        keyword=keyword,
        ai_provider=ai_provider,
        raw_answer=raw_answer,
        target=target,
        competitors=comp_brands,
        share_of_voice=sov,
    )


def summarize(result: GeoResult) -> str:
    """사람이 읽을 한 줄 요약."""
    t = result.target
    if not t.mentioned:
        return f"[{result.ai_provider}] ❌ '{t.brand}' 미노출 — {result.keyword} 답변에 안 나옴"
    return (f"[{result.ai_provider}] ✅ '{t.brand}' {t.first_order}번째 언급 "
            f"(횟수 {t.mention_count}, 감성 {t.sentiment}, SoV {int(result.share_of_voice*100)}%)")


def verdict(result: GeoResult, late_threshold: int = 3) -> dict:
    """처방 판정 — 노출 안 됐거나 순서가 늦으면 콘텐츠 생성 필요."""
    t = result.target
    if not t.mentioned:
        return {"need_content": True, "reason": "미노출", "severity": "high"}
    if t.first_order > late_threshold:
        return {"need_content": True, "reason": f"{t.first_order}번째로 늦음", "severity": "mid"}
    if t.sentiment in ("negative", "mixed"):
        return {"need_content": True, "reason": f"감성 {t.sentiment}", "severity": "mid"}
    return {"need_content": False, "reason": "양호", "severity": "low"}


if __name__ == "__main__":
    sample = """
    가성비 무선청소기를 찾으신다면 몇 가지를 추천드려요.
    먼저 디베아는 흡입력이 우수하고 가격이 합리적이라 가성비 1순위로 많이 꼽힙니다.
    다이슨은 성능은 최고지만 가격이 비싸다는 단점이 있습니다.
    샤오미도 무난하지만 A/S가 아쉽다는 평이 있어요.
    """
    r = analyze_answer("chatgpt", "가성비 무선청소기 추천", sample,
                       target_brand="디베아", target_aliases=["Dibea"],
                       competitors=["다이슨", {"name": "샤오미", "aliases": ["Xiaomi"]}, "LG"])
    print(summarize(r))
    print("verdict:", verdict(r))
    for c in r.competitors:
        print(f"  경쟁사 {c.brand}: 노출={c.mentioned} 순서={c.first_order} 감성={c.sentiment}")
