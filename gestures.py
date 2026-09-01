# gestures.py - part 1/2
import math


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _dist_rel(a, b, palm):
    base = max(_dist(palm, (palm[0], palm[1])), 1e-6)
    return _dist(a, b) / base


# Landmark indices (MediaPipe Hands, 21 points)
WRIST = 0
THUMB_TIP = 4
INDEX_TIP = 8
MIDDLE_TIP = 12
RING_TIP = 16
PINKY_TIP = 20
INDEX_PIP = 6
MIDDLE_PIP = 10
RING_PIP = 14
PINKY_PIP = 18
THUMB_IP = 2


def _palm_center(lm):
    xs = [lm[i][0] for i in (0, 5, 9, 13, 17)]
    ys = [lm[i][1] for i in (0, 5, 9, 13, 17)]
    return (sum(xs) / len(xs), sum(ys) / len(ys))
# gestures.py - part 2/2
def _finger_extended(lm, tip, pip_idx, wrist):
    # extended if tip is farther from wrist than the pip joint
    return _dist_rel(lm[tip], wrist, wrist) > _dist_rel(lm[pip_idx], wrist, wrist) * 1.0


def finger_states(lm):
    """Return dict of extended booleans for each finger."""
    wrist = lm[WRIST]
    return {
        "index": _finger_extended(lm, INDEX_TIP, INDEX_PIP, wrist),
        "middle": _finger_extended(lm, MIDDLE_TIP, MIDDLE_PIP, wrist),
        "ring": _finger_extended(lm, RING_TIP, RING_PIP, wrist),
        "pinky": _finger_extended(lm, PINKY_TIP, PINKY_PIP, wrist),
    }


def pinch_pair(lm, thumb, other, thresh=0.42):
    """True if thumb tip is close to `other` tip (relative to palm size)."""
    palm = _palm_center(lm)
    d = _dist(lm[thumb], lm[other]) / max(_dist(lm[WRIST], palm), 1e-6)
    return d < thresh


def classify(lm, pinch_thresh=0.42):
    """Return (gesture, fingers) where gesture is one of:
    'move','left','scroll','right','none'."""
    fingers = finger_states(lm)
    if pinch_pair(lm, THUMB_TIP, INDEX_TIP, pinch_thresh):
        return "left", fingers
    if pinch_pair(lm, THUMB_TIP, MIDDLE_TIP, pinch_thresh):
        return "scroll", fingers
    if pinch_pair(lm, THUMB_TIP, PINKY_TIP, pinch_thresh):
        return "right", fingers
    if all(fingers.values()):
        return "move", fingers
    return "none", fingers
