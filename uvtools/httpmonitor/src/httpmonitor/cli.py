"""
httpmonitor - Monitor HTTP/TCP connections of a process by PID.

Polls a process's TCP connections and tracks connection state transitions
to estimate completed HTTP requests, completion rate, and more. Outputs
a live TUI dashboard with a rate-over-time plot and writes all data to CSV.
"""

from __future__ import annotations

import argparse
import csv
import re
import signal
import sys
import time
from collections import Counter, deque
from datetime import datetime
from pathlib import Path

import plotext as plt
import psutil
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

__version__ = "0.3.0"

TCP_STATES = {
    "ESTABLISHED": "established",
    "TIME_WAIT": "completed (TIME_WAIT)",
    "CLOSE_WAIT": "closing (CLOSE_WAIT)",
    "FIN_WAIT1": "closing (FIN_WAIT1)",
    "FIN_WAIT2": "closing (FIN_WAIT2)",
    "SYN_SENT": "connecting (SYN_SENT)",
    "LAST_ACK": "closing (LAST_ACK)",
    "CLOSING": "closing",
    "NONE": "unknown",
}

FIELDNAMES = [
    "timestamp",
    "elapsed_s",
    "total_conns",
    "established",
    "time_wait",
    "completed_est",
    "rate_reqs",
]


# ---------------------------------------------------------------------------
# Rate period parsing
# ---------------------------------------------------------------------------

# Maps a unit suffix to its duration in seconds.
_UNIT_SECONDS = {
    "s": 1,
    "sec": 1,
    "second": 1,
    "seconds": 1,
    "m": 60,
    "min": 60,
    "minute": 60,
    "minutes": 60,
    "h": 3600,
    "hr": 3600,
    "hour": 3600,
    "hours": 3600,
}


def parse_period(value: str) -> float:
    """
    Parse a human-friendly period string into seconds.

    Accepted formats:
        "1s", "10s", "30sec"   → seconds
        "1m", "1min", "5min"   → minutes
        "1h", "1hr"            → hours
        "0.5"                  → bare number treated as seconds

    Returns the period in seconds (float).
    """
    value = value.strip().lower()

    # Bare number (seconds)
    try:
        return float(value)
    except ValueError:
        pass

    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([a-z]+)", value)
    if not m:
        raise argparse.ArgumentTypeError(
            f"invalid period: '{value}' "
            "(try '1s', '10s', '1min', '5min', '1h')"
        )

    num = float(m.group(1))
    unit = m.group(2)

    if unit not in _UNIT_SECONDS:
        raise argparse.ArgumentTypeError(
            f"unknown unit '{unit}' in '{value}' "
            f"(valid: {', '.join(sorted(set(_UNIT_SECONDS.values()), key=str))}... "
            f"e.g. '10s', '1min', '1h')"
        )

    return num * _UNIT_SECONDS[unit]


def format_rate(rate_per_second: float, period_seconds: float) -> str:
    """Format a rate (req/s internally) for display using the chosen period."""
    rate = rate_per_second * period_seconds

    if period_seconds < 60:
        if period_seconds == 1:
            return f"{rate:.2f} req/s"
        return f"{rate:.2f} req/{period_seconds:.0f}s"
    elif period_seconds < 3600:
        mins = period_seconds / 60
        if mins == 1:
            return f"{rate:.2f} req/min"
        return f"{rate:.2f} req/{mins:.0f}min"
    else:
        hrs = period_seconds / 3600
        if hrs == 1:
            return f"{rate:.2f} req/h"
        return f"{rate:.2f} req/{hrs:.0f}h"


