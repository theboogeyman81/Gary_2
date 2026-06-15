import os
import math
import time

import cv2
import mediapipe as mp
import requests
from dotenv import load_dotenv

load_dotenv()

# --- Home Assistant credentials ---
HA_URL = os.getenv('HA_URL')
HA_TOKEN = os.getenv('HA_TOKEN')
ENTITY_ID = os.getenv('ENTITY_ID', 'light.smart_bulb_12_5w')

# --- Pinch detection settings ---
PINCH_ENTER_THRESHOLD = float(os.getenv('PINCH_ENTER_THRESHOLD', '0.05'))   # fingers must be THIS close to start pinch
PINCH_EXIT_THRESHOLD = float(os.getenv('PINCH_EXIT_THRESHOLD', '0.09'))    # fingers must spread THIS far to reset
PINCH_HOLD_DURATION = float(os.getenv('PINCH_HOLD_DURATION', '0.6'))       # seconds you must hold to fire
CAMERA_INDEX = int(os.getenv('CAMERA_INDEX', '0'))

HEADERS = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type": "application/json",
}


# ============ HOME ASSISTANT FUNCTIONS ============

def check_bulb_status():
    try:
        url = f"{HA_URL}/api/states/{ENTITY_ID}"
        r = requests.get(url, headers=HEADERS, timeout=3)
        if r.status_code == 200:
            return r.json().get("state") == "on"
        return False
    except Exception as e:
        print(f"Status check error: {e}")
        return False


def turn_on():
    try:
        requests.post(f"{HA_URL}/api/services/light/turn_on",
                      headers=HEADERS, json={"entity_id": ENTITY_ID}, timeout=3)
        print("💡 ON")
    except Exception as e:
        print(f"Turn on error: {e}")


def turn_off():
    try:
        requests.post(f"{HA_URL}/api/services/light/turn_off",
                      headers=HEADERS, json={"entity_id": ENTITY_ID}, timeout=3)
        print("🌑 OFF")
    except Exception as e:
        print(f"Turn off error: {e}")


def toggle_bulb(currently_on):
    if currently_on:
        turn_off()
    else:
        turn_on()


# ============ PINCH DETECTION ============

def normalized_distance(a, b, hand_size):
    """
    Distance between two landmarks, normalized by hand size.
    This way, pinch detection works whether your hand is close or far from camera.
    """
    raw = math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2)
    return raw / hand_size if hand_size > 0 else raw


def get_hand_size(landmarks):
    """
    Use distance from wrist (0) to middle finger MCP (9) as 'hand size'.
    This is roughly the palm length — stable reference no matter the camera distance.
    """
    wrist = landmarks[0]
    middle_mcp = landmarks[9]
    return math.sqrt((wrist.x - middle_mcp.x) ** 2 + (wrist.y - middle_mcp.y) ** 2)


def get_pinch_distance(hand_landmarks):
    """
    Returns normalized distance between thumb tip (4) and index tip (8).
    Smaller = more pinched.
    """
    if hand_landmarks is None:
        return None
    lm = hand_landmarks.landmark
    if len(lm) < 10:
        return None
    hand_size = get_hand_size(lm)
    return normalized_distance(lm[4], lm[8], hand_size)


# ============ MAIN ============

def main():
    print("Testing Home Assistant connection...")
    bulb_is_on = check_bulb_status()
    print(f"Bulb is currently: {'ON' if bulb_is_on else 'OFF'}\n")

    mp_hands = mp.solutions.hands
    hands = mp_hands.Hands(
        static_image_mode=False,
        max_num_hands=1,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.6,
    )

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print("Cannot open camera.")
        return

    # State machine variables
    pinch_state = "IDLE"          # IDLE → PINCHING → FIRED → WAITING_RELEASE → IDLE
    pinch_start_time = 0.0
    last_status_check = 0.0
    cached_status = bulb_is_on

    print("HOLD pinch (thumb + index) for ~0.6s to toggle bulb. Press 'q' to quit.\n")

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        frame = cv2.flip(frame, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb)

        pinch_dist = None
        if results.multi_hand_landmarks:
            pinch_dist = get_pinch_distance(results.multi_hand_landmarks[0])

        now = time.time()
        progress = 0.0   # 0.0 to 1.0 — for visual feedback

        # ===== STATE MACHINE =====
        if pinch_state == "IDLE":
            # Waiting for pinch to start
            if pinch_dist is not None and pinch_dist <= PINCH_ENTER_THRESHOLD:
                pinch_state = "PINCHING"
                pinch_start_time = now

        elif pinch_state == "PINCHING":
            # Holding pinch — count time
            if pinch_dist is None or pinch_dist > PINCH_EXIT_THRESHOLD:
                # User let go before hold completed → reset
                pinch_state = "IDLE"
            else:
                held_duration = now - pinch_start_time
                progress = min(held_duration / PINCH_HOLD_DURATION, 1.0)

                if held_duration >= PINCH_HOLD_DURATION:
                    # FIRE THE COMMAND
                    toggle_bulb(cached_status)
                    cached_status = not cached_status
                    pinch_state = "WAITING_RELEASE"

        elif pinch_state == "WAITING_RELEASE":
            # Wait until user fully opens hand before allowing another pinch
            if pinch_dist is None or pinch_dist > PINCH_EXIT_THRESHOLD:
                pinch_state = "IDLE"

        # ===== STATUS REFRESH (light polling) =====
        if (now - last_status_check) > 2.0:
            cached_status = check_bulb_status()
            last_status_check = now

        # ===== UI =====
        draw_ui(frame, cached_status, pinch_state, progress, pinch_dist)

        cv2.imshow("Pinch Hold to Toggle", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
    hands.close()


def draw_ui(frame, bulb_on, state, progress, pinch_dist):
    """Draw status, pinch state, and progress bar on the frame."""
    h, w = frame.shape[:2]

    # Status text
    status_text = f"Bulb: {'ON' if bulb_on else 'OFF'}"
    color = (0, 255, 0) if bulb_on else (100, 100, 100)
    cv2.putText(frame, status_text, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

    # State indicator
    state_colors = {
        "IDLE": (200, 200, 200),
        "PINCHING": (0, 255, 255),
        "WAITING_RELEASE": (0, 100, 255),
    }
    cv2.putText(frame, f"State: {state}", (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, state_colors.get(state, (255, 255, 255)), 2)

    # Pinch distance debug
    if pinch_dist is not None:
        cv2.putText(frame, f"Dist: {pinch_dist:.3f}", (10, 85),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)

    # Progress bar (only during PINCHING)
    if state == "PINCHING":
        bar_x, bar_y = 10, h - 40
        bar_w, bar_h = 300, 20
        # Background
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h),
                      (50, 50, 50), -1)
        # Filled portion
        filled_w = int(bar_w * progress)
        bar_color = (0, 255, 0) if progress >= 1.0 else (0, 200, 255)
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + filled_w, bar_y + bar_h),
                      bar_color, -1)
        # Border
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h),
                      (255, 255, 255), 1)
        cv2.putText(frame, f"{int(progress * 100)}%", (bar_x + bar_w + 10, bar_y + 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)


if __name__ == "__main__":
    main()