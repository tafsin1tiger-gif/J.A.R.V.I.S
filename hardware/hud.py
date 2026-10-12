"""
HUD.py -- Matches the reference JARVIS dashboard layout precisely:
top bar (title/status, clock, system status ring), left column (System,
Network, Storage, Power, Radar), center targeting reticle + Voice Command
bar, right column (Weather, Apps, Calendar, Notifications).

ACTIVE (pinch thumb+index together): the center reticle bursts into a
dense radiating spike pattern in warm gold/orange, spreading across the
whole screen.

Controls:
- Move your hand: the whole HUD glides to follow your palm.
- Pinch thumb + index finger: triggers the burst/active look.
- Q or Esc: quit.

SETUP (in addition to opencv-python and mediapipe):
    pip install pillow
"""

import cv2
import mediapipe as mp
import numpy as np
import time
import math
import random
import datetime
from PIL import Image, ImageDraw, ImageFont

# ---------- CONFIG ----------
CAM_WIDTH, CAM_HEIGHT = 480, 360
CANVAS_WIDTH, CANVAS_HEIGHT = 1280, 720
PROCESS_EVERY_N_FRAMES = 2

COLOR_IDLE = (255, 230, 90)      # BGR -- cyan/sky-blue, matches the reference
COLOR_ACTIVE = (30, 140, 255)    # BGR -- warm gold, pinch/burst state
COLOR_WHITE = (255, 255, 255)
COLOR_DIM = (160, 130, 60)       # dimmer version of idle color, for secondary text
PINCH_THRESHOLD = 40

PARTICLE_COUNT = 120
ENABLE_GLOW = True
GLOW_DOWNSCALE = 4

_FONT_CANDIDATES = [
    "C:\\Windows\\Fonts\\segoeuisl.ttf",
    "C:\\Windows\\Fonts\\segoeui.ttf",
    "C:\\Windows\\Fonts\\calibri.ttf",
    "C:\\Windows\\Fonts\\arial.ttf",
]
_FONT_BOLD_CANDIDATES = [
    "C:\\Windows\\Fonts\\segoeuib.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
]
_font_cache = {}


def get_font(size, bold=False):
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]
    candidates = _FONT_BOLD_CANDIDATES + _FONT_CANDIDATES if bold else _FONT_CANDIDATES
    for path in candidates:
        try:
            f = ImageFont.truetype(path, size)
            _font_cache[key] = f
            return f
        except (OSError, IOError):
            continue
    f = ImageFont.load_default()
    _font_cache[key] = f
    return f


mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    max_num_hands=1,
    model_complexity=0,
    min_detection_confidence=0.6,
    min_tracking_confidence=0.5,
)

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)

start_time = time.time()

random.seed(42)
particles = []
for i in range(PARTICLE_COUNT):
    band = i % 5
    base_radius = 30 + band * 22 + random.uniform(-4, 4)
    angle = random.uniform(0, 360)
    speed = (0.3 + 0.1 * band) * (1 if band % 2 == 0 else -1)
    particles.append({"radius": base_radius, "angle": angle, "speed": speed,
                       "phase": random.uniform(0, 6.28)})

sparkline_seed_a = random.uniform(0, 6.28)
sparkline_seed_b = random.uniform(0, 6.28)

text_queue = []


def queue_text(x, y, text, size, color_bgr, bold=False):
    text_queue.append((x, y, text, size, color_bgr, bold))


def flush_text(canvas):
    img = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img)
    for x, y, text, size, color_bgr, bold in text_queue:
        rgb = (color_bgr[2], color_bgr[1], color_bgr[0])
        draw.text((x, y), text, font=get_font(size, bold), fill=rgb)
    text_queue.clear()
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def tint_region(canvas, x, y, w, h, color, alpha=0.07):
    x2, y2 = min(x + w, CANVAS_WIDTH), min(y + h, CANVAS_HEIGHT)
    x, y = max(x, 0), max(y, 0)
    if x2 <= x or y2 <= y:
        return
    roi = canvas[y:y2, x:x2]
    fill = np.full_like(roi, color, dtype=np.uint8)
    cv2.addWeighted(fill, alpha, roi, 1 - alpha, 0, dst=roi)


