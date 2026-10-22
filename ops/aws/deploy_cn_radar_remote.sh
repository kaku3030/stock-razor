#!/usr/bin/env bash
set -euo pipefail
umask 077

SOURCE_PROVIDER="${SOURCE_PROVIDER:?SOURCE_PROVIDER is required}"
REPO_REF="${REPO_REF:?REPO_REF exact worker commit SHA is required}"
INSTALL_SHA="${INSTALL_SHA:?INSTALL_SHA is required}"
VERIFY_SHA="${VERIFY_SHA:?VERIFY_SHA is required}"
case "$SOURCE_PROVIDER" in eastmoney|tickflow) ;; *) exit 2 ;; esac
[[ "$REPO_REF" =~ ^[a-f0-9]{40}$ ]]
[[ "$INSTALL_SHA" =~ ^[a-f0-9]{64}$ ]]
[[ "$VERIFY_SHA" =~ ^[a-f0-9]{64}$ ]]

stage=REMOTE_INIT
stage_dir=""
on_exit() {
  rc=$?
  if [[ "$rc" -ne 0 ]]; then
    printf 'CN_RADAR_STAGE=%s\nCN_RADAR_REMOTE_EXIT_CODE=%s\n' "$stage" "$rc" >&2
  fi
  if [[ -n "$stage_dir" ]]; then rm -rf "$stage_dir"; fi
}
trap on_exit EXIT

stage=TEMP_DIR
if ! stage_dir="$(mktemp -d)"; then
  echo 'CN_RADAR_STAGE=TEMP_DIR' >&2
  exit 1
fi

stage=INSTALL_DOWNLOAD
if ! curl -fsSL --proto '=https' --tlsv1.2 \
  "https://raw.githubusercontent.com/kaku3030/stock-razor/$REPO_REF/ops/aws/install_cn_radar_worker.sh" \
  -o "$stage_dir/install.sh"; then
  echo 'CN_RADAR_STAGE=INSTALL_DOWNLOAD' >&2
  exit 1
fi
stage=INSTALL_HASH
if ! printf '%s  %s\n' "$INSTALL_SHA" "$stage_dir/install.sh" | sha256sum -c - >/dev/null; then
  echo 'CN_RADAR_STAGE=INSTALL_HASH' >&2
  exit 1
fi

stage=VERIFY_DOWNLOAD
if ! curl -fsSL --proto '=https' --tlsv1.2 \
  "https://raw.githubusercontent.com/kaku3030/stock-razor/$REPO_REF/ops/aws/verify_cn_radar_worker.sh" \
  -o "$stage_dir/verify.sh"; then
  echo 'CN_RADAR_STAGE=VERIFY_DOWNLOAD' >&2
  exit 1
fi
stage=VERIFY_HASH
if ! printf '%s  %s\n' "$VERIFY_SHA" "$stage_dir/verify.sh" | sha256sum -c - >/dev/null; then
  echo 'CN_RADAR_STAGE=VERIFY_HASH' >&2
  exit 1
fi

stage=INSTALL
if ! SOURCE_PROVIDER="$SOURCE_PROVIDER" REPO_REF="$REPO_REF" bash "$stage_dir/install.sh" >"$stage_dir/install.log" 2>"$stage_dir/install.err"; then
  echo 'CN_RADAR_INSTALL=FAILED' >&2
  exit 1
fi

stage=ACCEPTANCE
if ! bash "$stage_dir/verify.sh" "$REPO_REF" "$SOURCE_PROVIDER" >"$stage_dir/verify.log" 2>"$stage_dir/verify.err"; then
  echo 'CN_RADAR_ACCEPTANCE=FAILED' >&2
  exit 1
fi
stage=VERIFY_OUTPUT
if ! grep -Fx enabled "$stage_dir/verify.log" >/dev/null ||
   ! grep -Fx active "$stage_dir/verify.log" >/dev/null ||
   ! grep -Fx CN_RADAR_WORKER_VERIFY=PASS "$stage_dir/verify.log" >/dev/null ||
   ! grep -Fx RADAR_ADMISSION=BLOCKED "$stage_dir/verify.log" >/dev/null ||
   ! grep -Fx LIVE_TRADE=NO "$stage_dir/verify.log" >/dev/null; then
  echo 'CN_RADAR_STAGE=VERIFY_OUTPUT' >&2
  exit 1
fi

printf 'CN_RADAR_WORKER_AWS_DEPLOYMENT=PASS\nRADAR_ADMISSION=BLOCKED\nLIVE_TRADE=NO\n'
