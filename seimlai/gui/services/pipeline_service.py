"""Pipeline execution service for SeiMLAI GUI.

Orchestrates running seismic workflow steps in a dedicated background thread,
captures stdout/stderr, extracts tqdm progress, and notifies listeners.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import io
import codecs
import os
import pickle
import signal
import subprocess
import re
import sys
import threading
import time
from typing import Any, Callable

import matplotlib
matplotlib.use("Agg")

from seimlai.context import build_context, ensure_initial_directories
from seimlai.main import STEPS, OPTIONAL_STEPS, LEGACY_STEPS, Step, select_steps


@dataclass
class StepState:
    """State tracking for a single pipeline step."""

    id: str
    command: str
    description: str
    status: str = "pending"  # pending, running, done, error, skipped
    progress: float = 0.0  # 0.0 to 1.0
    elapsed: float = 0.0
    error_message: str | None = None


class StreamCapture(io.TextIOBase):
    """Custom stream to capture stdout/stderr in real-time and extract progress."""

    def __init__(self, on_output: Callable[[str], None], original_stream: io.TextIOBase):
        super().__init__()
        self._on_output = on_output
        self._original_stream = original_stream
        self._buffer = ""
        self._lock = threading.Lock()

    def write(self, s: str) -> int:
        if not s:
            return 0

        # Always mirror to original terminal stdout
        try:
            self._original_stream.write(s)
            self._original_stream.flush()
        except Exception:
            pass

        with self._lock:
            # Handle carriage returns from tqdm or newlines
            self._buffer += s
            if "\n" in self._buffer or "\r" in self._buffer:
                # Split keeping delimiters or process line by line
                lines = re.split(r"[\r\n]+", self._buffer)
                for line in lines[:-1]:
                    if line.strip():
                        self._on_output(line.strip())
                self._buffer = lines[-1]
            if self._buffer and not self._buffer.strip("."):
                self._on_output(self._buffer)
                self._buffer = ""

        return len(s)

    def flush(self) -> None:
        try:
            self._original_stream.flush()
        except Exception:
            pass
        with self._lock:
            if self._buffer.strip():
                self._on_output(self._buffer.strip())
                self._buffer = ""


class PipelineService:
    """Service to execute SeiMLAI workflow asynchronously and report live events."""

    def __init__(self):
        self._lock = threading.Lock()
        self.is_running: bool = False
        self._stop_requested: bool = False
        self._process: subprocess.Popen | None = None
        self.current_step_id: str | None = None
        self.logs: list[str] = []
        self.max_log_lines: int = 2000

        # Step states
        self.step_states: dict[str, StepState] = {}
        self._init_step_states()

        # Callbacks
        self._log_listeners: list[Callable[[str], None]] = []
        self._step_listeners: list[Callable[[str, StepState], None]] = []
        self._finished_listeners: list[Callable[[bool, str], None]] = []

    def _init_step_states(self) -> None:
        """Initialize all default steps in pending state."""
        self.step_states.clear()
        for s in STEPS:
            self.step_states[s.id] = StepState(
                id=s.id,
                command=s.command,
                description=s.description,
                status="pending",
                progress=0.0,
                elapsed=0.0,
            )

    def add_log_listener(self, cb: Callable[[str], None]) -> None:
        self._log_listeners.append(cb)

    def add_step_listener(self, cb: Callable[[str, StepState], None]) -> None:
        self._step_listeners.append(cb)

    def add_finished_listener(self, cb: Callable[[bool, str], None]) -> None:
        self._finished_listeners.append(cb)

    def _notify_log(self, line: str) -> None:
        self.logs.append(line)
        if len(self.logs) > self.max_log_lines:
            self.logs.pop(0)

        # Parse tqdm progress if inside an active step
        self._extract_progress_from_log(line)

        for cb in self._log_listeners:
            try:
                cb(line)
            except Exception:
                pass

    def _notify_step(self, step_id: str) -> None:
        state = self.step_states.get(step_id)
        if not state:
            return
        for cb in self._step_listeners:
            try:
                cb(step_id, state)
            except Exception:
                pass

    def _notify_finished(self, success: bool, message: str) -> None:
        for cb in self._finished_listeners:
            try:
                cb(success, message)
            except Exception:
                pass

    def _extract_progress_from_log(self, line: str) -> None:
        """Extract percentage from tqdm format lines."""
        if not self.current_step_id or self.current_step_id not in self.step_states:
            return

        # Pattern: " 45%|" or "100%|"
        match_pct = re.search(r"(\d{1,3})%\|", line)
        if match_pct:
            pct = min(100, max(0, int(match_pct.group(1)))) / 100.0
            st = self.step_states[self.current_step_id]
            st.progress = pct
            self._notify_step(self.current_step_id)
            return

        # Pattern: " 25/100 ["
        match_counts = re.search(r"(\d+)/(\d+)\s+\[", line)
        if match_counts:
            cur, tot = int(match_counts.group(1)), int(match_counts.group(2))
            if tot > 0:
                pct = min(1.0, cur / tot)
                st = self.step_states[self.current_step_id]
                st.progress = pct
                self._notify_step(self.current_step_id)

    def request_stop(self) -> None:
        """Interrupt the active worker process and its descendants."""
        with self._lock:
            if not self.is_running or self._stop_requested:
                return
            self._stop_requested = True
            process = self._process
        self._notify_log("[WARN] Stop requested by user.")
        if process is not None:
            threading.Thread(target=self._interrupt_process, args=(process,), daemon=True).start()

    def _interrupt_process(self, process: subprocess.Popen) -> None:
        for sig, delay in ((signal.SIGINT, 5), (signal.SIGTERM, 3), (signal.SIGKILL, 0)):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                return
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline:
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    return
                time.sleep(0.1)

    def _run_module(self, module: str, ctx: Any) -> None:
        script = (
            "import importlib, pickle, sys; "
            "ctx = pickle.load(sys.stdin.buffer); "
            "importlib.import_module(sys.argv[1]).run(ctx)"
        )
        payload = pickle.dumps(ctx)
        with self._lock:
            if self._stop_requested:
                raise InterruptedError("Stopped by user")
            process = subprocess.Popen(
                [sys.executable, "-u", "-c", script, module],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                start_new_session=True,
                env={**os.environ, "MPLBACKEND": "Agg", "PYTHONUNBUFFERED": "1"},
            )
            self._process = process
        try:
            process.stdin.write(payload)
            process.stdin.close()
            capture = StreamCapture(self._notify_log, sys.__stdout__)
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            while chunk := os.read(process.stdout.fileno(), 4096):
                capture.write(decoder.decode(chunk))
            capture.write(decoder.decode(b"", final=True))
            capture.flush()
            code = process.wait()
            if self._stop_requested:
                raise InterruptedError("Stopped by user")
            if code:
                raise RuntimeError(f"{module} exited with code {code}")
        finally:
            process.stdout.close()
            with self._lock:
                if self._process is process:
                    self._process = None

    def run_workflow_async(
        self,
        config_path: str,
        from_step: str | None = None,
        only_steps: list[str] | None = None,
        phase_label: str = "workflow",
    ) -> bool:
        """Start workflow in a background thread."""
        with self._lock:
            if self.is_running:
                return False
            self.is_running = True
            self._stop_requested = False

        worker = threading.Thread(
            target=self._run_workflow_worker,
            args=(config_path, from_step, only_steps, phase_label),
            daemon=True,
        )
        worker.start()
        return True

    def run_optional_command_async(self, config_path: str, command: str) -> bool:
        """Start an optional command (e.g. plot-catalog, gamma-analysis) in background thread."""
        with self._lock:
            if self.is_running:
                return False
            self.is_running = True
            self._stop_requested = False

        worker = threading.Thread(
            target=self._run_optional_worker,
            args=(config_path, command),
            daemon=True,
        )
        worker.start()
        return True

    def _run_workflow_worker(
        self,
        config_path: str,
        from_step: str | None,
        only_steps: list[str] | None,
        phase_label: str,
    ) -> None:
        success = False
        error_msg = ""

        try:
            self._notify_log(f"=== Initializing context from {config_path} ===")
            ctx = build_context(config_path)
            ensure_initial_directories(ctx)

            # Determine steps to run
            steps_to_run = select_steps(STEPS, ctx, from_step=from_step, only_steps=only_steps, phase_label=phase_label)
            selected_ids = {s.id for s in steps_to_run}

            # Reset step states
            for sid, st in self.step_states.items():
                if sid in selected_ids:
                    st.status = "pending"
                    st.progress = 0.0
                    st.elapsed = 0.0
                    st.error_message = None
                else:
                    st.status = "skipped"
                    st.progress = 0.0
                self._notify_step(sid)

            total_t0 = time.time()
            for step in steps_to_run:
                if self._stop_requested:
                    self._notify_log(f"[HALTED] Pipeline execution stopped before Step {step.id}.")
                    break

                self.current_step_id = step.id
                st = self.step_states[step.id]
                st.status = "running"
                st.progress = 0.0
                self._notify_step(step.id)

                self._notify_log(f"\n{'='*50}\n  START STEP {step.id}: {step.description}\n{'='*50}")

                t0 = time.time()
                step_ok = True

                try:
                    modules = step.modules()
                    total_mods = len(modules)
                    for m_idx, mod_name in enumerate(modules):
                        if self._stop_requested:
                            step_ok = False
                            break
                        self._run_module(mod_name, ctx)
                        # Multi-module fractional progress fallback (e.g. step 04: 33%, 66%, 100%)
                        if total_mods > 1 and st.progress < (m_idx + 1) / total_mods:
                            st.progress = round((m_idx + 1) / total_mods, 2)
                            self._notify_step(step.id)
                except SystemExit as exc:
                    if exc.code not in (0, None):
                        step_ok = False
                        st.error_message = f"Exit code {exc.code}"
                        self._notify_log(f"[ERROR] Step {step.id} exited with code {exc.code}")
                except Exception as exc:
                    step_ok = False
                    st.error_message = str(exc)
                    self._notify_log(f"[EXCEPTION] Step {step.id} failed: {exc}")

                elapsed = time.time() - t0
                st.elapsed = elapsed

                if step_ok:
                    st.status = "done"
                    st.progress = 1.0
                    self._notify_log(f"[OK] Step {step.id} finished in {elapsed:.1f}s")
                else:
                    st.status = "error"
                    self._notify_step(step.id)
                    error_msg = f"Step {step.id} failed"
                    break

                self._notify_step(step.id)

            total_elapsed = time.time() - total_t0
            if not self._stop_requested and not error_msg:
                success = True
                self._notify_log(f"\n{'#'*50}\n  PIPELINE FINISHED SUCCESSFULLY in {total_elapsed:.1f}s\n{'#'*50}")
            elif self._stop_requested:
                error_msg = "Pipeline stopped by user."
        except ModuleNotFoundError as e:
            error_msg = f"Missing dependency: {e}"
            self._notify_log(f"[FATAL] {error_msg}")
            if any(pkg in str(e) for pkg in ("obspy", "torch", "seisbench", "pygmt", "gamma")):
                self._notify_log("\n[HINT] Seismic libraries are not installed in the active Python environment.")
                self._notify_log("[HINT] Activate the designated conda environment and restart:")
                self._notify_log("       conda activate catalog")
                self._notify_log("       python main.py --gui\n")
        except Exception as e:
            error_msg = f"Pipeline initialization or fatal error: {e}"
            self._notify_log(f"[FATAL] {error_msg}")
        finally:
            self.current_step_id = None
            with self._lock:
                self.is_running = False
            self._notify_finished(success, error_msg or "Completed successfully")

    def _run_optional_worker(self, config_path: str, command: str) -> None:
        success = False
        error_msg = ""

        try:
            ctx = build_context(config_path)

            step = OPTIONAL_STEPS.get(command) or LEGACY_STEPS.get(command)
            if not step:
                raise ValueError(f"Unknown command: {command}")

            self._notify_log(f"\n=== Running optional command: {command} ({step.description}) ===")
            t0 = time.time()
            for mod in step.modules():
                if self._stop_requested:
                    raise InterruptedError("Stopped by user")
                self._run_module(mod, ctx)
            elapsed = time.time() - t0
            success = True
            self._notify_log(f"[OK] Command {command} completed in {elapsed:.1f}s")
        except Exception as e:
            error_msg = "Pipeline stopped by user." if self._stop_requested else str(e)
            self._notify_log(f"[ERROR] Command {command} failed: {error_msg}")
        finally:
            with self._lock:
                self.is_running = False
            self._notify_finished(success, error_msg or f"Command {command} finished")

