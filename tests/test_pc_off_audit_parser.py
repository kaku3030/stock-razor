from src.services.live_feed.pc_off_audit_parser import extract_futures_heartbeat_payloads


PAYLOAD = '{"type":"futures_runtime_heartbeat","runtime_instance_id":"r1","generation":1,"host_id":"h1","sequence":83,"emitted_at_utc":"2026-10-05T05:45:20+00:00"}'


def test_extracts_plain_journal_payload():
    rows = extract_futures_heartbeat_payloads([f"Oct 05 host python[1]: {PAYLOAD}\n"])
    assert rows[0]["sequence"] == 83


def test_extracts_aws_cli_text_escaped_payload():
    escaped = PAYLOAD.replace('"', r'\"')
    rows = extract_futures_heartbeat_payloads([f"Oct 05 host python[1]: {escaped}\\nOct 05 host next"])
    assert rows[0]["runtime_instance_id"] == "r1"
    assert rows[0]["sequence"] == 83


def test_extracts_multiple_escaped_payloads_from_single_cli_text_record():
    p2 = PAYLOAD.replace('"sequence":83', '"sequence":84')
    escaped = (PAYLOAD + "\n" + p2).replace('"', chr(92) + '"').replace("\n", chr(92) + "n")
    rows = extract_futures_heartbeat_payloads([escaped])
    assert [row["sequence"] for row in rows] == [83, 84]


def test_ignores_non_heartbeat_text_around_payload():
    rows = extract_futures_heartbeat_payloads(["prefix status text " + PAYLOAD + " suffix"])
    assert len(rows) == 1
