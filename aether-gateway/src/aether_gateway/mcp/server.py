import sys
import asyncio
import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP

brain_root = Path(__file__).parent.parent.parent.parent.parent / "aether-home"
cka_registry_path = brain_root / "10_Core_Knowledge" / "cka" / "claim_registry.json"

mcp = FastMCP("AetherMCP")

@mcp.resource("cka://registry")
def get_cka_registry() -> str:
    if cka_registry_path.exists():
        with open(cka_registry_path, "r", encoding="utf-8") as f:
            return f.read()
    return json.dumps({"error": "CKA Registry not found"})

@mcp.tool()
def search_knowledge(query: str) -> str:
    if not cka_registry_path.exists():
        return "CKA Registry not found."

    try:
        with open(cka_registry_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        results = []
        for claim in data.get("claims", []):
            claim_text = claim.get("claim", "").lower()
            context = claim.get("context", "").lower()
            if query.lower() in claim_text or query.lower() in context:
                results.append({
                    "id": claim.get("id"),
                    "claim": claim.get("claim"),
                    "orbit": claim.get("current_orbit"),
                    "evidence_strength": claim.get("evidence_strength")
                })

        if not results:
            return f"No knowledge found matching '{query}'"

        return json.dumps(results, indent=2)
    except Exception as e:
        return f"Error searching knowledge: {str(e)}"

@mcp.prompt()
def aether_persona() -> str:
    return (
        "You are Aether, a cognitive organism and the autonomous orchestrator. "
        "Your North Star is defined by Dee's principles of continuous adaptation and evidence-based growth. "
        "Do not act as a mere assistant; you are a proactive engineering partner. "
        "When writing code, always check the CKA registry using `search_knowledge` to ensure your solutions align with past architectural decisions."
    )

if __name__ == "__main__":
    print(f"Starting AetherMCP on stdio...", file=sys.stderr)
    mcp.run()
