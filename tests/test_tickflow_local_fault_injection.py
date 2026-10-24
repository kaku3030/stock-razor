"""Local sockets/processes only. Never live-provider or Windows reboot evidence."""
from contextlib import contextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

import pytest
from scripts import audit_tickflow_windows_readonly as audit
from scripts import run_tickflow_windows_watch as watch


@contextmanager
def local_endpoint(monkeypatch):
    # Fail the test if SDK/proxy configuration tries any non-loopback address.
    original = socket.getaddrinfo
    def loopback_only(host, *args, **kwargs):
        if host not in ("127.0.0.1", b"127.0.0.1"):
            raise AssertionError("external network forbidden")
        return original(host, *args, **kwargs)
    monkeypatch.setattr(socket, "getaddrinfo", loopback_only)
    state = {"mode": "ok", "requests": 0, "volume": 1000}
    labels = ["2026-10-23T09:45:00+08:00","2026-10-23T10:00:00+08:00",
              "2026-10-23T10:15:00+08:00","2026-10-23T10:30:00+08:00"]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            state["requests"] += 1
            if state["mode"] == "disconnect":
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            if state["mode"] == "timeout":
                time.sleep(0.2)
                return
            if state["mode"] == "429":
                payload = {"message":"synthetic rate limit","code":"RATE_LIMIT"}
                body = json.dumps(payload).encode()
                self.send_response(429)
            else:
                payload = {"data":{
                    "timestamp":[int(datetime.fromisoformat(t).timestamp()*1000) for t in labels],
                    "open":[1.05]*4,"high":[1.06]*4,"low":[1.04]*4,
                    "close":[1.055]*4,"volume":[state["volume"]]*4}}
                body = json.dumps(payload).encode()
                self.send_response(200)
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(("127.0.0.1",0), Handler)
    worker = threading.Thread(target=server.serve_forever,daemon=True)
    worker.start()
    try:
        yield state, "http://127.0.0.1:" + str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


@pytest.mark.parametrize("failure",["disconnect","timeout","429"])
def test_installed_sdk_socket_failure_and_recovery(monkeypatch,failure):
    sdk = pytest.importorskip("tickflow")
    if getattr(sdk,"__version__",None) != "0.1.25":
        pytest.skip("requires installed pinned SDK; do not install for this test")
    with local_endpoint(monkeypatch) as (state,url):
        # Explicit synthetic key and loopback base_url; never read Windows credentials.
        client = sdk.TickFlow(api_key="SYNTHETIC_TEST_ONLY",base_url=url,timeout=0.05,max_retries=0)
        try:
            before = client.klines.intraday("159611.SZ",period="15m",count=4,as_dataframe=False)
            state["mode"] = failure
            count = state["requests"]
            started = time.monotonic()
            import httpx
            with pytest.raises((sdk.ConnectionError,sdk.TimeoutError,sdk.RateLimitError,httpx.RemoteProtocolError)):
                client.klines.intraday("159611.SZ",period="15m",count=4,as_dataframe=False)
            assert time.monotonic()-started < 2
            assert state["requests"] == count+1  # No hidden SDK retry.
            state["mode"] = "ok"
            state["volume"] = 1001
            after = client.klines.intraday("159611.SZ",period="15m",count=4,as_dataframe=False)
            now = datetime.fromisoformat("2026-10-23T10:32:00+08:00")
            assert audit.assess_compact(after,"15m",now)["status"] == "PASS_RESEARCH_ONLY"
            assert audit.frame_receipt(before,"15m",now)["row_receipts"][-1]["volume_sha256"] != audit.frame_receipt(after,"15m",now)["row_receipts"][-1]["volume_sha256"]
            assert audit.frame_receipt(after,"15m",now)["latest_bar_closed"] is False
        finally:
            client.close()


