"""Split a macros/export_avalanche_trajectories run across several KEKCC
LSF (bsub) jobs and merge the results back into the usual
results/root/<baseName>_avalanche.root -- for the higher-event-count runs
this project's investigation has repeatedly needed (see docs/debugging_notes.md,
"統計を増やす"), which can otherwise take many minutes to hours run serially.

Avalanche simulation is embarrassingly parallel across primary events (no
shared state), so this is a safe, simple way to use KEKCC's batch farm
instead of one long serial job. Each job gets a distinct, non-overlapping
slice of the total event count (via export_avalanche_trajectories'
eventOffset argument, added 2026-09-24 alongside this script) so the
per-job output files can be hadd'd together afterward without colliding
(event,track) keys -- every downstream analysis script in this project
treats (event,track) as a globally unique identifier.

IMPORTANT: this script only *submits real bsub jobs* when run without
--dry-run. Per this project's global safety rules, batch job submission is
hands-off by default -- only actually submit (i.e. run this without
--dry-run) when the user has explicitly asked for it at that time. Always
sanity-check with --dry-run first, which prints exactly what would be
submitted/merged without touching bsub or the LSF queue at all.

Usage:
    python3 run_avalanche_batch.py <mesh/result dir> <.gas file> <n_events_total>
      <zSensorMin> <zSensorMax> <zInjection> <xHalfCm> <yHalfCm>
      [e0_eV] [injectionRadiusCm] [collisionSteps]
      [--njobs N] [--queue NAME] [--poll-interval SEC]
      [--avalanche-size-limit N] [--dry-run]

Output: results/root/<baseName>_avalanche.root, exactly as a normal serial
export_avalanche_trajectories run would produce (so nothing downstream
needs to change). Per-job intermediates (partial ROOT files, bsub logs)
are kept under results/root/.batch_tmp/<baseName>/ for debugging, not
deleted automatically.
"""

import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bsub_utils

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MACRO_BINARY = os.path.join(REPO_ROOT, "macros", "build", "export_avalanche_trajectories")
RESULTS_ROOT_DIR = os.path.join(REPO_ROOT, "results", "root")
DEFAULT_QUEUE = "s"  # confirmed Open:Active on this cluster via `bqueues`, 2026-09-24