def rate_unit_label(period_seconds: float) -> str:
    """Short label for the rate unit, used in axes and CSV."""
    if period_seconds < 60:
        if period_seconds == 1:
            return "req/s"
        return f"req/{period_seconds:.0f}s"
    elif period_seconds < 3600:
        mins = period_seconds / 60
        if mins == 1:
            return "req/min"
        return f"req/{mins:.0f}min"
    else:
        hrs = period_seconds / 3600
        if hrs == 1:
            return "req/h"
        return f"req/{hrs:.0f}h"


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def get_connections(pid: int) -> list[psutil.Connection]:
    """Get TCP connections for a process and all its children."""
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return []

    pids = [pid] + [c.pid for c in proc.children(recursive=True)]
    conns = []
    for p in pids:
        try:
            conns.extend(psutil.Process(p).net_connections(kind="tcp"))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return conns


def snapshot(pid: int) -> dict:
    """Take a snapshot of current connections."""
    conns = get_connections(pid)
    state_counts: Counter[str] = Counter()
    remote_hosts: Counter[str] = Counter()

    for c in conns:
        state_counts[c.status] += 1
        if c.raddr:
            remote_hosts[f"{c.raddr.ip}:{c.raddr.port}"] += 1

    return {
        "timestamp": datetime.now(),
        "total": len(conns),
        "states": dict(state_counts),
        "remotes": dict(remote_hosts),
    }


def estimate_completed(history: list[dict]) -> int:
    """
    Estimate cumulative completed requests by tracking connection churn.

    Each time a connection leaves ESTABLISHED (and enters TIME_WAIT or
    disappears), we count it as a completed request.
    """
    if len(history) < 2:
        return 0

    completed = 0
    for i in range(1, len(history)):
        prev_est = history[i - 1]["states"].get("ESTABLISHED", 0)
        curr_est = history[i]["states"].get("ESTABLISHED", 0)
        curr_tw = history[i]["states"].get("TIME_WAIT", 0)
        prev_tw = history[i - 1]["states"].get("TIME_WAIT", 0)

        new_tw = max(0, curr_tw - prev_tw)
        vanished = max(0, prev_est - curr_est - new_tw) if prev_est > curr_est else 0
        completed += new_tw + vanished

    return completed


# ---------------------------------------------------------------------------
# Resume: read previous CSV to restore state
# ---------------------------------------------------------------------------


def load_resume_state(csv_path: Path) -> dict:
    """
    Read an existing CSV and return the last state so monitoring can continue.

    Returns a dict with:
        elapsed_offset   - last elapsed_s value (float)
        completed_offset - last completed_est value (int)
        rate_history     - list of (elapsed_s, rate_reqs) for the plot
    """
    elapsed_offset = 0.0
    completed_offset = 0
    rate_history: list[tuple[float, float]] = []

    try:
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                elapsed = float(row["elapsed_s"])
                completed = int(row["completed_est"])
                rate = float(row["rate_reqs"])
                rate_history.append((elapsed, rate))
            # Last row wins
            if rate_history:
                elapsed_offset = elapsed
                completed_offset = completed
    except (FileNotFoundError, KeyError, ValueError):
        pass

    return {
        "elapsed_offset": elapsed_offset,
        "completed_offset": completed_offset,
        "rate_history": rate_history,
    }


# ---------------------------------------------------------------------------
# Rate tracking
# ---------------------------------------------------------------------------


class RateTracker:
    """Track completion rate over time with a rolling window."""

    def __init__(self, window_size: int = 10):
        self.window_size = window_size
        self._samples: list[tuple[float, int]] = []
        self.rate_history: deque[float] = deque(maxlen=300)
        self.elapsed_history: deque[float] = deque(maxlen=300)

    def seed(self, history: list[tuple[float, float]]) -> None:
        """Pre-populate rate/elapsed history from a resumed CSV."""
        tail = history[-300:]
        for elapsed, rate in tail:
            self.elapsed_history.append(elapsed)
            self.rate_history.append(rate)

    def update(self, elapsed_s: float, cumulative_completed: int) -> float:
        """Record a sample and return the current rate (req/s)."""
        self._samples.append((elapsed_s, cumulative_completed))

        if len(self._samples) < 2:
            self.rate_history.append(0.0)
            self.elapsed_history.append(elapsed_s)
            return 0.0

        window_start = max(0, len(self._samples) - self.window_size - 1)
        t0, c0 = self._samples[window_start]
        t1, c1 = self._samples[-1]
        dt = t1 - t0

        rate = (c1 - c0) / dt if dt > 0 else 0.0
        self.rate_history.append(rate)
        self.elapsed_history.append(elapsed_s)
        return rate


