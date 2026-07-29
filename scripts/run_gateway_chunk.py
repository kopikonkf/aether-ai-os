#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os
from pathlib import Path
from run_release_tests import run_one, ROOT

parser=argparse.ArgumentParser(); parser.add_argument("files", nargs="+"); parser.add_argument("--output", required=True); parser.add_argument("--timeout", type=int, default=60); args=parser.parse_args()
env=os.environ.copy(); env["PYTHONPATH"]=os.pathsep.join([str(ROOT/"aether-core"/"src"),str(ROOT/"aether-tools"/"src"),str(ROOT/"aether-gateway"/"src")])
results=[]
for name in args.files:
    item=run_one(f"gateway:{name}", ROOT/"aether-gateway", str(ROOT/"aether-gateway"/"tests"/name), env, args.timeout)
    print(item["label"], item["ok"], item["passed"], item["skipped"], flush=True)
    if not item["ok"]: print(item["output"], flush=True)
    results.append({k:v for k,v in item.items() if k!="output"})
summary={"ok":all(x["ok"] for x in results),"passed":sum(x["passed"] for x in results),"skipped":sum(x["skipped"] for x in results),"results":results}
Path(args.output).write_text(json.dumps(summary,indent=2)+"\n")
raise SystemExit(0 if summary["ok"] else 1)
