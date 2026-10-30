"""FR-25 comparison across explicitly selected analysis jobs.

The score is relative to this set of sites. It is not an accident probability.
"""

from __future__ import annotations


def rank_sites(reports: list[dict]) -> list[dict]:
    rows = []
    for report in reports:
        exposure = report.get("exposure") or {}
        inputs = report.get("site_inputs") or {}
        speed = report.get("traffic_speed") or {}
        raw = exposure.get("speed_weighted_exposure")
        rows.append({
            "job_id": report.get("job_id"),
            "site_name": report.get("site_name") or "Unnamed site",
            "footpath_width_m": inputs.get("footpath_width_m"),
            "footpath_width_source": inputs.get("footpath_width_source"),
            "width_lost_m": inputs.get("width_lost_m"),
            "width_lost_source": inputs.get("width_lost_source"),
            "peak_flow_per_hour": inputs.get("peak_flow_per_hour"),
            "flow_source": inputs.get("flow_source"),
            "speed_kmh": speed.get("kmh"),
            "speed_source": speed.get("source"),
            "vehicle_speed_samples": len(speed.get("video_vehicle_samples_kmh") or []),
            "displaced_per_hour": exposure.get("displaced_per_hour"),
            "raw_exposure": raw,
            "relative_exposure_0_100": None,
            "comparison_label": "Inputs needed" if raw is None else None,
            "synthetic": bool(report.get("synthetic")),
        })
    worst = max((row["raw_exposure"] for row in rows if row["raw_exposure"] is not None), default=None)
    complete = [row for row in rows if row["raw_exposure"] is not None]
    for row in complete:
        row["relative_exposure_0_100"] = round(100 * row["raw_exposure"] / worst, 1) if worst else 0.0
        row["comparison_label"] = ("Highest in set" if row["raw_exposure"] == worst and worst
                                   else "Relative exposure")
    rows.sort(key=lambda row: (row["raw_exposure"] is None,
                               -(row["raw_exposure"] or 0), row["site_name"].lower()))
    return rows
