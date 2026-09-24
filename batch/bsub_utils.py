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
    mem_mb: int | None = None,
) -> int:
    """Submit shell_command (a full shell command string, e.g.
    "cd .../macros/build && ./export_avalanche_trajectories ...") via
    `bsub -q <queue> -o <log_path>`, running it inside a login shell (see
    build_login_shell_command). Returns the parsed LSF job id.

    mem_mb: explicit memory request in MB, passed as both `-M` (hard limit)
    and `-R "rusage[mem=...]"` (scheduler reservation). Without this, the
    queue's own default limit applies -- confirmed 2026-09-24 to be 4000MB
    for queue "s" on this cluster (not something this script ever set), which
    is nowhere near enough for a large/finely-tiled mesh: a
    triple_gem_field_v1.15x_n9 (9.6M-node) avalanche job was killed
    (TERM_MEMLIMIT, exit 137) hitting exactly that 4096MB ceiling. Pass a
    generous mem_mb for any mesh past roughly n_cells=7 (see
    docs/debugging_notes.md).

    Raises RuntimeError if bsub's stdout doesn't match the expected
    "Job <NNN> is submitted to queue <...>" response.
    """
    cmd = ["bsub", "-q", queue, "-o", log_path]
    if job_name:
        cmd += ["-J", job_name]
    if mem_mb is not None:
        cmd += ["-M", str(mem_mb), "-R", f"rusage[mem={mem_mb}]"]
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

    def get_status(self, job_id: int) -> str:
        """Status string (PEND/RUN/DONE/EXIT/...), or 'UNKNOWN' if bjobs -a
        no longer reports this job at all (e.g. it aged out of LSF's
        recently-finished-job history) -- callers should treat 'UNKNOWN'
        for a job they know they submitted as "probably finished", not as
        "still pending".
        """
        return self._status.get(job_id, "UNKNOWN")

    def wait_all(
        self,
        job_ids: list[int],
        poll_interval_s: float = 15.0,
        on_update=None,
    ) -> dict[int, str]:
        """Block until every job in job_ids is DONE, EXIT, or UNKNOWN
        (aged out of bjobs -a's history -- treated as finished). Returns
        the final {job_id: status} dict. Calls on_update(status_dict) once
        per poll cycle, if given, for progress reporting.
        """
        while True:
            self.refresh()
            statuses = {jid: self.get_status(jid) for jid in job_ids}
            if on_update is not None:
                on_update(statuses)
            if all(s in _TERMINAL_STATES or s == "UNKNOWN" for s in statuses.values()):
                return statuses
            time.sleep(poll_interval_s)

    def kill(self, job_id: int) -> None:
        subprocess.run(
            shlex.split(f"bkill {job_id}"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
