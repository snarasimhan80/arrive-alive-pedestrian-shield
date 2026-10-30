"""Conservative scene signals from a fixed camera's sampled detections.

Tracks are short-lived visual associations, not person identification. A crossing
or speed result is a candidate for review, never a measured crash outcome.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def segment_crossing_fraction(start: tuple[float, float], end: tuple[float, float],
                              gate: tuple[tuple[float, float], tuple[float, float]]) -> float | None:
    """Return the fraction of a moving point's path that crosses a finite gate."""
    (ax, ay), (bx, by) = gate
    px, py = start
    rx, ry = end[0] - px, end[1] - py
    sx, sy = bx - ax, by - ay
    denominator = rx * sy - ry * sx
    if abs(denominator) < 1e-9:
        return None
    qx, qy = ax - px, ay - py
    travel = (qx * sy - qy * sx) / denominator
    along_gate = (qx * ry - qy * rx) / denominator
    if 0 <= travel <= 1 and 0 <= along_gate <= 1:
        return travel
    return None


@dataclass
class VisualTrack:
    id: int
    class_name: str
    point: tuple[float, float]
    box: tuple[int, int, int, int]
    zone: str
    seconds: float
    crossings: dict[str, float] = field(default_factory=dict)


class ShortTrackMatcher:
    """Greedy same-class association across adjacent sampled frames only."""

    def __init__(self, frame_width: int, max_fraction: float) -> None:
        self.max_distance = frame_width * max_fraction
        self.tracks: dict[int, VisualTrack] = {}
        self.next_id = 1

    def update(self, objects: list[dict], seconds: float) -> list[tuple[dict, VisualTrack, VisualTrack | None]]:
        eligible = {track_id: track for track_id, track in self.tracks.items()
                    if seconds - track.seconds <= 2.0}
        candidates = []
        for index, item in enumerate(objects):
            x, y = item["footpoint"]
            for track_id, track in eligible.items():
                if item["class"] != track.class_name:
                    continue
                old_width = max(1, track.box[2] - track.box[0])
                new_width = max(1, item["box"][2] - item["box"][0])
                if not 0.35 <= new_width / old_width <= 2.8:
                    continue
                distance = math.hypot(x - track.point[0], y - track.point[1])
                if distance <= self.max_distance:
                    candidates.append((distance, index, track_id))
        candidates.sort()
        matched_items: dict[int, int] = {}
        used_tracks: set[int] = set()
        for _, index, track_id in candidates:
            if index not in matched_items and track_id not in used_tracks:
                matched_items[index] = track_id
                used_tracks.add(track_id)
        output = []
        updated = {}
        for index, item in enumerate(objects):
            track_id = matched_items.get(index)
            previous = eligible.get(track_id) if track_id is not None else None
            if track_id is None:
                track_id = self.next_id
                self.next_id += 1
            current = VisualTrack(track_id, item["class"], tuple(item["footpoint"]),
                                  tuple(item["box"]), item.get("zone", "other"), seconds,
                                  dict(previous.crossings) if previous else {})
            updated[track_id] = current
            output.append((item, current, previous))
        self.tracks = updated
        return output


class SpeedGateTracker:
    def __init__(self, width: int, height: int, gates: dict) -> None:
        self.matcher = ShortTrackMatcher(width, 0.24)
        self.gates = {}
        for name in ("a", "b"):
            self.gates[name] = tuple(tuple((point[0] * (width - 1), point[1] * (height - 1)))
                                     for point in gates[name])
        self.distance_m = gates["distance_m"]
        self.samples: list[float] = []
        self.counted_tracks: set[int] = set()

    def update(self, vehicles: list[dict], seconds: float) -> None:
        for _, current, previous in self.matcher.update(vehicles, seconds):
            if previous is None:
                continue
            for name, gate in self.gates.items():
                if name in current.crossings:
                    continue
                fraction = segment_crossing_fraction(previous.point, current.point, gate)
                if fraction is not None:
                    current.crossings[name] = previous.seconds + fraction * (seconds - previous.seconds)
            if current.id in self.counted_tracks or set(current.crossings) != {"a", "b"}:
                continue
            elapsed = abs(current.crossings["a"] - current.crossings["b"])
            if elapsed < 0.1:
                continue
            speed = self.distance_m / elapsed * 3.6
            if 5 <= speed <= 120:
                self.samples.append(round(speed, 1))
                self.counted_tracks.add(current.id)


class PersonMovementTracker:
    def __init__(self, width: int) -> None:
        self.matcher = ShortTrackMatcher(width, 0.12)
        self.last_blockage_seconds = -math.inf
        self.counted_tracks: set[int] = set()

    def update(self, people: list[dict], seconds: float, blocked: bool) -> list[dict]:
        if blocked:
            self.last_blockage_seconds = seconds
        candidates = []
        for item, current, previous in self.matcher.update(people, seconds):
            if (previous and previous.zone == "footpath" and current.zone == "road"
                    and seconds - self.last_blockage_seconds <= 2.0
                    and current.id not in self.counted_tracks):
                self.counted_tracks.add(current.id)
                candidates.append({"seconds": round(seconds, 2), "box": item["box"],
                                   "track_id": current.id})
        return candidates


class FootpathFlowCounter:
    """Count candidate unique pedestrian tracks crossing a marked line."""

    def __init__(self, width: int, height: int,
                 line: list[list[float]]) -> None:
        self.matcher = ShortTrackMatcher(width, 0.12)
        self.line = tuple(tuple((point[0] * (width - 1), point[1] * (height - 1)))
                          for point in line)
        self.min_movement = width * 0.012
        self.counted_tracks: set[int] = set()
        self.count = 0

    def update(self, people: list[dict], seconds: float) -> int:
        for _, current, previous in self.matcher.update(people, seconds):
            if (previous is None or current.id in self.counted_tracks
                    or not (previous.zone == "footpath" or current.zone == "footpath")
                    or math.dist(previous.point, current.point) < self.min_movement):
                continue
            if segment_crossing_fraction(previous.point, current.point, self.line) is not None:
                self.counted_tracks.add(current.id)
                self.count += 1
        return self.count


def largest_person_group(people: list[dict], width: int, height: int) -> int:
    """Count the largest nearby group in image space; this is only a crowd cue."""
    points = [(item["footpoint"][0] / width, item["footpoint"][1] / height)
              for item in people]
    unseen = set(range(len(points)))
    largest = 0
    while unseen:
        group = {unseen.pop()}
        frontier = list(group)
        while frontier:
            index = frontier.pop()
            nearby = {other for other in unseen
                      if math.dist(points[index], points[other]) <= 0.16}
            unseen -= nearby
            group |= nearby
            frontier.extend(nearby)
        largest = max(largest, len(group))
    return largest


def exposure_estimate(flow_per_hour: float | None, width_m: float | None,
                      width_lost_m: float | None, speed_kmh: float | None) -> dict:
    """Compute the PRD's *relative exposure index*, not a crash probability."""
    result = {"displaced_per_hour": None, "speed_weighted_exposure": None,
              "speed_multiplier": None}
    if (flow_per_hour is not None and width_m is not None and width_m > 0
            and width_lost_m is not None):
        result["displaced_per_hour"] = round(flow_per_hour * min(1.0, width_lost_m / width_m), 1)
    if speed_kmh is not None:
        result["speed_multiplier"] = round((speed_kmh / 30) ** 1.5, 2)
    if result["displaced_per_hour"] is not None and result["speed_multiplier"] is not None:
        result["speed_weighted_exposure"] = round(
            result["displaced_per_hour"] * (speed_kmh / 30) ** 1.5, 1)
    return result
