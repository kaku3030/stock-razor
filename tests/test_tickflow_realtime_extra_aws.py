"""Official TickFlow realtime extra must be present before any WS/REST calls.

No external SDK network, credentials, AWS service or broker actions.
"""
import builtins
from pathlib import Path
import sys
from types import ModuleType

from scripts import probe_tickflow_isolated as probe


REQUIREMENTS=Path("ops/requirements/tickflow-isolated-v0.1.txt")
BOOTSTRAP=Path("ops/aws/run_tickflow_premium_probe.sh")


def test_tickflow_realtime_extra_is_pinned_not_plain_http_only():
    txt=REQUIREMENTS.read_text(encoding="utf-8")
    assert "tickflow[realtime]==0.1.25" in txt
    assert "websockets==15.0.1" in txt
    assert "\ntickflow==0.1.25\n" not in txt


def test_aws_import_and_version_check_happens_before_secret_or_rest():
    s=BOOTSTRAP.read_text(encoding="utf-8")
    index_verify=s.index("probe_stage=VERIFY_REALTIME_EXTRA")
    index_secret=s.index("probe_stage=READ_SECRET")
    index_probe=s.index("probe_stage=RUN_PREMIUM_PROBE")
    assert s.index("probe_stage=INSTALL_DEPENDENCIES") < index_verify
    assert index_verify < index_secret < index_probe
    assert 'if [[ "$ws_seconds" != "0" ]]; then' in s
    assert 'import websockets; assert m.version("websockets") == "15.0.1"' in s
    assert "TICKFLOW_WS_DEPENDENCY=UNAVAILABLE" in s
    assert "trap cleanup EXIT" in s
    assert "unset TICKFLOW_API_KEY secret_json" in s


def test_missing_websockets_blocks_official_sdk_before_client_creation(monkeypatch):
    class ExplodingClient:
        init_calls=0

        def __init__(self,*args,**kwargs):
            ExplodingClient.init_calls+=1
            raise AssertionError("SDK client should not initialize")

    synthetic=ModuleType("tickflow")
    synthetic.TickFlow=ExplodingClient
    original_import=builtins.__import__

    def import_without_websocket(name,*args,**kwargs):
        if name=="websockets":
            raise ModuleNotFoundError("simulated optional dependency missing")
        return original_import(name,*args,**kwargs)

    with monkeypatch.context() as m:
        m.setitem(sys.modules,"tickflow",synthetic)
        m.setattr(builtins,"__import__",import_without_websocket)
        result=probe.build_probe(
            mode="premium",symbols=("159611.SZ","159209.SZ"),
            ws_seconds=10,credential_present=True,
            sdk_version="0.1.25",
        )
    assert [x["name"] for x in result["operations"]]==[
        "sdk_import","websocket_quote_smoke"
    ]
    assert result["operations"][-1]["operation"]=="BLOCKED"
    assert result["operations"][-1]["reason"]=="TICKFLOW_REALTIME_EXTRA_UNAVAILABLE"
    assert ExplodingClient.init_calls==0
    assert result["source_arbiter_admission"]=="BLOCKED"
    assert result["radar_admission"]=="BLOCKED"
    assert result["canonical_write"] is False
    assert result["live_trade"] is False


def test_aws_premium_probe_targets_the_requested_two_etfs():
    script=BOOTSTRAP.read_text(encoding="utf-8")
    start=script.index("probe_args=(")
    end=script.index('if [[ "$quote_only" == true ]]',start)
    scope=script[start:end]
    assert "--symbols 159611.SZ 159209.SZ" in scope
    assert "518880.SH" not in scope
    # The sanitized receipt must preserve exactly the requested pair so the
    # cloud evidence can prove which two quote targets were actually tested.
    assert 'if symbol in ("159611.SZ","159209.SZ"):' in script


def test_ws_import_guard_does_not_block_explicit_no_ws_premium_rest(monkeypatch):
    class SafeFake:
        called=0
        def __init__(self,*args,**kwargs):
            SafeFake.called+=1
            self.quotes=self
            self.klines=self
            self.depth=self
        def get(self,*args,**kwargs):
            return []

    synthetic=ModuleType("tickflow")
    synthetic.TickFlow=SafeFake
    original_import=builtins.__import__

    def block_websockets(name,*args,**kwargs):
        if name=="websockets":
            raise ModuleNotFoundError("missing")
        return original_import(name,*args,**kwargs)

    with monkeypatch.context() as m:
        m.setitem(sys.modules,"tickflow",synthetic)
        m.setattr(builtins,"__import__",block_websockets)
        result=probe.build_probe(
            mode="premium",symbols=("159611.SZ",),
            quote_only=True,ws_seconds=0,
            credential_present=True,
        )
    assert SafeFake.called==1
    assert result["operations"][-1]["name"]=="realtime_quote"
    assert result["operations"][-1]["operation"]=="COMPLETED"
    assert result["radar_admission"]=="BLOCKED"