def draw_panel_frame(canvas, x, y, w, h, color, label):
    tint_region(canvas, x, y, w, h, color, alpha=0.06)
    cv2.rectangle(canvas, (x, y), (x + w, y + h), color, 1, cv2.LINE_AA)
    queue_text(x + 10, y + 6, label, 13, color, bold=True)
    # small dotted decoration to the right of the title, like the reference
    for i in range(4):
        cv2.circle(canvas, (x + w - 14 - i * 7, y + 12), 1, color, -1, cv2.LINE_AA)


def draw_labeled_bar(canvas, x, y, w, color, label, value_text, percent):
    queue_text(x, y, label, 11, color)
    queue_text(x + w - len(value_text) * 7, y, value_text, 11, color)
    bar_y = y + 18
    bar_h = 4
    cv2.rectangle(canvas, (x, bar_y), (x + w, bar_y + bar_h), COLOR_DIM, 1, cv2.LINE_AA)
    fill_w = int(w * percent)
    if fill_w > 0:
        cv2.rectangle(canvas, (x, bar_y), (x + fill_w, bar_y + bar_h), color, -1, cv2.LINE_AA)


def draw_sparkline(canvas, x, y, w, h, color, t, seed, freq=3.2):
    pts = []
    steps = 28
    for i in range(steps + 1):
        px = x + int(w * i / steps)
        noise = math.sin(t * freq + i * 0.9 + seed) * 0.5 + math.sin(i * 1.7 + seed) * 0.3
        py = int(y + h / 2 - (h / 2 - 2) * noise)
        pts.append((px, py))
    cv2.polylines(canvas, [np.array(pts)], False, color, 1, cv2.LINE_AA)


