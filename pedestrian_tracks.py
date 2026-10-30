"""Short anonymous pedestrian tracks with a brief occlusion memory.

Position, velocity and clothing colour help reconnect a partially hidden
walker. No face recognition or persistent identity is used.
"""
from dataclasses import dataclass
import math
import cv2
import numpy as np


@dataclass
class PedestrianTrack:
    id: int
    point: tuple
    box: tuple
    zone: str
    seconds: float
    velocity: tuple
    appearance: np.ndarray
    hits: int = 1


def clothing_histogram(frame, box):
    x1, y1, x2, y2 = box
    width, height = x2-x1, y2-y1
    crop = frame[max(0, y1+round(height*.22)):min(frame.shape[0], y1+round(height*.65)),
                 max(0, x1+round(width*.2)):min(frame.shape[1], x2-round(width*.2))]
    if crop.size == 0:
        return np.zeros(48, dtype=np.float32)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [12, 4], [0, 180, 0, 256]).flatten()
    return hist / max(float(hist.sum()), 1)


class PedestrianTrackMatcher:
    def __init__(self, width, max_fraction=.12):
        self.max_distance = width * max_fraction
        self.tracks = {}
        self.next_id = 1

    def update(self, people, seconds, frame):
        eligible = {key: track for key, track in self.tracks.items()
                    if seconds-track.seconds <= 1.5}
        old = list(eligible.values())
        descriptors = [clothing_histogram(frame, item['box']) for item in people]
        costs = np.full((len(people), len(old)), 1e6, dtype=np.float64)
        for row, item in enumerate(people):
            point = item['footpoint']
            new_width = max(1, item['box'][2]-item['box'][0])
            for column, track in enumerate(old):
                elapsed = seconds-track.seconds
                ratio = new_width / max(1, track.box[2]-track.box[0])
                travel = math.dist(point, track.point)
                if not .25 <= ratio <= 3.5 or travel > self.max_distance * (1+min(elapsed, 1)):
                    continue
                predicted = tuple(track.point[i] + track.velocity[i]*min(elapsed, .75) for i in (0, 1))
                colour = math.sqrt(max(0, 1-float(np.sqrt(descriptors[row]*track.appearance).sum())))
                costs[row, column] = (.7*math.dist(point, predicted) + .3*travel
                                      + self.max_distance*.65*colour + elapsed*5
                                      - min(track.hits, 8)*.8)
        matched = {}
        candidates = sorted((costs[row, column], row, column)
                            for row in range(len(people)) for column in range(len(old))
                            if costs[row, column] < 1e5)
        used = set()
        for _, row, column in candidates:
            if row not in matched and column not in used:
                matched[row] = old[column]
                used.add(column)
        updated = dict(eligible)
        output = []
        for index, item in enumerate(people):
            previous = matched.get(index)
            point = tuple(item['footpoint'])
            descriptor = descriptors[index]
            if previous:
                elapsed = max(.01, seconds-previous.seconds)
                velocity = tuple(.6*previous.velocity[i] + .4*(point[i]-previous.point[i])/elapsed for i in (0, 1))
                descriptor = .8*previous.appearance + .2*descriptor
                current = PedestrianTrack(previous.id, point, tuple(item['box']), item.get('zone', 'other'),
                                          seconds, velocity, descriptor, previous.hits+1)
            else:
                current = PedestrianTrack(self.next_id, point, tuple(item['box']), item.get('zone', 'other'),
                                          seconds, (0, 0), descriptor)
                self.next_id += 1
            updated[current.id] = current
            output.append((item, current, previous))
        self.tracks = updated
        return output
