"""One explicit Windows SDK read; private hashes only, no orders or subscriptions."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess

from data_provider.cn_tickflow_research_cache import build_observation
from data_provider.tickflow_evidence_checkpoints import manifest_from_observation, write_immutable, compare_manifests, pairing_summary, compare_pairing_summaries, _load, SAFE
from scripts.audit_tickflow_windows_readonly import read_windows_credential


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-sha")
    parser.add_argument("--sequence", type=int, default=1)
    parser.add_argument("--output")
    parser.add_argument("--compare", nargs=2, metavar=("FIRST", "SECOND"))
    parser.add_argument("--dual-endpoint", action="store_true")
    parser.add_argument("--compare-summaries", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--summarize-manifest")
    args = parser.parse_args()
    if args.summarize_manifest:
        try:
            if args.execute or args.compare:
                raise ValueError("CONFLICTING_MODE")
            result = {**SAFE,"status":"POSTCLOSE_PAIR_CAPTURE_RESEARCH_ONLY",
                      "pairing_summary":pairing_summary(_load(Path(args.summarize_manifest)))}
        except Exception:
            result = {**SAFE,"status":"EVIDENCE_INVALID"}
        print(json.dumps(result))
        return 2 if result["status"] == "EVIDENCE_INVALID" else 0
    if args.compare:
        try:
            if args.execute:
                raise ValueError("CONFLICTING_MODE")
            if args.compare_summaries:
                docs=[]
                for path in args.compare:
                    with open(path,"rb") as handle:
                        raw=handle.read(16001)
                    if len(raw)>16000:
                        raise ValueError("SUMMARY_TOO_LARGE")
                    docs.append(json.loads(raw))
                result=compare_pairing_summaries(*docs)
            else:
                result = compare_manifests(*(_load(Path(p)) for p in args.compare),
                                           dual_endpoint=args.dual_endpoint)
        except Exception:
            result = {**SAFE,"status":"EVIDENCE_INVALID"}
        print(json.dumps(result))
        return 2 if result["status"] == "EVIDENCE_INVALID" else 0
    if not args.execute:
        print(json.dumps({**SAFE,"status":"NOT_EXECUTED_OPT_IN_REQUIRED"}))
        return 0
    client = None
    sdk_attempted = False
    try:
        if os.name != "nt" or not args.output or args.sequence < 1:
            raise ValueError("INPUT_OR_PLATFORM_BLOCKED")
        actual = subprocess.run(["git","rev-parse","HEAD"],cwd=Path(__file__).resolve().parents[1],
            check=True,capture_output=True,text=True,timeout=5).stdout.strip()
        dirty = subprocess.run(["git","status","--porcelain","--untracked-files=normal"],
            cwd=Path(__file__).resolve().parents[1],check=True,capture_output=True,text=True,timeout=5).stdout
        if dirty.strip() or actual != args.expected_sha or importlib.metadata.version("tickflow") != "0.1.25":
            raise ValueError("REVISION_OR_SDK_MISMATCH")
        with open(os.devnull,"w") as quiet, redirect_stdout(quiet), redirect_stderr(quiet):
            from tickflow import TickFlow
            sdk_attempted = True
            client = TickFlow(api_key=read_windows_credential(),timeout=8,max_retries=0)
            observed = datetime.now(timezone.utc)
            snapshot = build_observation(client,now_utc=observed,repo_sha=actual,
                sequence=args.sequence,include_supplemental=True,use_batch=True)
        manifest = manifest_from_observation(snapshot,endpoint="WINDOWS",now_utc=datetime.now(timezone.utc))
        summary = {"pairing_summary":pairing_summary(manifest)} if args.summary else {}
        created = write_immutable(Path(args.output),manifest)
        print(json.dumps({**SAFE,**summary,"provider_requests":None,"sdk_observation_attempted":True,
                          "status":"PRIVATE_CAPTURE_RECORDED" if created else "OUTPUT_ALREADY_EXISTS",
                          "frame_count":len(manifest["frames"])}))
        return 0 if created else 2
    except Exception:
        print(json.dumps({**SAFE,"provider_requests":None if sdk_attempted else 0,
                          "sdk_observation_attempted":sdk_attempted,"status":"CAPTURE_BLOCKED"}))
        return 2
    finally:
        if client is not None:
            try:
                with open(os.devnull,"w") as quiet, redirect_stdout(quiet), redirect_stderr(quiet):
                    client.close()
            except Exception:
                pass  # Never leak credential-bearing SDK exception text at shutdown.


if __name__ == "__main__":
    raise SystemExit(main())
