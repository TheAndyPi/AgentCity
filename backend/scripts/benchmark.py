"""Measure the actual HTTP and durable simulation paths, without vendor keys."""

import argparse
import asyncio
import json
import os
import time
from collections import Counter
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.infrastructure.config import AppConfig
from app.main import create_app
from scripts.client import Driver


def p95(values):
    return sorted(values)[max(0, int(len(values) * 0.95 + 0.999) - 1)] if values else None


def peak_memory_bytes():
    """Peak of this application/test-driver process, rather than system RAM."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t)
                for name in (
                    "peak_working_set",
                    "working_set",
                    "quota_peak_paged",
                    "quota_paged",
                    "quota_peak_nonpaged",
                    "quota_nonpaged",
                    "pagefile",
                    "peak_pagefile",
                )
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL("kernel32")
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError()
        return counters.peak_working_set
    import resource
    import sys

    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform == "darwin" else value * 1024


class BlockedTiger:
    async def migrate(self):
        pass

    async def ingest(self, batch):
        await asyncio.Event().wait()


def run(population, steps, live_ticks, blocked_tiger=False, horizon=10000):
    with TemporaryDirectory() as temp:
        directory = Path(temp)
        app = create_app(
            AppConfig(
                data_dir=directory,
                tiger_enabled=blocked_tiger,
                tiger_database_url="controlled-outage" if blocked_tiger else "",
            )
        )
        integration = (
            patch("app.integrations.tiger.PostgresSink", lambda config: BlockedTiger())
            if blocked_tiger
            else nullcontext()
        )
        with integration, TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
            driver = Driver(client)
            start = time.perf_counter()
            simulation = driver.city(population=population, max_ticks=horizon)
            sid = simulation["id"]
            initialization = time.perf_counter() - start
            timings = []
            for i in range(steps):
                start = time.perf_counter()
                driver.command(sid, "step", count=1)
                timings.append(time.perf_counter() - start)
            control = []
            for _ in range(10):
                start = time.perf_counter()
                driver.command(sid, "set_speed", value=1)
                control.append(time.perf_counter() - start)
            with client.websocket_connect(f"ws://127.0.0.1/api/v1/simulations/{sid}/stream") as socket:
                socket.send_json(dict(type="hello", schema_version="1.0.0", last_revision=None))
                socket.receive_json()
                baseline = driver.get(f"/simulations/{sid}")["tick"]
                driver.command(sid, "play")
                start = time.perf_counter()
                while driver.get(f"/simulations/{sid}")["tick"] - baseline < live_ticks:
                    socket.receive_json()
                elapsed = time.perf_counter() - start
                driver.command(sid, "pause")
            service = app.state.service
            state = service.heads[sid]
            source_counts = Counter(decision.source for decision in state.decisions)
            bytes_used = sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())
            return dict(
                population=population,
                initialization_seconds=initialization,
                manual_ticks=steps,
                live_ticks=live_ticks,
                http_step_p95_ms=p95(timings) * 1000,
                http_control_p95_ms=p95(control) * 1000,
                achieved_live_ticks_per_second=(state.simulation.tick - baseline) / elapsed,
                tick_compute_p95_ms=p95(service.stats["tick_seconds"]) * 1000,
                commit_p95_ms=p95(service.stats["commit_seconds"]) * 1000,
                provider_queue_depth=sum(not task.done() for task in service.provider_tasks.values()),
                decision_sources=dict(source_counts),
                rules_fraction=source_counts.get("rules", 0) / max(1, len(state.decisions)),
                usage=service.usage("demo_owner", sid).model_dump(),
                socket_bytes=service.stats["socket_bytes"],
                persisted_bytes=bytes_used,
                revisions=state.simulation.revision + 1,
                peak_process_bytes=peak_memory_bytes(),
                tiger_enabled=service.config.tiger_enabled,
                tiger_blocked_fake=blocked_tiger,
                tiger_lag_revisions=service.tiger.status("demo_owner")["simulations"][0]["lag_revisions"],
                configured_horizon=horizon,
                final_tick=state.simulation.tick,
                final_status=state.simulation.status,
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--live-ticks", type=int, default=10)
    parser.add_argument("--populations", type=int, nargs="+", default=[10, 30, 100])
    parser.add_argument("--blocked-tiger", action="store_true")
    parser.add_argument("--horizon", type=int, default=10000)
    parser.add_argument("--output", type=Path, default=Path("artifacts/performance.json"))
    args = parser.parse_args()
    if args.steps < 1 or args.live_ticks < 1 or args.steps + args.live_ticks > args.horizon:
        parser.error("positive manual/live ticks must fit within the configured horizon")
    results = dict(
        contract_version="1.0.0",
        mode="rules",
        platform="measured locally; see Python/runtime lock",
        results=[
            run(population, args.steps, args.live_ticks, args.blocked_tiger, args.horizon)
            for population in args.populations
        ],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
