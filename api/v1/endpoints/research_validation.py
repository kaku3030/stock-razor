# -*- coding: utf-8 -*-
"""Research-only Radar Harness endpoints.

The GitHub token is read exclusively on the server. These endpoints never
promote a rule or place an order.
"""
from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

router = APIRouter()

_REPO = os.getenv("RADAR_GITHUB_REPOSITORY", "kaku3030/stock-razor")
_BRANCH = os.getenv("RADAR_GITHUB_BRANCH", "research/rule-validation-harness-v0-1")
_WORKFLOW = os.getenv("RADAR_GITHUB_WORKFLOW", "research-universe-capture.yml")
_TOKEN_ENV = "RADAR_GITHUB_TOKEN"
_ALLOWED_COUNTERFACTUALS = {
    "without_rule",
    "with_rule",
    "delayed_rule",
    "shuffled_placebo",
    "regime_conditioned",
}


class ResearchValidationConfig(BaseModel):
    """Strict, research-only configuration accepted by the UI."""

    rule_id: str = Field(min_length=1, max_length=120)
    rule_version: str = Field(default="v0.1", min_length=1, max_length=40)
    symbol: str = Field(min_length=1, max_length=32)
    development_end: str
    validation_end: str
    holdout_id: str = Field(min_length=1, max_length=120)
    counterfactuals: List[str] = Field(
        default_factory=lambda: sorted(_ALLOWED_COUNTERFACTUALS),
        min_length=1,
        max_length=5,
    )
    research_only: bool = Field(default=True)

    @field_validator("research_only")
    @classmethod
    def _research_only_required(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("research_only must remain true")
        return value

    @field_validator("counterfactuals")
    @classmethod
    def _counterfactuals_allowed(cls, value: List[str]) -> List[str]:
        unknown = set(value) - _ALLOWED_COUNTERFACTUALS
        if unknown:
            raise ValueError(f"unsupported counterfactuals: {sorted(unknown)}")
        return list(dict.fromkeys(value))


def _github_headers() -> Dict[str, str]:
    token = os.getenv(_TOKEN_ENV, "").strip()
    if not token:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "github_token_unavailable",
                "message": "Research artifact proxy is not configured on this server.",
            },
        )
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "stock-razor-radar-harness",
    }


def _json_files_from_zip(payload: bytes) -> Dict[str, Any]:
    extracted: Dict[str, Any] = {}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for name in archive.namelist():
            if not name.lower().endswith(".json") or name.endswith("/"):
                continue
            # Keep the proxy bounded and avoid returning arbitrary files.
            if archive.getinfo(name).file_size > 10 * 1024 * 1024:
                continue
            try:
                extracted[name] = json.loads(archive.read(name).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
    return extracted


@router.get("/artifact")
async def get_latest_artifact() -> Dict[str, Any]:
    """Return the latest successful capture artifact as structured JSON."""
    headers = _github_headers()
    base = f"https://api.github.com/repos/{_REPO}"
    params = {"branch": _BRANCH, "status": "success", "per_page": "10"}
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        runs = await client.get(f"{base}/actions/workflows/{_WORKFLOW}/runs", params=params, headers=headers)
        if runs.status_code != 200:
            raise HTTPException(status_code=502, detail={"error": "github_runs_failed", "status": runs.status_code})
        run_items = runs.json().get("workflow_runs", [])
        if not run_items:
            raise HTTPException(status_code=404, detail={"error": "artifact_not_found"})
        run = run_items[0]
        artifacts = await client.get(f"{base}/actions/runs/{run['id']}/artifacts", headers=headers)
        if artifacts.status_code != 200:
            raise HTTPException(status_code=502, detail={"error": "github_artifacts_failed", "status": artifacts.status_code})
        available = [a for a in artifacts.json().get("artifacts", []) if not a.get("expired")]
        if not available:
            raise HTTPException(status_code=404, detail={"error": "artifact_not_found"})
        artifact = available[0]
        download = await client.get(artifact["archive_download_url"], headers=headers)
        if download.status_code != 200:
            raise HTTPException(status_code=502, detail={"error": "github_download_failed", "status": download.status_code})
    return {
        "research_only": True,
        "run": {
            "id": run.get("id"),
            "url": run.get("html_url"),
            "created_at": run.get("created_at"),
            "head_sha": run.get("head_sha"),
        },
        "artifact": {
            "id": artifact.get("id"),
            "name": artifact.get("name"),
            "size_in_bytes": artifact.get("size_in_bytes"),
            "digest": artifact.get("digest"),
            "updated_at": artifact.get("updated_at"),
        },
        "files": _json_files_from_zip(download.content),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/submit", status_code=202)
async def submit_research_config(config: ResearchValidationConfig) -> Dict[str, Any]:
    """Validate and acknowledge a research task; no production execution."""
    return {
        "status": "accepted_for_research",
        "research_only": True,
        "production_promotion": "locked",
        "task_id": f"radar-{config.rule_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "config": config.model_dump(),
        "next_step": "Run through PIT/anti-leak and protected holdout gates.",
    }
