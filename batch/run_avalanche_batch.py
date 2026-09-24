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
      [--avalanche-size-limit N] [--mem-mb N] [--slots-per-job N]
      [--output-suffix STR] [--dry-run]

Output: results/root/<baseName>_avalanche.root (or
results/root/<baseName><output-suffix>_avalanche.root if --output-suffix is
given -- needed to run more than one batch against the same mesh, e.g. a
parameter scan, without each one overwriting the last), exactly as a normal serial
export_avalanche_trajectories run would produce (so nothing downstream
needs to change), plus a small "BatchMergeProvenance" tree recording which
parts/seeds/offsets went into it (GitHub issue #9 item 4). Per-job
intermediates (partial ROOT files, bsub logs) are kept under
results/root/.batch_tmp/<baseName>/<run_id>/ for debugging, not deleted
automatically -- run_id is a fresh timestamp every invocation, so a failed
run's leftovers can never get merged into a later run's output (GitHub
issue #9 item 1). The merge only happens if every single job finishes
LSF-status DONE and each part's own RunInfo matches what this run actually
submitted for it (seed/event_offset/n_events, GitHub issue #9 items 2-3);
otherwise no "final" output is written at all, and the run must be
re-submitted (getting its own fresh run_id) after the underlying problem
is fixed.
"""

import argparse
import os
import subprocess
import sys
import time

import numpy as np
import uproot

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bsub_utils

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MACRO_BINARY = os.path.join(REPO_ROOT, "macros", "build", "export_avalanche_trajectories")
RESULTS_ROOT_DIR = os.path.join(REPO_ROOT, "results", "root")
DEFAULT_QUEUE = "s"  # confirmed Open:Active on this cluster via `bqueues`, 2026-09-24


def _read_run_info(root_path: str) -> dict[str, str]:
    """The (key, value) pairs from a part file's own "RunInfoTrajectories" tree, as a
    plain dict (see macros/run_info.hh) -- used to cross-check that a part
    file actually matches what *this* run expected of it (GitHub issue #9
    item 3), not just that some file happens to exist at that path."""
    with uproot.open(root_path) as f:
        if "RunInfoTrajectories" not in f:
            return {}
        arr = f["RunInfoTrajectories"].arrays(["key", "value"], library="np")
    return dict(zip(arr["key"], arr["value"]))


def _validate_part(job: dict) -> list[str]:
    """Problems found cross-checking a part's own RunInfo against what this
    run actually submitted for it -- empty list means it's consistent.
    Missing RunInfo entirely (an older export_avalanche_trajectories build)
    is reported as a problem too, not silently skipped, since GitHub issue
    #9 wants this checked whenever it's possible to check."""
    run_info = _read_run_info(job["part_root_path"])
    if not run_info:
        return ["no RunInfo tree in part file -- cannot verify it matches this run "
                "(rebuild macros/export_avalanche_trajectories if this is unexpected)"]
    problems = []
    expected = {
        "rng_seed": str(job["seed"]),
        "event_offset": str(job["offset"]),
        "n_events": str(job["n_events"]),
        "avalanche_size_limit": str(job["avalanche_size_limit"]),
        "geometry_type": job["geometry_type"],
    }
    for key, want in expected.items():
        got = run_info.get(key)
        if got != want:
            problems.append(f"RunInfo[{key!r}] = {got!r}, expected {want!r}")
    return problems


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
        "--mem-mb", type=int, default=None,
        help="Explicit bsub memory request in MB (both -M and -R rusage[mem=...]). "
             "Every queue on this cluster has a hard per-slot MEMLIMIT of 4GB "
             "(confirmed 2026-09-24, bqueues -l) that bsub itself refuses to exceed "
             "via -M at the default 1 slot -- use --slots-per-job instead for a job "
             "that needs more than 4GB; this is for a value under that per-slot cap.",
    )
    parser.add_argument(
        "--slots-per-job", type=int, default=1,
        help="bsub -n <N> per job (all on one host, -R span[hosts=1]) -- on this "
             "cluster the per-job memory budget scales with slot count (N x the "
             "queue's per-slot MEMLIMIT, 4GB), so this is how to get a large-mesh "
             "avalanche job enough headroom. A triple_gem_field_v1.15x_n9 (9.6M-node) "
             "job needs ~5.6GB RSS (measured locally, 2026-09-24) -- try 2 first, "
             "raise to 3/4/... if a job still gets TERM_MEMLIMIT-killed. Default 1 "
             "(no change from before this option existed).",
    )
    parser.add_argument(
        "--output-suffix", default="",
        help="Appended to the final output's base name: "
             "results/root/<baseName><suffix>_avalanche.root instead of the plain "
             "<baseName>_avalanche.root. Needed to run more than one batch against the same "
             "mesh (e.g. a parameter scan -- different avalanche_size_limit/collision_steps "
             "values on the same mesh) without each run overwriting the previous one's final "
             "output; per-job intermediates already avoid this via run_id, but the final "
             "merged file's name is otherwise always exactly <baseName>_avalanche.root.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be submitted/merged; never call bsub or touch the LSF queue.",
    )
    args = parser.parse_args()

    # Explicit, loud validation up front (GitHub issue #9) -- argparse's
    # type=int/float already rejects non-numeric input, but not <= 0, which
    # would otherwise surface later as a confusing failure deep in
    # _split_events or bsub itself.
    if args.njobs <= 0:
        parser.error(f"--njobs must be > 0, got {args.njobs}")
    if args.n_events_total <= 0:
        parser.error(f"n_events_total must be > 0, got {args.n_events_total}")

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

    # Run-scoped part directory, not a bare .batch_tmp/<baseName>/ reused
    # across every invocation (GitHub issue #9): reusing the same partXXX/
    # paths meant a failed job's *previous* run's ROOT file could still be
    # sitting there when this run's merge step only checks file existence,
    # not which run actually produced it -- confirmed happening for real
    # 2026-09-25 (triple_gem_field_v1.15x_n9: 6/10 jobs EXITed but the
    # merge went ahead anyway using whatever files existed, some left over
    # from an earlier failed attempt; the resulting file was quarantined,
    # not used). A fresh timestamped subdirectory per invocation means a
    # failed run can never contaminate a later one, and nothing here is
    # ever silently reused across runs.
    run_id = time.strftime("%Y%m%dT%H%M%S")
    batch_tmp_dir = os.path.join(RESULTS_ROOT_DIR, ".batch_tmp", base_name, run_id)
    if not args.dry_run:
        os.makedirs(batch_tmp_dir, exist_ok=True)
    print(f"run_id={run_id} (part directory: {batch_tmp_dir})")

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
        if not args.dry_run:
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
            "avalanche_size_limit": args.avalanche_size_limit, "geometry_type": base_name,
        })

    print(f"base_name={base_name}, {len(jobs)} jobs covering {args.n_events_total} events total:")
    for j in jobs:
        print(f"  job {j['index']:3d}: {j['n_events']:4d} events, offset={j['offset']:5d}, "
              f"seed={j['seed']} -> {j['part_root_path']}")

    if args.dry_run:
        print("\n--dry-run: not calling bsub. Commands that would be submitted:")
        resource_parts = []
        n_flag = ""
        if args.slots_per_job > 1:
            n_flag = f"-n {args.slots_per_job} "
            resource_parts.append("span[hosts=1]")
        if args.mem_mb:
            resource_parts.append(f"rusage[mem={args.mem_mb}]")
        mem_flag = f"-M {args.mem_mb} " if args.mem_mb else ""
        r_flag = f"-R \"{' '.join(resource_parts)}\" " if resource_parts else ""
        for j in jobs:
            print(f"  bsub -q {args.queue} {n_flag}{mem_flag}{r_flag}-o {j['log_path']} "
                  f"bash -lc \"{j['command']}\"")
        print("\n--dry-run: stopping before submission/merge.")
        return

    print(f"\nSubmitting {len(jobs)} jobs to queue '{args.queue}' ...")
    for j in jobs:
        j["job_id"] = bsub_utils.submit(
            j["command"], queue=args.queue, log_path=j["log_path"],
            job_name=f"{base_name}_avalanche_part{j['index']:03d}",
            mem_mb=args.mem_mb, n_slots=args.slots_per_job,
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

    # Strict DONE-only merge condition (GitHub issue #9 item 2): a job
    # that's EXIT, or UNKNOWN (aged out of `bjobs -a` before we could
    # confirm which -- ambiguous, not "probably fine"), blocks the merge
    # entirely. A merge that silently went ahead using whatever part files
    # happened to exist, regardless of job status, is exactly how a stale
    # or truncated part got folded into a "successful" output for real on
    # 2026-09-25 -- no "final" file gets written at all now unless every
    # single part is confirmed DONE.
    not_done = [j for j in jobs if final_statuses.get(j["job_id"]) != "DONE"]
    if not_done:
        print(f"\nERROR: {len(not_done)}/{len(jobs)} job(s) did not finish DONE -- refusing to "
              f"merge (no partial/best-effort output is written):")
        for j in not_done:
            status = final_statuses.get(j["job_id"], "UNKNOWN")
            print(f"  job {j['index']:3d}: status={status} (see {j['log_path']})")
        print(f"\nPart directory kept at {batch_tmp_dir} for inspection. Fix the underlying "
              f"issue (see the logs above) and re-run the whole batch -- it gets a fresh "
              f"run_id, so this won't collide with the failed attempt.")
        sys.exit(1)

    missing = [j for j in jobs if not os.path.isfile(j["part_root_path"])]
    if missing:
        print(f"\nERROR: {len(missing)} part file(s) missing despite DONE status, cannot merge:")
        for j in missing:
            print(f"  job {j['index']:3d}: expected {j['part_root_path']} (see {j['log_path']})")
        sys.exit(1)

    # Cross-check each part's own RunInfo against what this run actually
    # submitted for it (GitHub issue #9 item 3) -- catches a part file that
    # exists and is DONE but somehow doesn't match (e.g. a macro bug, or a
    # future change to this script that breaks the seed/offset bookkeeping)
    # before it gets folded into the merged output.
    inconsistent = {}
    for j in jobs:
        problems = _validate_part(j)
        if problems:
            inconsistent[j["index"]] = problems
    if inconsistent:
        print(f"\nERROR: {len(inconsistent)} part file(s) failed RunInfo consistency checks, "
              f"cannot merge:")
        for idx, problems in inconsistent.items():
            print(f"  job {idx:3d}: {'; '.join(problems)}")
        sys.exit(1)

    final_path = os.path.join(RESULTS_ROOT_DIR, f"{base_name}{args.output_suffix}_avalanche.root")
    part_paths = [j["part_root_path"] for j in jobs]
    print(f"\nAll {len(part_paths)} parts DONE and RunInfo-consistent. "
          f"Merging into {final_path} ...")
    subprocess.run(["hadd", "-f", final_path] + part_paths, check=True)

    # Provenance (GitHub issue #9 item 4): which parts, from which run,
    # under which batch parameters, actually went into this merged file --
    # appended as its own tree rather than folded into "RunInfoTrajectories" so it
    # doesn't collide with (or get overwritten by) the per-part RunInfo
    # trees export_avalanche_trajectories itself already writes there.
    with uproot.update(final_path) as f:
        f["BatchMergeProvenance"] = {
            "part_index": np.array([j["index"] for j in jobs]),
            "seed": np.array([j["seed"] for j in jobs]),
            "event_offset": np.array([j["offset"] for j in jobs]),
            "n_events": np.array([j["n_events"] for j in jobs]),
        }
    print(f"Wrote {final_path} (run_id={run_id}, per-job intermediates kept under {batch_tmp_dir})")


if __name__ == "__main__":
    main()