def test_hard_process_exit_and_fresh_process_state_recovery(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    target = tmp_path/"latest-poll.json"
    watch.atomic_write(target,{"sequence":1,"status":"BLOCKED"})
    crash = """
import os,sys
from pathlib import Path
path=Path(sys.argv[1])
with open(str(path)+'.interrupted.tmp','w') as out:
    out.write('{"sequence":')
    out.flush()
    os.fsync(out.fileno())
os._exit(71)
"""
    crashed = subprocess.run([sys.executable,"-c",crash,str(target)],capture_output=True,timeout=5)
    assert crashed.returncode == 71
    assert watch.load_state(target) == {"sequence":1,"status":"BLOCKED"}
    restart = """
import sys
from pathlib import Path
from scripts.run_tickflow_windows_watch import load_state,atomic_write
path=Path(sys.argv[1]); prior=load_state(path)
atomic_write(path,{"sequence":prior["sequence"]+1,"status":"REVALIDATION_REQUIRED"})
"""
    resumed = subprocess.run([sys.executable,"-c",restart,str(target)],cwd=repo,
                             capture_output=True,timeout=10)
    assert resumed.returncode == 0
    assert watch.load_state(target) == {"sequence":2,"status":"REVALIDATION_REQUIRED"}
    # An interrupted staging file can never substitute for the published record.
    assert target.with_name(target.name+".interrupted.tmp").exists()

def test_real_sdk_disconnect_is_sanitized_by_actual_auditor_entry(monkeypatch,capsys):
    sdk = pytest.importorskip("tickflow")
    if getattr(sdk,"__version__",None) != "0.1.25":
        pytest.skip("requires installed pinned SDK")
    original = sdk.TickFlow
    with local_endpoint(monkeypatch) as (state,url):
        def factory(**kwargs):
            return original(api_key="SYNTHETIC_TEST_ONLY",base_url=url,timeout=0.05,max_retries=0)
        monkeypatch.setattr(sdk,"TickFlow",factory)
        monkeypatch.setattr(audit,"read_windows_credential",lambda:"SYNTHETIC_TEST_ONLY")
        monkeypatch.setattr(audit,"SYMBOLS",("159611.SZ",))
        monkeypatch.setattr(sys,"argv",["auditor","--execute","--timeframe","15m"])
        state["mode"]="disconnect"
        assert audit.main() == 1
        blocked=json.loads(capsys.readouterr().out)
        assert blocked["status"] == "BLOCKED"
        assert blocked["error_class"] == "RemoteProtocolError"
        assert blocked["live_trade"] is False
        assert "SYNTHETIC_TEST_ONLY" not in json.dumps(blocked)
        # Real new SDK context and a new socket request; only the test clock is frozen.
        class FixtureClock(datetime):
            @classmethod
            def now(cls,tz=None):
                result=datetime.fromisoformat("2026-10-23T10:32:00+08:00")
                return result.astimezone(tz) if tz else result.replace(tzinfo=None)
        monkeypatch.setattr(audit,"datetime",FixtureClock)
        state["mode"]="ok"
        assert audit.main() == 0
        recovered=json.loads(capsys.readouterr().out)
        assert recovered["status"] == "PASS_RESEARCH_ONLY"
        assert recovered["radar_admission"] == "BLOCKED"
        assert recovered["bar_finality"] == "NOT_VERIFIED"

def test_installed_sdk_websocket_reconnect_replays_subscription(monkeypatch):
    sdk=pytest.importorskip("tickflow")
    pytest.importorskip("websockets.sync.server")
    if getattr(sdk,"__version__",None) != "0.1.25":
        pytest.skip("requires installed pinned SDK")
    from websockets.sync.server import serve
    from websockets.exceptions import ConnectionClosed
    from data_provider.tickflow_ws_research_observer import attach_tickflow_stream
    # Explicit proxy bypass only in this isolated loopback fixture.
    monkeypatch.setenv("NO_PROXY","127.0.0.1")
    monkeypatch.setenv("no_proxy","127.0.0.1")
    original=socket.getaddrinfo
    def loopback_only(host,*args,**kwargs):
        if host not in ("127.0.0.1",b"127.0.0.1"):
            raise AssertionError("external network forbidden")
        return original(host,*args,**kwargs)
    monkeypatch.setattr(socket,"getaddrinfo",loopback_only)
    subscriptions=[]
    delivered=threading.Event()
    lock=threading.Lock()
    stamp=time.time_ns()//1_000_000
    def handler(ws):
        message=json.loads(ws.recv(timeout=3))
        with lock:
            subscriptions.append(message)
            ordinal=len(subscriptions)
        ws.send(json.dumps({"op":"subscribed","channel":"quotes","total":1}))
        ws.send(json.dumps({"op":"quotes","data":[{
            "symbol":"159611.SZ","timestamp":stamp+(ordinal-1)*1000,
            "last_price":1.05,"volume":1000+ordinal}]}))
        if ordinal==1:
            ws.close(code=1011,reason="synthetic disconnect")
        else:
            delivered.set()
            try:
                ws.recv(timeout=5)
            except ConnectionClosed:
                pass
    with serve(handler,"127.0.0.1",0) as server:
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        client=sdk.TickFlow(api_key="SYNTHETIC_TEST_ONLY",
                           base_url="http://127.0.0.1:"+str(server.socket.getsockname()[1]),
                           timeout=0.05,max_retries=0)
        observer=attach_tickflow_stream(client,("159611.SZ",))
        try:
            assert delivered.wait(8), "no bounded loopback resubscription"
            deadline=time.monotonic()+2
            while observer.summary()["quote_events"]<2 and time.monotonic()<deadline:
                time.sleep(0.01)
            assert len(subscriptions)==2
            for message in subscriptions:
                assert message=={"op":"subscribe","channel":"quotes","symbols":["159611.SZ"]}
            evidence=observer.summary()
            assert evidence["post_initial_update_candidates"]==1
            assert evidence["continuous_feed_qualified"] is False
            assert evidence["radar_admission"]=="BLOCKED"
        finally:
            client.stream.close()
            client.close()
            client.stream._thread.join(timeout=5)
            server.shutdown()
            thread.join(timeout=2)
        assert not client.stream._thread.is_alive()
