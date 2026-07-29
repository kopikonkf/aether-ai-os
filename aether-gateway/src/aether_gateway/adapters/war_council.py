import requests
import time
import logging
from typing import Dict, Any, Optional, List
from aether.utils.time import utc_now

log = logging.getLogger(__name__)

WAR_COUNCIL_API = "http://127.0.0.1:9223"

def check_health() -> bool:
    try:
        r = requests.get(f"{WAR_COUNCIL_API}/health", timeout=3)
        return r.status_code == 200
    except requests.exceptions.RequestException:
        return False

def consult_war_council(prompt: str, mode: str = "audit", platforms: Optional[List[str]] = None, timeout_seconds: int = 120) -> Dict[str, Any]:
    if not check_health():
        log.error("War Council App is not reachable on localhost:9223")
        return {"error": "War Council offline"}

    try:
        payload = {"prompt": prompt, "mode": mode}
        if platforms:
            payload["platforms"] = platforms

        send_resp = requests.post(f"{WAR_COUNCIL_API}/send", json=payload, timeout=5)
        if send_resp.status_code != 200:
            return {"error": f"Failed to send prompt: {send_resp.text}"}

        start_time = time.time()
        while (time.time() - start_time) < timeout_seconds:
            time.sleep(5)
            try:
                resp = requests.get(f"{WAR_COUNCIL_API}/responses", timeout=3)
                if resp.status_code == 200:
                    data = resp.json()
                    if "synthesis" in data and data["synthesis"]:
                        return {
                            "responses": data.get("responses", {}),
                            "synthesis": data.get("synthesis"),
                            "verdict": data.get("verdict"),
                            "timestamp": utc_now(),
                        }
            except requests.exceptions.RequestException as e:
                log.warning(f"War Council polling error: {e}")

        return {"error": "Timeout waiting for War Council responses"}

    except Exception as e:
        log.error(f"War Council critical error: {e}")
        return {"error": str(e)}