# ---------------------------------------------------------------------------
# TUI rendering
# ---------------------------------------------------------------------------


def _sparkline(values: list[float], width: int = 50) -> str:
    """Simple Unicode sparkline as a fallback."""
    if not values:
        return ""
    blocks = " ▁▂▃▄▅▆▇█"
    mn, mx = min(values), max(values)
    rng = mx - mn if mx != mn else 1.0
    # Downsample to fit width
    if len(values) > width:
        step = len(values) / width
        values = [values[int(i * step)] for i in range(width)]
    return "".join(blocks[min(8, int((v - mn) / rng * 8))] for v in values)


def build_rate_plot(
    rate_tracker: RateTracker,
    period: float,
    width: int | None = None,
    height: int | None = None,
) -> str:
    """Render a plotext chart to a string for embedding in Rich."""
    elapsed = list(rate_tracker.elapsed_history)
    rates = [r * period for r in rate_tracker.rate_history]

    if len(elapsed) < 2:
        return "  Waiting for data..."

    # Adapt to terminal size, leave room for panel borders + table
    if width is None:
        try:
            import shutil
            term_w = shutil.get_terminal_size().columns
        except Exception:
            term_w = 80
        width = max(40, term_w - 6)  # panel borders + padding
    if height is None:
        try:
            import shutil
            term_h = shutil.get_terminal_size().lines
        except Exception:
            term_h = 40
        height = max(8, term_h // 3)

    unit = rate_unit_label(period)

    try:
        plt.clear_figure()
        plt.plot_size(width, height)
        plt.plot(elapsed, rates, marker="dot")
        plt.title(f"Completion Rate ({unit})")
        plt.xlabel("Elapsed (s)")
        plt.ylabel(unit)
        plt.theme("clear")
        return plt.build()
    except Exception:
        # Fallback: text-based sparkline
        spark = _sparkline(rates, width - 10)
        mn, mx = min(rates), max(rates)
        return (
            f"  Completion Rate ({unit})\n"
            f"  {spark}\n"
            f"  min={mn:.1f}  max={mx:.1f}  latest={rates[-1]:.1f}"
        )


def build_dashboard(
    snap: dict,
    completed: int,
    rate: float,
    rate_tracker: RateTracker,
    pid: int,
    period: float,
    resumed: bool = False,
) -> Layout:
    """Build a full dashboard with table + rate plot."""
    layout = Layout()
    layout.split_column(
        Layout(name="top", size=12),
        Layout(name="bottom"),
    )

    title = f"httpmonitor · PID {pid} · {snap['timestamp']:%H:%M:%S}"
    if resumed:
        title += " [dim](resumed)[/dim]"

    table = Table(
        title=title,
        title_style="bold cyan",
        show_header=True,
        header_style="bold",
        min_width=55,
        expand=True,
    )
    table.add_column("Metric", style="dim")
    table.add_column("Value", justify="right")

    table.add_row("Total connections", str(snap["total"]))
    table.add_row("Estimated completed", f"[green]{completed}[/green]")
    table.add_row("Completion rate", f"[cyan]{format_rate(rate, period)}[/cyan]")

    if rate > 0:
        avg_rates = list(rate_tracker.rate_history)
        if avg_rates:
            avg = sum(avg_rates) / len(avg_rates)
            peak = max(avg_rates)
            table.add_row("Avg rate", format_rate(avg, period))
            table.add_row("Peak rate", f"[yellow]{format_rate(peak, period)}[/yellow]")

    for state, count in sorted(snap["states"].items()):
        label = TCP_STATES.get(state, state)
        table.add_row(f"  {label}", str(count))

    layout["top"].update(table)

    plot_str = build_rate_plot(rate_tracker, period)
    plot_panel = Panel(
        Text.from_ansi(plot_str),
        title="[cyan]Rate over time[/cyan]",
        border_style="dim",
    )
    layout["bottom"].update(plot_panel)

    return layout


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

DESCRIPTION = """\
Monitor HTTP/TCP connections of a process by PID.

Polls the target process's TCP connections at a regular interval and
tracks state transitions (ESTABLISHED → TIME_WAIT) to estimate the
number of completed HTTP requests and the completion rate over time.

All data is written to a CSV file for later analysis. In TUI mode
(the default), a live dashboard shows connection stats and a
rate-over-time plot.
"""

EPILOG = """\
examples:
  httpmonitor 12345                    Monitor PID 12345 (1s interval, TUI)
  httpmonitor 12345 -i 0.5            Poll every 0.5s for faster processes
  httpmonitor 12345 -o run1.csv       Write output to run1.csv
  httpmonitor 12345 -r                Resume from existing httpmonitor_12345.csv
  httpmonitor 12345 -r -o run1.csv    Resume from run1.csv
  httpmonitor 12345 -p 1min           Show rate as req/min
  httpmonitor 12345 -p 10s            Show rate as req/10s
  httpmonitor 12345 -p 1h             Show rate as req/h
  httpmonitor 12345 -w 20             Smoother rate (20-sample window)
  httpmonitor 12345 --no-tui          Plain text output for piping/logging
  httpmonitor 12345 -f                Overwrite existing CSV without prompting
  sudo httpmonitor 12345              Monitor a process owned by another user

rate period (-p):
  Controls the unit used to display and record the completion rate.
  Accepts a number with a unit suffix: s/sec, m/min, h/hr.
  Examples: "1s" (req/s, default), "10s" (req/10s), "1min" (req/min), "1h" (req/h).
"""


def main():
    parser = argparse.ArgumentParser(
        prog="httpmonitor",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "pid",
        type=int,
        help="process ID to monitor",
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=float,
        default=1.0,
        metavar="SECS",
        help="polling interval in seconds (default: 1.0)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        metavar="FILE",
        help="output CSV file (default: httpmonitor_<PID>.csv)",
    )
    parser.add_argument(
        "-p",
        "--period",
        type=str,
        default="1s",
        metavar="PERIOD",
        help="rate display period: '1s' (req/s), '10s', '1min', '1h' (default: 1s)",
    )
    parser.add_argument(
        "-w",
        "--window",
        type=int,
        default=10,
        metavar="N",
        help="rolling window size for rate smoothing (default: 10 samples)",
    )
    parser.add_argument(
        "-r",
        "--resume",
        action="store_true",
        help="resume from an existing CSV file, continuing elapsed time "
        "and completed count from where it left off",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="overwrite existing CSV file without prompting",
    )
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="plain text output instead of the rich TUI dashboard",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    args = parser.parse_args()

    # --- Parse period ---
    period = parse_period(args.period)

    # --- Verify PID ---
    try:
        proc = psutil.Process(args.pid)
        proc_name = proc.name()
    except psutil.NoSuchProcess:
        print(f"error: no process with PID {args.pid}", file=sys.stderr)
        sys.exit(1)
    except psutil.AccessDenied:
        print(
            f"error: access denied for PID {args.pid} (try sudo)",
            file=sys.stderr,
        )
        sys.exit(1)

    outfile = Path(args.output or f"httpmonitor_{args.pid}.csv")
    console = Console()
    history: list[dict] = []

    # Auto-scale window: ensure it covers at least one full period so that
    # e.g. -p 1min with -i 1 uses a 60-sample window minimum, giving genuine
    # per-minute smoothing instead of jittery per-second rate × 60.
    min_window_for_period = max(1, int(period / args.interval))
    effective_window = max(args.window, min_window_for_period)
    if effective_window != args.window:
        console.print(
            f"[dim]Window auto-scaled from {args.window} to {effective_window} "
            f"samples to cover the full {args.period} period[/dim]"
        )
    rate_tracker = RateTracker(window_size=effective_window)

    # --- Resume handling ---
    elapsed_offset = 0.0
    completed_offset = 0
    resumed = False

    if args.resume and outfile.exists():
        state = load_resume_state(outfile)
        elapsed_offset = state["elapsed_offset"]
        completed_offset = state["completed_offset"]
        if state["rate_history"]:
            rate_tracker.seed(state["rate_history"])
        resumed = True
        console.print(
            f"[yellow]Resuming[/yellow] from {outfile} "
            f"(elapsed={elapsed_offset:.1f}s, completed={completed_offset})"
        )
    elif not args.resume and outfile.exists() and not args.force:
        # --- Overwrite confirmation ---
        console.print(
            f"[yellow]Warning:[/yellow] {outfile} already exists."
        )
        console.print(
            "  Use [bold]-r/--resume[/bold] to continue from it, "
            "or [bold]-f/--force[/bold] to overwrite."
        )
        try:
            response = console.input("  Overwrite? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            console.print("\nAborted.")
            sys.exit(0)
        if response.strip().lower() not in ("y", "yes"):
            console.print("Aborted.")
            sys.exit(0)

    # --- Open CSV (append if resuming, write if fresh) ---
    if resumed:
        csv_fh = open(outfile, "a", newline="")
        writer = csv.DictWriter(csv_fh, fieldnames=FIELDNAMES)
    else:
        csv_fh = open(outfile, "w", newline="")
        writer = csv.DictWriter(csv_fh, fieldnames=FIELDNAMES)
        writer.writeheader()

    start_time = time.monotonic()

    def cleanup(*_):
        csv_fh.close()
        console.print(f"\n[dim]Results saved to {outfile}[/dim]")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    mode = "resumed" if resumed else "fresh"
    unit = rate_unit_label(period)
    console.print(
        f"[bold]Monitoring[/bold] PID {args.pid} ({proc_name}) → {outfile} "
        f"[{mode}, rate in {unit}]"
    )

    def tick():
        snap = snapshot(args.pid)
        history.append(snap)
        completed_delta = estimate_completed(history)
        completed = completed_offset + completed_delta
        elapsed = elapsed_offset + (time.monotonic() - start_time)
        rate = rate_tracker.update(elapsed, completed)

        # CSV always stores rate in the display period
        display_rate = rate * period

        row = {
            "timestamp": snap["timestamp"].isoformat(),
            "elapsed_s": f"{elapsed:.1f}",
            "total_conns": snap["total"],
            "established": snap["states"].get("ESTABLISHED", 0),
            "time_wait": snap["states"].get("TIME_WAIT", 0),
            "completed_est": completed,
            "rate_reqs": f"{display_rate:.3f}",
        }
        writer.writerow(row)
        csv_fh.flush()

        return snap, completed, rate

    if args.no_tui:
        console.print(
            f"timestamp | total | established | time_wait | completed | rate ({unit})"
        )
        console.print("-" * 70)
        while True:
            snap, completed, rate = tick()
            est = snap["states"].get("ESTABLISHED", 0)
            tw = snap["states"].get("TIME_WAIT", 0)
            console.print(
                f"{snap['timestamp']:%H:%M:%S} | "
                f"{snap['total']:5d} | {est:11d} | {tw:9d} | "
                f"{completed:9d} | {format_rate(rate, period)}"
            )
            time.sleep(args.interval)
    else:
        with Live(console=console, refresh_per_second=2, screen=True) as live:
            while True:
                snap, completed, rate = tick()
                dashboard = build_dashboard(
                    snap, completed, rate, rate_tracker, args.pid,
                    period=period, resumed=resumed,
                )
                live.update(dashboard)
                time.sleep(args.interval)


if __name__ == "__main__":
    main()
