"""
트래픽스 데이터 클라이언트 — 별도 배포된 트래픽스의 GEO 엔드포인트를 호출.

환경변수:
  TRAFFIX_BASE   — 트래픽스 주소 (예: https://traffix.kr)
  GEO_API_TOKEN  — 트래픽스 GEO 엔드포인트 인증 토큰 (트래픽스쪽과 동일 값)
"""

import os
import requests


TRAFFIX_BASE = os.environ.get("TRAFFIX_BASE", "").rstrip("/")
GEO_API_TOKEN = os.environ.get("GEO_API_TOKEN", "")


def fetch_products(keyword: str, target_brand: str = "", display: int = 60) -> dict:
    """키워드 상위 제품 + 통계 데이터를 트래픽스에서 받아온다.

    실패 시 {'ok': False, 'error': ...} 반환 (앱이 죽지 않게).
    """
    if not TRAFFIX_BASE:
        return {"ok": False, "error": "TRAFFIX_BASE 미설정"}
    try:
        r = requests.get(
            f"{TRAFFIX_BASE}/api/geo/products",
            params={"keyword": keyword, "display": display, "target_brand": target_brand},
            headers={"x-geo-token": GEO_API_TOKEN},
            timeout=20,
        )
        if r.status_code == 401:
            return {"ok": False, "error": "트래픽스 인증 실패 (GEO_API_TOKEN 불일치)"}
        r.raise_for_status()
        data = r.json()
        data["ok"] = True
        return data
    except Exception as e:
        return {"ok": False, "error": f"트래픽스 호출 실패: {str(e)[:160]}"}
