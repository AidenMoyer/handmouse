import math

# Landmark indices (MediaPipe Hands, 21 points)
WRIST      = 0
THUMB_TIP  = 4
INDEX_TIP  = 8;  INDEX_MCP  = 5;  INDEX_PIP  = 6
MIDDLE_TIP = 12; MIDDLE_MCP = 9;  MIDDLE_PIP = 10
RING_TIP   = 16; RING_MCP   = 13; RING_PIP   = 14
PINKY_TIP  = 20; PINKY_MCP  = 17; PINKY_PIP  = 18
THUMB_IP   = 2


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _palm_center(lm):
    xs = [lm[i][0] for i in (0, 5, 9, 13, 17)]
    ys = [lm[i][1] for i in (0, 5, 9, 13, 17)]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _finger_extended(lm, tip, pip_idx):
    """True when tip is farther from wrist than the PIP knuckle (finger is open)."""
    wrist = lm[WRIST]
    return _dist(lm[tip], wrist) > _dist(lm[pip_idx], wrist)


def finger_states(lm):
    """Return dict of extended booleans for each finger."""
    return {
        "index":  _finger_extended(lm, INDEX_TIP,  INDEX_PIP),
        "middle": _finger_extended(lm, MIDDLE_TIP, MIDDLE_PIP),
        "ring":   _finger_extended(lm, RING_TIP,   RING_PIP),
        "pinky":  _finger_extended(lm, PINKY_TIP,  PINKY_PIP),
    }


def fist_closed(lm):
    """True when all four fingertips are curled below their MCP knuckles.

    Uses MCP (base knuckle) rather than PIP so a loose/partial fist is still
    detected — the tip only needs to be closer to the wrist than the knuckle,
    not all the way to the palm.
    """
    wrist = lm[WRIST]
    pairs = [
        (INDEX_TIP,  INDEX_MCP),
        (MIDDLE_TIP, MIDDLE_MCP),
        (RING_TIP,   RING_MCP),
        (PINKY_TIP,  PINKY_MCP),
    ]
    return all(_dist(lm[tip], wrist) < _dist(lm[mcp], wrist) * 1.1
               for tip, mcp in pairs)


def pinch_pair(lm, thumb, other, thresh=0.42):
    """True if thumb tip is close to `other` tip (relative to wrist-palm dist)."""
    palm = _palm_center(lm)
    d = _dist(lm[thumb], lm[other]) / max(_dist(lm[WRIST], palm), 1e-6)
    return d < thresh


def classify(lm, pinch_thresh=0.42):
    """Return (gesture, fingers) where gesture is one of:
    'fist', 'move', 'left', 'scroll', 'right', 'none'.

    Order matters:
      1. Fist checked first — closing the hand always stops movement immediately.
      2. Pinches checked next — thumb+finger contact overrides open-hand state.
      3. All fingers open → move.
      4. Anything else → none (transitional / ambiguous state).
    """
    fingers = finger_states(lm)

    # 1. Fist — explicit stop, highest priority
    if fist_closed(lm):
        return "fist", fingers

    # 2. Pinch gestures
    if pinch_pair(lm, THUMB_TIP, INDEX_TIP,  pinch_thresh):
        return "left", fingers
    if pinch_pair(lm, THUMB_TIP, MIDDLE_TIP, pinch_thresh):
        return "scroll", fingers
    if pinch_pair(lm, THUMB_TIP, PINKY_TIP,  pinch_thresh):
        return "right", fingers

    # 3. All fingers extended → move mouse
    if all(fingers.values()):
        return "move", fingers

    # 4. Transitional / partial open
    return "none", fingers