# ---------- LEFT COLUMN ----------
def draw_left_column(canvas, color, t):
    x, w = 20, 260

    y, h = 90, 110
    draw_panel_frame(canvas, x, y, w, h, color, "SYSTEM")
    cpu = 20 + int(10 * (math.sin(t * 0.7) * 0.5 + 0.5))
    ram = 44 + int(8 * (math.sin(t * 0.5) * 0.5 + 0.5))
    swap = 14 + int(6 * (math.sin(t * 0.9) * 0.5 + 0.5))
    draw_labeled_bar(canvas, x + 12, y + 28, w - 24, color, "CPU Usage", f"{cpu}%", cpu / 100)
    draw_labeled_bar(canvas, x + 12, y + 56, w - 24, color, "RAM Usage", f"{ram}%", ram / 100)
    draw_labeled_bar(canvas, x + 12, y + 84, w - 24, color, "SWAP Usage", f"{swap}%", swap / 100)

    y += h + 10
    h = 120
    draw_panel_frame(canvas, x, y, w, h, color, "NETWORK")
    queue_text(x + 12, y + 28, "Upload", 11, color)
    queue_text(x + w - 90, y + 28, "12.4 Mbps", 11, color)
    draw_sparkline(canvas, x + 12, y + 44, w - 24, 22, color, t, sparkline_seed_a, freq=3.0)
    queue_text(x + 12, y + 74, "Download", 11, color)
    queue_text(x + w - 90, y + 74, "85.7 Mbps", 11, color)
    draw_sparkline(canvas, x + 12, y + 90, w - 24, 22, color, t, sparkline_seed_b, freq=2.3)

    y += h + 10
    h = 100
    draw_panel_frame(canvas, x, y, w, h, color, "STORAGE")
    draw_labeled_bar(canvas, x + 12, y + 26, w - 24, color, "C:\\", "62%", 0.62)
    queue_text(x + 12, y + 44, "465 GB / 740 GB", 9, COLOR_DIM)
    draw_labeled_bar(canvas, x + 12, y + 62, w - 24, color, "D:\\", "38%", 0.38)
    queue_text(x + 12, y + 80, "232 GB / 600 GB", 9, COLOR_DIM)

    y += h + 10
    h = 80
    draw_panel_frame(canvas, x, y, w, h, color, "POWER")
    draw_labeled_bar(canvas, x + 12, y + 28, w - 24, color, "AC Line", "100%", 1.0)
    draw_labeled_bar(canvas, x + 12, y + 56, w - 24, color, "Battery", "87%", 0.87)

    y += h + 10
    h = 130
    draw_panel_frame(canvas, x, y, w, h, color, "RADAR")
    rcx, rcy, rr = x + 70, y + 75, 42
    cv2.circle(canvas, (rcx, rcy), rr, color, 1, cv2.LINE_AA)
    cv2.circle(canvas, (rcx, rcy), rr * 2 // 3, color, 1, cv2.LINE_AA)
    cv2.circle(canvas, (rcx, rcy), rr // 3, color, 1, cv2.LINE_AA)
    a = math.radians((t * 90) % 360)
    cv2.line(canvas, (rcx, rcy), (int(rcx + rr * math.cos(a)), int(rcy + rr * math.sin(a))),
             color, 1, cv2.LINE_AA)
    for blip_a, blip_r in [(50, 0.55), (210, 0.4), (300, 0.8)]:
        a2 = math.radians(blip_a)
        bx = int(rcx + rr * blip_r * math.cos(a2))
        by = int(rcy + rr * blip_r * math.sin(a2))
        cv2.circle(canvas, (bx, by), 3, color, -1, cv2.LINE_AA)
    queue_text(x + 150, y + 60, "3", 22, color, bold=True)
    queue_text(x + 150, y + 88, "CONTACTS", 9, color)
    queue_text(x + 150, y + 100, "DETECTED", 9, color)


# ---------- RIGHT COLUMN ----------
def draw_cloud_icon(canvas, cx, cy, color):
    cv2.circle(canvas, (cx - 10, cy), 10, color, -1, cv2.LINE_AA)
    cv2.circle(canvas, (cx + 6, cy - 6), 13, color, -1, cv2.LINE_AA)
    cv2.circle(canvas, (cx + 18, cy + 2), 9, color, -1, cv2.LINE_AA)
    cv2.rectangle(canvas, (cx - 12, cy + 2), (cx + 20, cy + 12), color, -1, cv2.LINE_AA)


def draw_right_column(canvas, color, t):
    x, w = CANVAS_WIDTH - 280, 260

    y, h = 90, 150
    draw_panel_frame(canvas, x, y, w, h, color, "WEATHER")
    draw_cloud_icon(canvas, x + 30, y + 45, COLOR_WHITE)
    queue_text(x + 60, y + 28, "21", 26, COLOR_WHITE, bold=True)
    queue_text(x + 100, y + 32, "C", 16, COLOR_WHITE)
    queue_text(x + 60, y + 58, "PARTLY CLOUDY", 10, color)
    rows = [("Feels like:", "21 C"), ("Humidity:", "60%"), ("Wind:", "14 km/h"), ("Visibility:", "10 km")]
    for i, (label, val) in enumerate(rows):
        ry = y + 84 + i * 16
        queue_text(x + 12, ry, label, 10, COLOR_DIM)
        queue_text(x + w - 60, ry, val, 10, color)

    y += h + 10
    h = 140
    draw_panel_frame(canvas, x, y, w, h, color, "APPS")
    apps = [("Chrome", True), ("VS Code", True), ("Spotify", True), ("Discord", False)]
    for i, (name, active) in enumerate(apps):
        ry = y + 30 + i * 26
        queue_text(x + 12, ry, name, 12, color)
        status = "ACTIVE" if active else "IDLE"
        stat_color = color if active else COLOR_DIM
        cv2.circle(canvas, (x + w - 70, ry + 6), 3, stat_color, -1, cv2.LINE_AA)
        queue_text(x + w - 58, ry, status, 9, stat_color)

    y += h + 10
    h = 140
    draw_panel_frame(canvas, x, y, w, h, color, "CALENDAR")
    now = datetime.datetime.now()
    queue_text(x + 12, y + 28, now.strftime("%B %d, %Y"), 11, COLOR_WHITE)
    events = [("Meeting with Team", "10:00 AM"), ("Project Deadline", "3:00 PM"), ("Gym Session", "7:00 PM")]
    for i, (name, when) in enumerate(events):
        ry = y + 56 + i * 24
        cv2.circle(canvas, (x + 16, ry + 5), 2, color, -1, cv2.LINE_AA)
        queue_text(x + 24, ry, name, 10, color)
        queue_text(x + w - 65, ry, when, 9, COLOR_DIM)

    y += h + 10
    h = 130
    draw_panel_frame(canvas, x, y, w, h, color, "NOTIFICATIONS")
    notifs = ["System Update Available", "New Email from John", "Calendar Event in 30 min"]
    for i, text in enumerate(notifs):
        ry = y + 30 + i * 28
        cv2.circle(canvas, (x + 16, ry + 5), 3, color, -1, cv2.LINE_AA)
        queue_text(x + 26, ry, text, 10, color)


# ---------- TOP BAR ----------
def draw_top_bar(canvas, color, t):
    queue_text(24, 14, "JARVIS", 26, COLOR_WHITE, bold=True)
    cv2.circle(canvas, (150, 26), 4, color, -1, cv2.LINE_AA)
    queue_text(162, 18, "ONLINE", 12, color)

    now = datetime.datetime.now()
    time_str = now.strftime("%H:%M:%S")
    date_str = now.strftime("%A, %B %d, %Y").upper()
    queue_text(CANVAS_WIDTH // 2 - 55, 8, time_str, 22, color, bold=True)
    queue_text(CANVAS_WIDTH // 2 - 100, 34, date_str, 10, COLOR_WHITE)

    queue_text(CANVAS_WIDTH - 190, 18, "SYSTEM STATUS", 11, color)
    badge_x, badge_y = CANVAS_WIDTH - 40, 26
    cv2.circle(canvas, (badge_x, badge_y), 16, color, 1, cv2.LINE_AA)
    pct = 0.9 + 0.08 * math.sin(t)
    cv2.ellipse(canvas, (badge_x, badge_y), (16, 16), 0, -90, -90 + pct * 360, color, 2, cv2.LINE_AA)
    queue_text(badge_x - 12, badge_y - 8, f"{int(pct*100)}", 11, COLOR_WHITE, bold=True)


# ---------- CENTER RETICLE ----------
def draw_reticle(canvas, center, color, t):
    cx, cy = center
    # outer dashed ring (white, like the reference)
    outer_r = 195
    segs = 48
    seg_len = 360 / segs * 0.55
    for s in range(segs):
        a0 = s * (360 / segs)
        cv2.ellipse(canvas, (cx, cy), (outer_r, outer_r), 0, a0, a0 + seg_len,
                    COLOR_WHITE, 1, cv2.LINE_AA)

    # cardinal bracket accents just outside the outer ring
    for ang in [0, 90, 180, 270]:
        a = math.radians(ang)
        bx = int(cx + (outer_r + 18) * math.cos(a))
        by = int(cy + (outer_r + 18) * math.sin(a))
        cv2.rectangle(canvas, (bx - 4, by - 4), (bx + 4, by + 4), color, 1, cv2.LINE_AA)

    # tick-mark belt ring
    belt_r = 165
    for i in range(72):
        a = math.radians(i * 5)
        x1 = int(cx + (belt_r - 6) * math.cos(a))
        y1 = int(cy + (belt_r - 6) * math.sin(a))
        x2 = int(cx + belt_r * math.cos(a))
        y2 = int(cy + belt_r * math.sin(a))
        cv2.line(canvas, (x1, y1), (x2, y2), color, 1, cv2.LINE_AA)

    # denser inner tick belt
    belt2_r = 120
    for i in range(90):
        a = math.radians(i * 4)
        x1 = int(cx + (belt2_r - 8) * math.cos(a))
        y1 = int(cy + (belt2_r - 8) * math.sin(a))
        x2 = int(cx + belt2_r * math.cos(a))
        y2 = int(cy + belt2_r * math.sin(a))
        cv2.line(canvas, (x1, y1), (x2, y2), color, 1, cv2.LINE_AA)

    # rotating segmented core rings
    for i in range(3):
        radius = 40 + i * 22
        speed = 40 * (1 if i % 2 == 0 else -1)
        start_angle = (t * speed) % 360
        segments = 12
        seg_len2 = (360 / segments) - 8
        for s in range(segments):
            a0 = start_angle + s * (360 / segments)
            cv2.ellipse(canvas, (cx, cy), (radius, radius), 0, a0, a0 + seg_len2,
                        color, 2, cv2.LINE_AA)

    pulse = 5 + int(3 * math.sin(t * 6))
    cv2.circle(canvas, (cx, cy), pulse, color, -1, cv2.LINE_AA)


def draw_particle_field(canvas, center, color, t, intensity):
    cx, cy = center
    for p in particles:
        angle = math.radians(p["angle"] + t * p["speed"] * 20)
        radius = p["radius"] * (1 + intensity * (1.6 + 0.4 * math.sin(t * 8 + p["phase"])))
        x = int(cx + radius * math.cos(angle))
        y = int(cy + radius * math.sin(angle))
        if intensity > 0.05:
            inner = int(cx + (radius * 0.15) * math.cos(angle))
            inner_y = int(cy + (radius * 0.15) * math.sin(angle))
            cv2.line(canvas, (inner, inner_y), (x, y), color, 1, cv2.LINE_AA)
        else:
            cv2.circle(canvas, (x, y), 1, color, -1, cv2.LINE_AA)


def draw_voice_command(canvas, color, t, active):
    x, y, w, h = 300, 570, 680, 120
    draw_panel_frame(canvas, x, y, w, h, color, "VOICE COMMAND")

    bar_area_w = w - 130
    bars = 46
    bw = bar_area_w / bars
    for i in range(bars):
        level = abs(math.sin(t * 5 + i * 0.5)) * 0.7 + 0.1
        bar_h = int(level * (h - 60))
        bx = int(x + 16 + i * bw)
        by = y + h - 32
        cv2.rectangle(canvas, (bx, by - bar_h), (int(bx + bw - 2), by), color, -1, cv2.LINE_AA)

    queue_text(x + 16, y + h - 22, "Listening..." if not active else "Processing...", 11, color)

    mic_cx, mic_cy, mic_r = x + w - 55, y + h // 2, 34
    cv2.circle(canvas, (mic_cx, mic_cy), mic_r, color, 2, cv2.LINE_AA)
    cv2.rectangle(canvas, (mic_cx - 7, mic_cy - 14), (mic_cx + 7, mic_cy + 4), color, -1, cv2.LINE_AA)
    cv2.ellipse(canvas, (mic_cx, mic_cy), (12, 12), 0, 0, 180, color, 2, cv2.LINE_AA)
    cv2.line(canvas, (mic_cx, mic_cy + 12), (mic_cx, mic_cy + 18), color, 2, cv2.LINE_AA)


def apply_glow(canvas):
    small = cv2.resize(canvas, (CANVAS_WIDTH // GLOW_DOWNSCALE, CANVAS_HEIGHT // GLOW_DOWNSCALE))
    small = cv2.GaussianBlur(small, (0, 0), sigmaX=4)
    glow = cv2.resize(small, (CANVAS_WIDTH, CANVAS_HEIGHT))
    return cv2.addWeighted(canvas, 1.0, glow, 0.32, 0)


def draw_hud(canvas, center, active, t):
    canvas[:] = 0
    color = COLOR_ACTIVE if active else COLOR_IDLE

    draw_top_bar(canvas, color, t)
    draw_left_column(canvas, color, t)
    draw_right_column(canvas, color, t)
    draw_reticle(canvas, center, color, t)

    intensity = 1.0 if active else 0.0
    draw_particle_field(canvas, center, color, t, intensity)

    draw_voice_command(canvas, color, t, active)

    canvas = flush_text(canvas)
    if ENABLE_GLOW:
        canvas = apply_glow(canvas)
    return canvas


def main():
    frame_count = 0
    cam_center = (CAM_WIDTH // 2, CAM_HEIGHT // 2)
    active = False

    cv2.namedWindow("HUD", cv2.WND_PROP_FULLSCREEN)
    cv2.setWindowProperty("HUD", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    canvas = np.zeros((CANVAS_HEIGHT, CANVAS_WIDTH, 3), dtype=np.uint8)

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame = cv2.flip(frame, 1)

        if frame_count % PROCESS_EVERY_N_FRAMES == 0:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = hands.process(rgb)
            if result.multi_hand_landmarks:
                hand = result.multi_hand_landmarks[0]
                h, w, _ = frame.shape
                wrist = hand.landmark[0]
                middle_base = hand.landmark[9]
                cx = int((wrist.x + middle_base.x) / 2 * w)
                cy = int((wrist.y + middle_base.y) / 2 * h)
                cam_center = (cx, cy)

                thumb = hand.landmark[4]
                index = hand.landmark[8]
                dist = math.hypot((thumb.x - index.x) * w, (thumb.y - index.y) * h)
                active = dist < PINCH_THRESHOLD
            else:
                active = False

        frame_count += 1

        raw_x = cam_center[0] / CAM_WIDTH * CANVAS_WIDTH
        raw_y = cam_center[1] / CAM_HEIGHT * CANVAS_HEIGHT
        cx = int(min(max(raw_x, 340), CANVAS_WIDTH - 340))
        cy = int(min(max(raw_y, 220), 420))
        canvas_center = (cx, cy)

        t = time.time() - start_time
        canvas = draw_hud(canvas, canvas_center, active, t)

        cv2.imshow("HUD", canvas)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q") or key == 27:
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
