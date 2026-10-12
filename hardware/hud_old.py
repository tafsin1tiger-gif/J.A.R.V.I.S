"""
HUD.py -- A hand-tracking holographic-style interface overlay.

STACK (all $0):
  - Hand tracking: mediapipe (Google's free library)
  - Drawing:        opencv-python

SETUP:
    pip install opencv-python mediapipe numpy

RUN:
    python hud.py

- Move your hand in front of your webcam: the rings will follow your palm.
- Pinch your thumb and index finger together to "activate" (rings turn from
  cyan to orange, like a selection state).
- Press Q to quit.

NOTE FOR WEAK PCs: if this feels laggy, lower CAM_WIDTH/CAM_HEIGHT below,
or reduce RING_COUNT. Hand tracking is the heaviest part of this whole
project -- it's normal for this to use more CPU than the voice assistant.
"""

import cv2
import mediapipe as mp
import numpy as np
import time
import math

# ---------- CONFIG ----------
CAM_WIDTH, CAM_HEIGHT = 640, 480   # lower this (e.g. 480x360) if it's laggy
RING_COUNT = 4
COLOR_IDLE = (255, 220, 100)       # cyan-ish (BGR order for OpenCV)
COLOR_ACTIVE = (0, 140, 255)       # orange when "pinched"
PINCH_THRESHOLD = 40               # pixels; smaller = must pinch tighter

# ---------- MEDIAPIPE SETUP ----------
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    max_num_hands=1,
    min_detection_confidence=0.6,
    min_tracking_confidence=0.5,
)

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)

start_time = time.time()


def draw_hud(frame, center, active, counter_value):
    """Draw concentric rotating rings + readout around a center point."""
    overlay = frame.copy()
    t = time.time() - start_time
    color = COLOR_ACTIVE if active else COLOR_IDLE
    cx, cy = center

    for i in range(RING_COUNT):
        radius = 40 + i * 22
        thickness = 2
        # each ring rotates at a different speed/direction
        speed = 40 * (1 if i % 2 == 0 else -1)
        start_angle = (t * speed) % 360
        # draw ring as several arc segments (gives a "data ring" look)
        segments = 8
        gap = 10
        seg_len = (360 / segments) - gap
        for s in range(segments):
            a0 = start_angle + s * (360 / segments)
            a1 = a0 + seg_len
            cv2.ellipse(overlay, (cx, cy), (radius, radius), 0, a0, a1, color, thickness)

    # pulsing center dot
    pulse = 4 + int(3 * math.sin(t * 6))
    cv2.circle(overlay, (cx, cy), pulse, color, -1)

    # center readout number (like a status counter)
    text = str(counter_value)
    cv2.putText(overlay, text, (cx - 14, cy + 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1, cv2.LINE_AA)

    # small side "data" ticks for flavor
    for i in range(3):
        y = cy - 60 + i * 30
        cv2.line(overlay, (cx + 90, y), (cx + 130, y), color, 1)

    cv2.addWeighted(overlay, 0.85, frame, 0.15, 0, frame)
    return frame


def main():
    counter = 0
    frame_count = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame = cv2.flip(frame, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = hands.process(rgb)

        center = (CAM_WIDTH // 2, CAM_HEIGHT // 2)  # default: screen center
        active = False

        if result.multi_hand_landmarks:
            hand = result.multi_hand_landmarks[0]
            h, w, _ = frame.shape
            # palm center = average of wrist + middle finger base
            wrist = hand.landmark[0]
            middle_base = hand.landmark[9]
            cx = int((wrist.x + middle_base.x) / 2 * w)
            cy = int((wrist.y + middle_base.y) / 2 * h)
            center = (cx, cy)

            # pinch detection: distance between thumb tip (4) and index tip (8)
            thumb = hand.landmark[4]
            index = hand.landmark[8]
            dist = math.hypot((thumb.x - index.x) * w, (thumb.y - index.y) * h)
            active = dist < PINCH_THRESHOLD

        frame_count += 1
        if frame_count % 15 == 0:
            counter = (counter + 1) % 100

        frame = draw_hud(frame, center, active, counter)

        cv2.imshow("HUD", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
