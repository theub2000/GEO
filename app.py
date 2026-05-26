"""
GEO 테스트 앱 — 트래픽스 리소스 활용 테스트용 (별도 배포, 1명 테스트).

흐름:
  1. 유저가 키워드 + 타겟 브랜드(+별칭) + 경쟁사 입력
  2. GPT / Gemini / Claude 3개에 같은 질문 → 각 답변에서 타겟 노출 측정
  3. 미노출/순서 늦음 → AI 인용 최적화 양식의 글 생성
  4. 유저가 복붙해서 블로그/워드프레스에 발행

실행: uvicorn app:app --host 0.0.0.0 --port 8200
환경변수: OPENAI_API_KEY / GEMINI_API_KEY / ANTHROPIC_API_KEY
"""

import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse

from ai_clients import ask_all
from geo_brand_analyzer import analyze_answer, summarize, verdict
from geo_content import generate_geo_content
from traffix_client import fetch_products
from reputation import fetch_all_reputations

app = FastAPI(title="GEO 노출 측정 테스트")


def _result_to_dict(provider, ai_res, keyword, target_brand, aliases, competitors):
    """AI 1건 응답 → 판정 결과 dict."""
    if not ai_res.get("ok"):
        return {"provider": provider, "ok": False, "error": ai_res.get("error", "호출 실패"),
                "mentioned": None, "answer": ""}
    r = analyze_answer(provider, keyword, ai_res["answer"], target_brand, aliases, competitors)
    return {
        "provider": provider,
        "ok": True,
        "error": "",
        "answer": ai_res["answer"],
        "mentioned": r.target.mentioned,
        "mention_count": r.target.mention_count,
        "first_order": r.target.first_order,
        "sentiment": r.target.sentiment,
        "share_of_voice": r.share_of_voice,
        "summary": summarize(r),
        "verdict": verdict(r),
        "competitors": [
            {"brand": c.brand, "mentioned": c.mentioned, "order": c.first_order, "sentiment": c.sentiment}
            for c in r.competitors
        ],
    }


@app.post("/api/analyze")
async def api_analyze(request: Request):
    body = await request.json()
    keyword = (body.get("keyword") or "").strip()
    target_brand = (body.get("target_brand") or "").strip()
    aliases = [a.strip() for a in (body.get("aliases") or "").split(",") if a.strip()]
    competitors = [c.strip() for c in (body.get("competitors") or "").split(",") if c.strip()]

    if not keyword or not target_brand:
        return JSONResponse({"error": "키워드와 타겟 브랜드는 필수"}, status_code=400)

    ai = await ask_all(keyword)
    results = {}
    for provider in ("gpt", "gemini", "claude"):
        results[provider] = _result_to_dict(provider, ai[provider], keyword,
                                             target_brand, aliases, competitors)

    # 종합 — 3개 중 미노출/늦음이 하나라도 있으면 콘텐츠 생성 권장
    need = any(r.get("ok") and r.get("verdict", {}).get("need_content") for r in results.values())
    not_mentioned = [p for p, r in results.items() if r.get("ok") and r.get("mentioned") is False]

    return JSONResponse({
        "keyword": keyword,
        "target_brand": target_brand,
        "prompt": ai["prompt"],
        "results": results,
        "need_content": need,
        "not_mentioned_in": not_mentioned,
    })


def _extract_top_competitors(traffix, target_brand, limit=6):
    """실제 순위 상위 제품(top_ranked)에서 타겟 제외 경쟁 브랜드를 순위 순서대로 추출.
    brand 필드가 비면 제목 앞부분에서 브랜드를 추정한다.
    """
    if not traffix or not traffix.get("ok"):
        return []
    top = (traffix.get("stats", {}) or {}).get("top_ranked", []) or []
    tb = (target_brand or "").strip().lower().replace(" ", "")
    out = []
    seen = set()
    for p in top:
        b = (p.get("brand") or "").strip()
        if not b:
            title = (p.get("title") or "").strip()
            b = title.split()[0] if title else ""
        if not b:
            continue
        bl = b.lower().replace(" ", "")
        if tb and tb in bl:           # 타겟 브랜드는 제외
            continue
        if bl in seen:
            continue
        seen.add(bl)
        out.append(b)
        if len(out) >= limit:
            break
    return out