def _split_events(n_events_total: int, n_jobs: int) -> list[tuple[int, int]]:
    """[(n_events_this_job, event_offset), ...], as evenly split as
    possible (earlier jobs get one extra event if it doesn't divide
    evenly), skipping any chunk that would end up with 0 events."""
    base, remainder = divmod(n_events_total, n_jobs)
    chunks = []
    offset = 0
    for i in range(n_jobs):
        n = base + (1 if i < remainder else 0)
        if n > 0:
            chunks.append((n, offset))
        offset += n
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mesh_dir")
    parser.add_argument("gas_file")
    parser.add_argument("n_events_total", type=int)
    parser.add_argument("z_sensor_min", type=float)
    parser.add_argument("z_sensor_max", type=float)
    parser.add_argument("z_injection", type=float)
    parser.add_argument("x_half_cm", type=float)
    parser.add_argument("y_half_cm", type=float)
    parser.add_argument("e0_ev", type=float, nargs="?", default=0.1)
    parser.add_argument("injection_radius_cm", type=float, nargs="?", default=0.0005)
    parser.add_argument("collision_steps", type=int, nargs="?", default=100)
    parser.add_argument("--njobs", type=int, default=10)
    parser.add_argument("--queue", default=DEFAULT_QUEUE)
    parser.add_argument("--poll-interval", type=float, default=15.0)
    parser.add_argument(
        "--base-seed", type=int, default=None,
        help="Explicit RNG base seed; job i uses (base_seed + i). Defaults to a "
             "time-derived value, printed below, if not given. Each job's actual "
             "seed is passed to export_avalanche_trajectories' seed argument -- "
             "see GitHub issue #5 item 4 and that macro's own comment for why this "
             "is needed instead of relying on its per-process auto-seeding.",
    )
    parser.add_argument(
        "--avalanche-size-limit", type=int, default=2000,
        help="export_avalanche_trajectories' EnableAvalancheSizeLimit() argument "
             "(default 2000, matching that macro's own default). A capped event's "
             "still-unprocessed electrons are dropped with no trajectory recorded at "
             "all, biasing measured transmission fractions downward -- found to be "
             "hit routinely once Penning transfer was enabled (GitHub issue #7 item "
             "4); raise this for a run where that bias matters.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be submitted/merged; never call bsub or touch the LSF queue.",
    )
    args = parser.parse_args()

    if not os.path.isfile(MACRO_BINARY):
        parser.error(f"Binary not found: {MACRO_BINARY} (build it first, see docs/reference.md)")

    # Resolve to absolute paths up front: the submitted command `cd`s into
    # macros/build first, so a path given relative to wherever this script
    # was invoked from would otherwise resolve against the wrong directory.
    args.mesh_dir = os.path.abspath(args.mesh_dir)
    args.gas_file = os.path.abspath(args.gas_file)

    base_name = os.path.basename(os.path.normpath(args.mesh_dir))
    chunks = _split_events(args.n_events_total, args.njobs)
    if not chunks:
        parser.error("n_events_total is too small to split into any non-empty chunk")

    batch_tmp_dir = os.path.join(RESULTS_ROOT_DIR, ".batch_tmp", base_name)
    os.makedirs(batch_tmp_dir, exist_ok=True)

    # Each job's own explicit seed, base_seed + job index -- NOT relying on
    # export_avalanche_trajectories' per-process auto-seeding, even though
    # that was verified independent across jobs (2026-09-24): explicit
    # per-job seeds make a batch run reproducible (rerun with the same
    # --base-seed to get bit-identical results) and don't depend on that
    # auto-seeding behavior continuing to hold.
    base_seed = args.base_seed if args.base_seed is not None else int(time.time())
    print(f"base_seed={base_seed} (job i uses seed {base_seed}+i)")

    jobs = []  # (job_id_or_None, part_out_dir, part_root_path, log_path)
    for i, (n_events, offset) in enumerate(chunks):
        part_dir = os.path.join(batch_tmp_dir, f"part{i:03d}")
        os.makedirs(part_dir, exist_ok=True)
        part_root_path = os.path.join(part_dir, f"{base_name}_avalanche.root")
        log_path = os.path.join(part_dir, "bsub.log")
        seed = base_seed + i
        cmd = (
            f"cd {os.path.dirname(MACRO_BINARY)} && "
            f"./export_avalanche_trajectories "
            f"{args.mesh_dir} {args.gas_file} {n_events} "
            f"{args.z_sensor_min} {args.z_sensor_max} {args.z_injection} "
            f"{args.x_half_cm} {args.y_half_cm} {args.e0_ev} {args.injection_radius_cm} "
            f"{part_dir} {args.collision_steps} {offset} {seed} {args.avalanche_size_limit}"
        )
        jobs.append({
            "index": i, "n_events": n_events, "offset": offset, "seed": seed,
            "part_dir": part_dir, "part_root_path": part_root_path,
            "log_path": log_path, "command": cmd, "job_id": None,
        })

    print(f"base_name={base_name}, {len(jobs)} jobs covering {args.n_events_total} events total:")
    for j in jobs:
        print(f"  job {j['index']:3d}: {j['n_events']:4d} events, offset={j['offset']:5d}, "
              f"seed={j['seed']} -> {j['part_root_path']}")

    if args.dry_run:
        print("\n--dry-run: not calling bsub. Commands that would be submitted:")
        for j in jobs:
            print(f"  bsub -q {args.queue} -o {j['log_path']} bash -lc \"{j['command']}\"")
        print("\n--dry-run: stopping before submission/merge.")
        return

    print(f"\nSubmitting {len(jobs)} jobs to queue '{args.queue}' ...")
    for j in jobs:
        j["job_id"] = bsub_utils.submit(
            j["command"], queue=args.queue, log_path=j["log_path"],
            job_name=f"{base_name}_avalanche_part{j['index']:03d}",
        )
        print(f"  job {j['index']:3d}: submitted as LSF job {j['job_id']}")

    cache = bsub_utils.BJobStatusCache()
    job_ids = [j["job_id"] for j in jobs]

    def _report(statuses: dict[int, str]) -> None:
        counts: dict[str, int] = {}
        for s in statuses.values():
            counts[s] = counts.get(s, 0) + 1
        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        print(f"[{time.strftime('%H:%M:%S')}] {summary}")

    print(f"\nPolling every {args.poll_interval}s until all jobs finish ...")
    final_statuses = cache.wait_all(job_ids, poll_interval_s=args.poll_interval, on_update=_report)

    failed = [j for j in jobs if final_statuses.get(j["job_id"]) == "EXIT"]
    if failed:
        print(f"\nWARNING: {len(failed)} job(s) reported EXIT (check their logs):")
        for j in failed:
            print(f"  job {j['index']:3d}: {j['log_path']}")

    missing = [j for j in jobs if not os.path.isfile(j["part_root_path"])]
    if missing:
        print(f"\nERROR: {len(missing)} part file(s) missing, cannot merge:")
        for j in missing:
            print(f"  job {j['index']:3d}: expected {j['part_root_path']} (see {j['log_path']})")
        sys.exit(1)

    final_path = os.path.join(RESULTS_ROOT_DIR, f"{base_name}_avalanche.root")
    part_paths = [j["part_root_path"] for j in jobs]
    print(f"\nMerging {len(part_paths)} part files into {final_path} ...")
    subprocess.run(["hadd", "-f", final_path] + part_paths, check=True)
    print(f"Wrote {final_path} (per-job intermediates kept under {batch_tmp_dir})")


if __name__ == "__main__":
    main()
