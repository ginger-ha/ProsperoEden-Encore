#!/usr/bin/env python3
"""Pair FC27 native RELEASE frame/pressure windows, keeping launches separate.

The older analyze-fc27-stutter.py intentionally demands EDEN_DEV_GPU.
Quiet release builds lack it. This tool uses only emitted frame/pressure
fields, NEVER interprets uninstrumented guest IPC/JIT/GPU zeros as evidence.
No raw console logs are distributed with this tool.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from pathlib import Path

SESSION = re.compile(r"^EDEN_SESSION_SOURCE\s+source_sha=([0-9a-f]{40})(?:\s|$)")
NUMERIC = re.compile(r"([A-Za-z][A-Za-z0-9_]*)=(-?[0-9]+(?:\.[0-9]+)?)")


def fields(line: str) -> dict[str, float]:
    return {key: float(value) for key, value in NUMERIC.findall(line)}


def pearson(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 3:
        return None
    x, y = zip(*pairs)
    mx, my = statistics.mean(x), statistics.mean(y)
    xx = sum((v - mx) ** 2 for v in x)
    yy = sum((v - my) ** 2 for v in y)
    if xx == 0 or yy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in pairs) / math.sqrt(xx * yy)


def collect(text: str) -> list[dict]:
    sessions: list[dict] = []
    session: dict | None = None
    for line in text.splitlines():
        match = SESSION.match(line)
        if match:
            session = {"source_sha": match.group(1), "frames": {}, "pressure": {},
                       "detailed_gpu_reports": 0}
            sessions.append(session)
            continue
        if session is None:
            continue
        if line.startswith("EDEN_VULKAN_FRAME frames="):
            row = fields(line)
            if {"total", "fps", "worst_ms", "late50", "late100", "seconds"} <= row.keys():
                frame = int(row["total"])
                if frame in session["frames"]:
                    raise ValueError(f"Repeated renderer frame {frame} inside one session")
                session["frames"][frame] = row
        elif line.startswith("EDEN_FRAME_PRESSURE frame="):
            row = fields(line)
            if "frame" in row and "cache_wait_ms" in row:
                frame = int(row["frame"])
                if frame in session["pressure"]:
                    raise ValueError(f"Repeated pressure frame {frame} inside one session")
                session["pressure"][frame] = row
        elif line.startswith("EDEN_DEV_GPU frame="):
            session["detailed_gpu_reports"] += 1
    return sessions




def steady_state(session: dict, warmup_seconds: float = 180.0,
                 min_late50: int = 5) -> dict:
    """Rank sustained-playback bursts without mixing launches or missing counters.

    Elapsed time is the sum of renderer five-second windows; it is not the
    guest match clock. A session may include loading/menus after warmup.
    Cache waits sum work on multiple threads, not blocked frame wall time.
    """
    elapsed = 0.0
    rows = []
    unpaired = 0
    for frame_id, frame in sorted(session["frames"].items()):
        elapsed += frame["seconds"]
        if elapsed <= warmup_seconds:
            continue
        pressure = session["pressure"].get(frame_id)
        if pressure is None or "cache_wait_ms" not in pressure:
            unpaired += 1
            continue
        rows.append({
            "frame": frame_id, "end_s": round(elapsed, 1),
            "fps": round(frame["fps"], 3),
            "late50": int(frame["late50"]),
            "late100": int(frame["late100"]),
            "worst_ms": round(frame["worst_ms"], 3),
            "cache_blocked": (int(pressure["cache_blocked"])
                              if "cache_blocked" in pressure else None),
            "cache_wait_ms_multi_thread": round(pressure["cache_wait_ms"], 3),
        })
    bursts = [r for r in rows if r["late50"] >= min_late50]
    return {
        "warmup_excluded_s": warmup_seconds,
        "late50_burst_threshold": min_late50,
        "paired_windows": len(rows),
        "unpaired_windows": unpaired,
        "burst_windows": len(bursts),
        "burst_late50": sum(r["late50"] for r in bursts),
        "steady_late50": sum(r["late50"] for r in rows),
        "zero_late50_windows": sum(r["late50"] == 0 for r in rows),
        "bursts": sorted(bursts, key=lambda r: (-r["late50"], -r["worst_ms"]))[:12],
        "cache_wait_interpretation":
            "Multi-thread 5-second cumulative contention, not per-frame "
            "stall ownership or proof of causality.",
        "hud_freshness": "NOT_MEASURED",
        "guest_progress": "NOT_MEASURED",
    }


def summarize(session: dict, ordinal: int) -> dict:
    frames, pressure = session["frames"], session["pressure"]
    keys = sorted(frames.keys() & pressure.keys())
    if not keys:
        return {"session": ordinal, "source_sha": session["source_sha"],
                "status": "NO_PAIRABLE_WINDOWS", "paired_windows": 0}
    pairs = [(frames[k], pressure[k]) for k in keys]
    total_late50 = sum(int(frame["late50"]) for frame, _ in pairs)
    severe = [(frame, perf) for frame, perf in pairs if frame["late50"] >= 5]
    quiet = [(frame, perf) for frame, perf in pairs if frame["late50"] == 0]
    corr = pearson([(frame["late50"], perf["cache_wait_ms"]) for frame, perf in pairs])
    return {
        "session": ordinal,
        "source_sha": session["source_sha"],
        "status": "RELEASE_FRAME_PRESSURE_ONLY" if not session["detailed_gpu_reports"] else "DETAILED_GPU_PRESENT",
        "paired_windows": len(keys),
        "unpaired_frames": len(frames) - len(keys),
        "unpaired_pressure": len(pressure) - len(keys),
        "steady_state": steady_state(session),
        "seconds_observed": round(sum(frame["seconds"] for frame, _ in pairs), 3),
        "median_reported_fps": round(statistics.median(frame["fps"] for frame, _ in pairs), 3),
        "minimum_window_fps": round(min(frame["fps"] for frame, _ in pairs), 3),
        "late50": total_late50,
        "late100": sum(int(frame["late100"]) for frame, _ in pairs),
        "worst_present_interval_ms": round(max(frame["worst_ms"] for frame, _ in pairs), 3),
        "cache_wait_ms_aggregate_threads": round(sum(perf["cache_wait_ms"] for _, perf in pairs), 3),
        "cache_wait_late50_pearson": round(corr, 3) if corr is not None else None,
        "windows_with_5_or_more_late50": len(severe),
        "share_late50_in_those_windows": round(
            sum(int(frame["late50"]) for frame, _ in severe) / total_late50, 3
        ) if total_late50 else None,
        "mean_cache_wait_ms_5plus": round(
            statistics.mean(perf["cache_wait_ms"] for _, perf in severe), 3
        ) if severe else None,
        "mean_cache_wait_ms_zero_late50": round(
            statistics.mean(perf["cache_wait_ms"] for _, perf in quiet), 3
        ) if quiet else None,
        "unmeasured_release_fields": [
            "jit_compile_duration", "guest_ipc_duration", "gpu_worker_busy",
            "hud_glyph_timing", "input_to_visible_frame", "pixel_freshness"
        ] if not session["detailed_gpu_reports"] else [
            "hud_glyph_timing", "input_to_visible_frame", "pixel_freshness"
        ],
        "interpretation": "Five-second correlations, not per-frame causality. "
                          "Aggregate cache wait overlaps threads. A displayed callback "
                          "does not certify a new guest-rendered image.",
    }


def analyze(text: str) -> list[dict]:
    return [summarize(session, i) for i, session in enumerate(collect(text), 1)]


def self_test() -> None:
    first = "1" * 40
    second = "2" * 40
    def session(sha: str, waits: list[int], late: list[int], detailed: bool = False) -> str:
        lines = [f"EDEN_SESSION_SOURCE source_sha={sha}"]
        for index in range(3):
            frame = 150 * (index + 1)
            lines.append(f"EDEN_VULKAN_FRAME frames=150 seconds=5 fps=30 worst_ms=100 "
                         f"total={frame} late38=4 late50={late[index]} late100=1")
            lines.append(f"EDEN_FRAME_PRESSURE frame={frame} cache_wait_ms={waits[index]} "
                         f"jit_ms=0 guest_ipc_ms=0 gpu_idle_ms=0")
            if detailed:
                lines.append(f"EDEN_DEV_GPU frame={frame} dispatch_calls={index}")
        return "\n".join(lines)
    output = analyze("irrelevant startup" + "\n" +
                     session(first, [0, 5, 10], [0, 4, 8]) + "\n" +
                     session(second, [10, 5, 0], [0, 4, 8]) + "\n")
    assert len(output) == 2
    assert output[0]["source_sha"] == first and output[1]["source_sha"] == second
    assert output[0]["late50"] == output[1]["late50"] == 12
    assert output[0]["paired_windows"] == output[1]["paired_windows"] == 3
    assert output[0]["cache_wait_late50_pearson"] == 1.0
    assert output[1]["cache_wait_late50_pearson"] == -1.0
    assert output[0]["share_late50_in_those_windows"] == 0.667
    assert output[0]["status"] == "RELEASE_FRAME_PRESSURE_ONLY"
    assert "jit_compile_duration" in output[0]["unmeasured_release_fields"]
    assert analyze(session(first, [0, 1, 2], [0, 0, 0]))[0]["cache_wait_late50_pearson"] is None
    demo = collect(session(first, [0, 5, 10], [0, 4, 8]))[0]
    stable = steady_state(demo, warmup_seconds=5.0, min_late50=3)
    assert stable["paired_windows"] == 2 and stable["burst_windows"] == 2
    assert stable["burst_late50"] == stable["steady_late50"] == 12
    assert stable["bursts"][0]["frame"] == 450
    assert stable["bursts"][0]["cache_wait_ms_multi_thread"] == 10
    assert stable["hud_freshness"] == "NOT_MEASURED"
    incomplete = session(first, [0, 5, 10], [0, 4, 8]).replace(
        "EDEN_FRAME_PRESSURE frame=450 cache_wait_ms=10",
        "EDEN_FRAME_PRESSURE frame=450 detail=not_measured")
    incomplete_report = steady_state(collect(incomplete)[0], 5.0, 3)
    assert incomplete_report["unpaired_windows"] == 1
    assert incomplete_report["paired_windows"] == 1

    assert analyze(session(first, [1, 2, 3], [1, 2, 3], detailed=True))[0]["status"] == "DETAILED_GPU_PRESENT"
    mixed = session(first, [0, 5, 10], [0, 4, 8]) + "\n"
    mixed += "EDEN_VULKAN_FRAME frames=150 seconds=5 fps=30 worst_ms=100 total=150 late50=1 late100=0"
    try:
        analyze(mixed)
    except ValueError as exc:
        assert "Repeated renderer frame" in str(exc)
    else:
        raise AssertionError("Repeated samples must not be silently overwritten")
    print("FC27_RELEASE_SESSION_FORENSICS_PASS mixed_launches=2 missing_dev_is_unknown=1 overlap_guard=1")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("heap_log", nargs="?", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.heap_log is None:
        parser.error("provide an unmodified local heap log or --self-test")
    sessions = analyze(args.heap_log.read_text(encoding="utf-8", errors="replace"))
    if not sessions:
        parser.error("no EDEN_SESSION_SOURCE markers; cannot separate game launches")
    print(json.dumps({"schema": "fc27_release_sessions_v1", "sessions": sessions},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