@app.post("/api/generate")
async def api_generate(request: Request):
    body = await request.json()
    keyword = (body.get("keyword") or "").strip()
    target_brand = (body.get("target_brand") or "").strip()
    competitors = [c.strip() for c in (body.get("competitors") or "").split(",") if c.strip()]
    analysis_summary = (body.get("analysis_summary") or "").strip() or "AI 답변에 타겟 브랜드 노출이 약함"

    if not keyword or not target_brand:
        return JSONResponse({"error": "키워드와 타겟 브랜드는 필수"}, status_code=400)

    # 1단계: 트래픽스에서 키워드 '실제 순위' 상위 제품 (네이버 쇼핑 노출 순위)
    traffix = fetch_products(keyword, target_brand=target_brand, display=80)

    # 1.5단계: 순위 상위권에서 경쟁 브랜드 자동 추출 → 유저 입력과 합쳐 비교 대상 확정
    auto_comp = _extract_top_competitors(traffix, target_brand, limit=6)
    final_comp = list(competitors)
    seen = {c.lower().replace(" ", "") for c in final_comp}
    for c in auto_comp:
        cl = c.lower().replace(" ", "")
        if cl not in seen:
            seen.add(cl)
            final_comp.append(c)
    final_comp = final_comp[:7]  # 디베아 vs 상위권 최대 7개

    # 2단계: 타겟 + (자동 추출 포함) 경쟁사 각각 웹검색 평판(강점/약점) 수집
    reps = fetch_all_reputations(target_brand, final_comp, keyword)
    # 3단계: 실순위 + 평판 → '디베아 vs 상위권 강점/약점 비교분석' 글
    out = generate_geo_content(keyword, target_brand, final_comp, traffix, reps, analysis_summary)
    if not out["ok"]:
        return JSONResponse({"error": out["error"]}, status_code=500)
    return JSONResponse({
        "content": out["content"],
        "data_used": {
            "traffix_ok": traffix.get("ok", False),
            "traffix_error": traffix.get("error", ""),
            "product_count": traffix.get("count", 0),
            "competitors_used": final_comp,
            "reputation_ok": reps.get("target", {}).get("ok", False),
            "reputation_searched": reps.get("target", {}).get("searched", False),
        },
    })


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_PAGE


@app.get("/health")
async def health():
    return {
        "ok": True,
        "keys": {
            "gpt": bool(os.environ.get("OPENAI_API_KEY")),
            "gemini": bool(os.environ.get("GEMINI_API_KEY")),
            "claude": bool(os.environ.get("ANTHROPIC_API_KEY")),
        },
        "traffix": {
            "base_set": bool(os.environ.get("TRAFFIX_BASE")),
            "token_set": bool(os.environ.get("GEO_API_TOKEN")),
        },
    }


