# Private CN MCP reference fixture conversion (offline)

This helper is an **optional, local-only** preparation step for the separate TickFlow ↔ Tencent/Eastmoney closed-bar comparison in PR #480. It does **not** connect TickFlow to ChatGPT, call any provider, or qualify production data.

Save an already obtained **direct JSON** response from `get_cn_market_data(symbol="159611.SZ", timeframe="15m", limit=...)` in a private local file. The converter consumes the JSON without performing network requests. It checks symbol, provider, verified `BAR_END` timestamp semantics, row quality flags, and that each bar predates the observation by at least 60 seconds. It removes source paths, keys, raw provider labels, account fields, and other unexpected fields.

### Required manual confirmations

1. Confirm the selected ETF and time period correspond to **completed** bars and the expected Shanghai trading session. The comparator separately checks session labels but does not prove exchange holidays.
2. Verify from the relevant source contract that the provider's `HAND` means a specific number of shares for this instrument. **Do not blindly assume 100.** The command requires an explicit `--shares-per-hand` for HAND data, and `--attest-volume-unit`.
3. Verify the prices are **unadjusted** before passing `--attest-unadjusted`. The current MCP observation does not itself prove adjustment.
4. Keep the generated fixture outside the repo and never commit or publish it without checking licensing, confidentiality and data rights. `REAL_CAPTURED` is a user-attested label, not independently verified provenance.

Example after manual validation of volume conversion (replace `<VERIFIED_SHARES_PER_HAND>` with the verified integer):

```bash
python3 scripts/cn_mcp_offline_fixture_converter.py \
  --input /private/cn_mcp_159611_15m.json \
  --output /private/tencent_159611_15m_fixture.json \
  --symbol 159611.SZ --timeframe 15m \
  --shares-per-hand <VERIFIED_SHARES_PER_HAND> \
  --attest-volume-unit --attest-unadjusted
```

Output is a new private `0600` file and the script refuses to overwrite an existing file. Standard output only reports a short status and row count; it never prints bar values or secrets.

The resulting fixture follows `stock_razor_cn_offline_bar_fixture_v0_1` and can be compared to a **separately, legitimately captured** TickFlow fixture once both are normalized. A comparison match is observational only. This converter does not prove currentness, TickFlow schema, websocket continuity, or Radar admission. `RADAR_ADMISSION=BLOCKED` and `LIVE_TRADE=NO` remain unchanged.
