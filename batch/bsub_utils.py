"""Minimal LSF (bsub/bjobs) submission + polling helpers for parallelizing
this project's embarrassingly-parallel avalanche runs across KEKCC batch
jobs (see GitHub issue #2 discussion, 2026-09-24, and
docs/pipeline_gotchas.md).

Deliberately much smaller than a general-purpose run manager: this project
only ever needs "submit N independent shell commands, wait for all of them,
then do something with the outputs" -- not staging, DST chaining, or job
priorities. Modeled loosely on the batch-status-polling idea in
~/analyzer/JPARC2025E72/runmanager/module/bjobmanager.py (poll `bjobs -a`
once and look up many job IDs in the cached result, instead of one `bjobs
<id>` subprocess per job -- the latter doesn't scale past a handful of
jobs), but without that framework's DST/analyzer-specific run-list schema,
HSM staging, or logging config, none of which apply here.

IMPORTANT: submitting a real bsub job is a batch-job submission -- per this
project's own global safety rules, that should only happen when the user
explicitly asks for it at that moment, not on this tool's own initiative.
Callers (e.g. run_avalanche_batch.py) should support --dry-run and default
to it, or otherwise make submission an explicit, deliberate step.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import time

_BSUB_JOB_ID_RE = re.compile(r"Job <(\d+)> is submitted")
# Terminal bjobs states -- once a job reaches one of these it will not
# change again (successfully finished or failed/killed).
_TERMINAL_STATES = {"DONE", "EXIT"}

# LSF writes this header line to a job's -o log as soon as the job reaches
# a terminal state, e.g. "Subject: Job 123: <name> in cluster <x> Done".
_LSF_LOG_STATUS_RE = re.compile(r"in cluster <[^>]*> (Done|Exit)")


def status_from_log(log_path: str) -> str | None:
    """Final status ("DONE"/"EXIT") read from a job's own LSF -o log
    header, or None if the header isn't there yet (job not actually
    finished) or the log doesn't exist. Unlike `bjobs -a`, a local log file
    never ages out -- this is the fallback for BJobStatusCache.get_status
    when a job has disappeared from `bjobs -a`'s retained history (real,
    observed 2026-09-25: a 50-job batch against the 9x9 mesh had 22/50
    jobs finish successfully -- confirmed by this exact log header -- but
    fall out of `bjobs -a` before wait_all's polling loop noticed, because
    the loop keeps running for as long as the *slowest* job in the batch
    takes, well past bjobs -a's retention window for the fast ones. Before
    this fix, those 22 genuinely-successful jobs were reported "UNKNOWN"
    and the batch's strict DONE-only merge gate (GitHub issue #9 item 2)
    correctly refused to merge -- correctly conservative, but needlessly
    so, since the data was fine).
    """
    try:
        with open(log_path) as f:
            head = f.read(2000)
    except OSError:
        return None
    match = _LSF_LOG_STATUS_RE.search(head)
    if match is None:
        return None
    return "DONE" if match.group(1) == "Done" else "EXIT"


def build_login_shell_command(shell_command: str) -> list[str]:
    """Wrap a shell command string to run inside a fresh login shell
    (`bash -lc`), so it goes through ~/.bashrc's LSF-batch-job branch
    (`$LSB_JOBID` set -> skip the node-local envfs mount, fall back to the
    canonical ~/local/root/6.40.04 etc. paths -- see
    ~/local/envfs_README.md) rather than depending on whatever environment
    happened to be inherited from the submitting shell, which may reference
    a node-local /tmp mount that doesn't exist on the compute node the job
    actually lands on.
    """
    return ["bash", "-lc", shell_command]


def submit(
    shell_command: str, queue: str, log_path: str, job_name: str | None = None,
    mem_mb: int | None = None, n_slots: int | None = None,
) -> int:
    """Submit shell_command (a full shell command string, e.g.
    "cd .../macros/build && ./export_avalanche_trajectories ...") via
    `bsub -q <queue> -o <log_path>`, running it inside a login shell (see
    build_login_shell_command). Returns the parsed LSF job id.

    Every queue on this cluster was confirmed 2026-09-24 to have a hard
    per-slot MEMLIMIT of 4GB (`bqueues -l <queue>`) that `-M` cannot exceed
    at n=1 -- bsub itself rejects a too-high -M with "MEMLIMIT: Cannot
    exceed queue's hard limit(s)". A triple_gem_field_v1.15x_n9 (9.6M-node)
    avalanche job needs ~5.6GB RSS (measured locally), already over that.

    n_slots: request this many job slots (`-n <n_slots> -R "span[hosts=1]"`,
    all on one host since this is a single-process job, not real MPI/thread
    parallelism) -- on this cluster the per-job memory budget scales with
    slot count (n_slots x the queue's per-slot MEMLIMIT), so this is the
    actual way to get a large-mesh job enough headroom, not mem_mb/-M
    (still supported below for a value under the per-slot cap, but mostly
    superseded by this for anything that needs more than 4GB).

    mem_mb: explicit memory request in MB, passed as both `-M` (hard limit)
    and `-R "rusage[mem=...]"` (scheduler reservation).

    Raises RuntimeError if bsub's stdout doesn't match the expected
    "Job <NNN> is submitted to queue <...>" response.
    """
    cmd = ["bsub", "-q", queue, "-o", log_path]
    if job_name:
        cmd += ["-J", job_name]
    if n_slots is not None and n_slots > 1:
        cmd += ["-n", str(n_slots)]
    # Only one -R is meaningful to bsub -- combine span/rusage into one
    # resource-requirement string instead of passing -R twice (the second
    # would silently override the first, dropping span[hosts=1]).
    resource_parts = []
    if n_slots is not None and n_slots > 1:
        resource_parts.append("span[hosts=1]")
    if mem_mb is not None:
        resource_parts.append(f"rusage[mem={mem_mb}]")
        cmd += ["-M", str(mem_mb)]
    if resource_parts:
        cmd += ["-R", " ".join(resource_parts)]
    cmd += build_login_shell_command(shell_command)
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"bsub failed (rc={proc.returncode}): {proc.stderr.strip()}")
    match = _BSUB_JOB_ID_RE.search(proc.stdout)
    if not match:
        raise RuntimeError(f"Could not parse job id from bsub output: {proc.stdout!r}")
    return int(match.group(1))


class BJobStatusCache:
    """Caches one `bjobs -a` snapshot at a time instead of shelling out
    per job id -- important once there are more than a handful of jobs.
    """

    def __init__(self) -> None:
        self._status: dict[int, str] = {}

    def refresh(self) -> None:
        proc = subprocess.run(
            shlex.split("bjobs -a"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        self._status = {}
        for line in proc.stdout.splitlines():
            columns = line.split()
            if len(columns) < 4 or not columns[0].isdigit():
                continue  # header line or malformed
            self._status[int(columns[0])] = columns[2]

    def get_status(self, job_id: int, log_path: str | None = None) -> str:
        """Status string (PEND/RUN/DONE/EXIT/...). If bjobs -a no longer
        reports this job at all (aged out of LSF's recently-finished-job
        history) and log_path is given, falls back to that job's own LSF
        log header (see status_from_log) to resolve it to DONE/EXIT
        instead of leaving it as an ambiguous 'UNKNOWN' -- see
        status_from_log's docstring for why this fallback exists. Only
        genuinely still-running-or-truly-untraceable jobs (no log header
        yet, or no log_path given) come back as 'UNKNOWN'.
        """
        status = self._status.get(job_id)
        if status is not None:
            return status
        if log_path is not None:
            log_status = status_from_log(log_path)
            if log_status is not None:
                return log_status
        return "UNKNOWN"

    def wait_all(
        self,
        job_ids: list[int],
        poll_interval_s: float = 15.0,
        on_update=None,
        log_paths: dict[int, str] | None = None,
    ) -> dict[int, str]:
        """Block until every job in job_ids is DONE, EXIT, or UNKNOWN
        (aged out of bjobs -a's history AND its own log has no terminal
        header yet -- treated as finished, since there is nothing left to
        poll for). Returns the final {job_id: status} dict. Calls
        on_update(status_dict) once per poll cycle, if given, for progress
        reporting. log_paths, if given, maps job_id -> its LSF -o log path,
        used to resolve jobs that have aged out of bjobs -a (see
        get_status) instead of leaving them as an ambiguous 'UNKNOWN'.
        """
        while True:
            self.refresh()
            statuses = {
                jid: self.get_status(jid, log_paths.get(jid) if log_paths else None)
                for jid in job_ids
            }
            if on_update is not None:
                on_update(statuses)
            if all(s in _TERMINAL_STATES or s == "UNKNOWN" for s in statuses.values()):
                return statuses
            time.sleep(poll_interval_s)

    def kill(self, job_id: int) -> None:
        subprocess.run(
            shlex.split(f"bkill {job_id}"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
