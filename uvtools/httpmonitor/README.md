# httpmonitor

Monitor HTTP/TCP connections of a process by PID, with live completion rate tracking, a TUI plot, resume support, and configurable rate period.

## Install

```bash
uv tool install .
```

Or run directly without installing:

```bash
uv run httpmonitor <PID>
```

## Usage

```bash
httpmonitor <PID> [OPTIONS]
```

### Options

| Flag | Description |
|---|---|
| `-i, --interval SECS` | Polling interval in seconds (default: 1.0) |
| `-o, --output FILE` | Output CSV file (default: `httpmonitor_<PID>.csv`) |
| `-p, --period PERIOD` | Rate display period: `1s`, `10s`, `1min`, `1h` (default: `1s`) |
| `-w, --window N` | Rolling window size for rate smoothing (default: 10) |
| `-r, --resume` | Resume from an existing CSV, continuing elapsed time and completed count |
| `-f, --force` | Overwrite existing CSV file without prompting |
| `--no-tui` | Plain text output instead of the rich TUI dashboard |
| `-V, --version` | Show version and exit |

### Examples

```bash
# Basic monitoring (1s interval, TUI dashboard)
httpmonitor 12345

# Poll every 0.5s for faster processes
httpmonitor 12345 -i 0.5

# Show rate as requests per minute
httpmonitor 12345 -p 1min

# Show rate as requests per 10 seconds
httpmonitor 12345 -p 10s

# Show rate as requests per hour
httpmonitor 12345 -p 1h

# Write output to a specific file
httpmonitor 12345 -o run1.csv

# Resume from where you left off
httpmonitor 12345 --resume
httpmonitor 12345 --resume -o run1.csv

# Overwrite existing file without prompting
httpmonitor 12345 -f

# Smoother rate with a 20-sample rolling window
httpmonitor 12345 -w 20

# Plain text for piping or logging
httpmonitor 12345 --no-tui

# Monitor a process owned by another user
sudo httpmonitor 12345
```

## Rate Period

The `-p / --period` flag controls the unit used to display and record the completion rate. Internally, the rate is always computed in req/s and then scaled to the chosen period.

| Period | Display | Meaning |
|---|---|---|
| `1s` (default) | `3.50 req/s` | 3.5 requests per second |
| `10s` | `35.00 req/10s` | 35 requests every 10 seconds |
| `1min` | `210.00 req/min` | 210 requests per minute |
| `1h` | `12600.00 req/h` | 12600 requests per hour |

## Overwrite Protection

If the output CSV already exists and you haven't passed `--resume` or `--force`, httpmonitor will ask for confirmation before overwriting:

```
Warning: httpmonitor_12345.csv already exists.
  Use -r/--resume to continue from it, or -f/--force to overwrite.
  Overwrite? [y/N]
```

## Resume

If your monitoring session is interrupted (Ctrl+C, ssh disconnect, etc.), you can pick up where you left off with `--resume`. This reads the existing CSV to restore:

- **Elapsed time offset** — the clock continues from the last recorded time
- **Completed count offset** — new completions are added to the previous total
- **Rate plot history** — the TUI plot shows the full history from the CSV

The new data is appended to the same CSV file.

## Output

The CSV file contains:

| Column | Description |
|---|---|
| `timestamp` | ISO timestamp |
| `elapsed_s` | Seconds since monitoring started (continuous across resumes) |
| `total_conns` | Total TCP connections |
| `established` | Active connections |
| `time_wait` | Connections in TIME_WAIT (recently completed) |
| `completed_est` | Cumulative estimated completed requests |
| `rate_reqs` | Completion rate in the configured period (see `-p`) |

## TUI Dashboard

The default TUI shows:
- Connection stats table (total, established, completed, rate, avg, peak)
- Live braille plot of completion rate over time (last 300 samples)
- `(resumed)` indicator in the title when continuing a previous session

## How it works

The tool polls the process's TCP connections via `psutil` and tracks connection state transitions. When connections move from `ESTABLISHED` to `TIME_WAIT` (or disappear entirely), they are counted as completed HTTP requests. The rate is computed over a rolling window (configurable with `-w`).

## Limitations

- Polling-based: very short-lived connections between polls may be missed. Use a shorter `-i` interval to reduce this.
- The completed count is an estimate based on TCP state transitions.
- Requires read access to `/proc/<pid>/net` (may need `sudo`).