HTML_PAGE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GEO 노출 측정 테스트</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
         max-width: 860px; margin: 0 auto; padding: 24px; color: #1a1a1a; background: #fafafa; }
  h1 { font-size: 22px; margin-bottom: 4px; }
  .sub { color: #777; font-size: 13px; margin-bottom: 24px; }
  .card { background: #fff; border: 1px solid #e5e5e5; border-radius: 12px; padding: 18px; margin-bottom: 16px; }
  label { display: block; font-size: 13px; font-weight: 600; margin: 10px 0 4px; }
  input { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 8px; font-size: 14px; }
  .hint { color: #999; font-size: 12px; font-weight: 400; }
  button { background: #1a1a1a; color: #fff; border: 0; border-radius: 8px; padding: 12px 20px;
           font-size: 14px; cursor: pointer; margin-top: 14px; }
  button:disabled { background: #bbb; cursor: not-allowed; }
  button.sec { background: #fff; color: #1a1a1a; border: 1px solid #ccc; }
  .grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }
  @media (max-width: 700px) { .grid { grid-template-columns: 1fr; } }
  .ai { border-radius: 10px; padding: 14px; border: 1px solid #e5e5e5; }
  .ai h3 { margin: 0 0 8px; font-size: 15px; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: 600; }
  .ok { background: #e6f6ec; color: #1a7f3c; }
  .no { background: #fdecec; color: #c0392b; }
  .meta { font-size: 13px; color: #555; margin: 6px 0; line-height: 1.6; }
  .answer { font-size: 12px; color: #777; white-space: pre-wrap; max-height: 140px; overflow-y: auto;
            border-top: 1px dashed #eee; margin-top: 8px; padding-top: 8px; }
  pre { white-space: pre-wrap; word-break: break-word; background: #f6f6f6; padding: 16px;
        border-radius: 8px; font-size: 13px; line-height: 1.7; }
  .err { color: #c0392b; font-size: 13px; }
  .spin { color: #888; font-size: 13px; }
</style>
</head>
<body>
<h1>GEO 노출 측정 테스트</h1>
<div class="sub">내 브랜드가 AI(GPT·Gemini·Claude) 추천 답변에 얼마나 나오는지 측정하고, 안 나오면 노출용 글을 만들어줍니다.</div>

<div class="card">
  <label>검색 키워드 / 질문 <span class="hint">예: 무선청소기 추천</span></label>
  <input id="keyword" placeholder="무선청소기 추천">
  <label>타겟 브랜드 <span class="hint">노출시키고 싶은 내 브랜드/제품/스토어</span></label>
  <input id="target_brand" placeholder="노출시키려는 내 브랜드">
  <label>별칭 <span class="hint">쉼표로 구분 (영문/다른표기). 예: Dibea, 디베아청소기</span></label>
  <input id="aliases" placeholder="영문명, 다른 표기">
  <label>경쟁사 <span class="hint">쉼표로 구분. 예: 다이슨, 샤오미, LG</span></label>
  <input id="competitors" placeholder="다이슨, 샤오미, LG">
  <button id="analyzeBtn" onclick="analyze()">3개 AI로 측정하기</button>
  <div id="status" class="spin"></div>
</div>

<div id="results"></div>

<div id="contentCard" class="card" style="display:none;">
  <h3 style="margin-top:0;">📝 AI 노출용 글 (그대로 복붙해서 블로그/워드프레스에 발행)</h3>
  <button id="genBtn" class="sec" onclick="generate()">노출용 글 생성하기</button>
  <div id="genStatus" class="spin"></div>
  <pre id="content" style="display:none;"></pre>
  <button id="copyBtn" style="display:none;" onclick="copyContent()">📋 글 복사</button>
</div>

<script>
let lastInput = {};

async function analyze() {
  const keyword = document.getElementById('keyword').value.trim();
  const target_brand = document.getElementById('target_brand').value.trim();
  const aliases = document.getElementById('aliases').value.trim();
  const competitors = document.getElementById('competitors').value.trim();
  if (!keyword || !target_brand) { alert('키워드와 타겟 브랜드는 필수입니다.'); return; }

  lastInput = { keyword, target_brand, aliases, competitors };
  const btn = document.getElementById('analyzeBtn');
  btn.disabled = true;
  document.getElementById('status').textContent = '3개 AI에게 물어보는 중... (10~30초)';
  document.getElementById('results').innerHTML = '';
  document.getElementById('contentCard').style.display = 'none';

  try {
    const res = await fetch('/api/analyze', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(lastInput)
    });
    const data = await res.json();
    if (data.error) { document.getElementById('status').innerHTML = '<span class="err">' + data.error + '</span>'; btn.disabled = false; return; }
    renderResults(data);
    document.getElementById('status').textContent = '';
  } catch (e) {
    document.getElementById('status').innerHTML = '<span class="err">오류: ' + e + '</span>';
  }
  btn.disabled = false;
}

function renderResults(data) {
  const names = { gpt: 'ChatGPT', gemini: 'Gemini', claude: 'Claude' };
  let html = '<div class="card"><h3 style="margin-top:0;">측정 결과 — "' + data.keyword + '" / 타겟: ' + data.target_brand + '</h3><div class="grid">';
  for (const p of ['gpt', 'gemini', 'claude']) {
    const r = data.results[p];
    html += '<div class="ai">';
    html += '<h3>' + names[p] + '</h3>';
    if (!r.ok) {
      html += '<div class="err">' + (r.error || '호출 실패') + '</div>';
    } else if (!r.mentioned) {
      html += '<span class="badge no">미노출</span>';
      html += '<div class="meta">답변에 안 나옴</div>';
    } else {
      html += '<span class="badge ok">' + r.first_order + '번째 노출</span>';
      html += '<div class="meta">언급 ' + r.mention_count + '회 · 감성 ' + r.sentiment + '<br>노출비중(SoV) ' + Math.round(r.share_of_voice * 100) + '%</div>';
    }
    if (r.answer) html += '<div class="answer">' + escapeHtml(r.answer) + '</div>';
    html += '</div>';
  }
  html += '</div></div>';
  document.getElementById('results').innerHTML = html;

  if (data.need_content) {
    document.getElementById('contentCard').style.display = 'block';
  }
}

async function generate() {
  const btn = document.getElementById('genBtn');
  btn.disabled = true;
  document.getElementById('genStatus').textContent = 'AI 인용 최적화 글 작성 중... (10~30초)';
  document.getElementById('content').style.display = 'none';
  document.getElementById('copyBtn').style.display = 'none';
  try {
    const res = await fetch('/api/generate', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ ...lastInput, analysis_summary: '일부 AI 답변에서 타겟 브랜드 미노출 또는 순서 늦음' })
    });
    const data = await res.json();
    if (data.error) { document.getElementById('genStatus').innerHTML = '<span class="err">' + data.error + '</span>'; btn.disabled = false; return; }
    document.getElementById('content').textContent = data.content;
    document.getElementById('content').style.display = 'block';
    document.getElementById('copyBtn').style.display = 'inline-block';
    document.getElementById('genStatus').textContent = '';
  } catch (e) {
    document.getElementById('genStatus').innerHTML = '<span class="err">오류: ' + e + '</span>';
  }
  btn.disabled = false;
}

function copyContent() {
  const t = document.getElementById('content').textContent;
  const b = document.getElementById('copyBtn');
  const done = () => { b.textContent = '✅ 복사됨'; setTimeout(() => b.textContent = '📋 글 복사', 1500); };
  // https(보안 컨텍스트)에서만 navigator.clipboard 동작 → http(sslip.io)면 fallback
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(t).then(done).catch(() => fallbackCopy(t, done));
  } else {
    fallbackCopy(t, done);
  }
}

function fallbackCopy(text, done) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.left = '-9999px';
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  try { document.execCommand('copy'); done(); }
  catch (e) { alert('자동 복사가 안 됩니다. 글을 직접 드래그해서 복사하세요.'); }
  document.body.removeChild(ta);
}

function escapeHtml(s) {
  return (s || '').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
}
</script>
</body>
</html>"""
