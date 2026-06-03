"""Emit scheduler snippets for common operating systems."""

from __future__ import annotations


def _hour_minute(at: str) -> tuple[str, str]:
    hour, minute = at.split(":", 1)
    h = int(hour)
    m = int(minute)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("time must be HH:MM in 24-hour format")
    return str(h).zfill(2), str(m).zfill(2)


def emit_windows_task(name: str, command: str, *, at: str = "09:00", daily: bool = True) -> str:
    cadence = "DAILY" if daily else "ONCE"
    return f'schtasks /Create /TN "{name}" /TR "{command}" /SC {cadence} /ST {at}'


def emit_cron(command: str, *, at: str = "09:00", daily: bool = True) -> str:
    hour, minute = _hour_minute(at)
    day = "*" if daily else "1"
    return f"{int(minute)} {int(hour)} {day} * * {command}"


def emit_launchd(name: str, command: str, *, at: str = "09:00") -> str:
    hour, minute = _hour_minute(at)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{name}</string>
  <key>ProgramArguments</key>
  <array><string>/bin/sh</string><string>-lc</string><string>{command}</string></array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>{int(hour)}</integer><key>Minute</key><integer>{int(minute)}</integer></dict>
</dict>
</plist>"""
