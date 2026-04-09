"""
IronHand - Iron Man Style Gesture Controller
Gesture control + Air Keyboard (JARVIS style)
"""

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
import pyautogui
import numpy as np
import time
import platform
import urllib.request
import os

# ── Volume control imports ───────────────────────────────────────────────────
PYCAW_AVAILABLE = False
if platform.system() == "Windows":
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        PYCAW_AVAILABLE = True
    except Exception:
        pass
elif platform.system() == "Darwin":
    import subprocess

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.01

# ── Download MediaPipe model ─────────────────────────────────────────────────
MODEL_PATH = "hand_landmarker.task"
MODEL_URL  = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
if not os.path.exists(MODEL_PATH):
    print("Downloading MediaPipe hand model... (~5MB, one time only)")
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    print("Done!")

# ── MediaPipe setup ──────────────────────────────────────────────────────────
BaseOptions           = mp_python.BaseOptions
HandLandmarker        = vision.HandLandmarker
HandLandmarkerOptions = vision.HandLandmarkerOptions
VisionRunningMode     = vision.RunningMode

options = HandLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=MODEL_PATH),
    running_mode=VisionRunningMode.IMAGE,
    num_hands=1,
    min_hand_detection_confidence=0.6,
    min_hand_presence_confidence=0.6,
    min_tracking_confidence=0.6
)
detector = HandLandmarker.create_from_options(options)

# ── Colours ──────────────────────────────────────────────────────────────────
HUD_COLOR  = (0, 255, 200)
DIM_COLOR  = (0, 160, 120)
RED_COLOR  = (0, 80,  255)
KEY_COLOR  = (0, 255, 200)   # normal key border
HOV_COLOR  = (0, 255, 255)   # hovered key border
TYP_COLOR  = (0, 200, 255)   # typed text colour
FONT       = cv2.FONT_HERSHEY_SIMPLEX

# ── Keyboard layout ──────────────────────────────────────────────────────────
KB_ROWS = [
    ["Q","W","E","R","T","Y","U","I","O","P"],
    ["A","S","D","F","G","H","J","K","L"],
    ["Z","X","C","V","B","N","M"],
]
DWELL_TIME = 0.5   # seconds finger must hover before key fires

# ── Volume ───────────────────────────────────────────────────────────────────
def set_volume(direction):
    try:
        if platform.system() == "Windows" and PYCAW_AVAILABLE:
            devices   = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume    = cast(interface, POINTER(IAudioEndpointVolume))
            current   = volume.GetMasterVolumeLevelScalar()
            new_vol   = min(1.0, current+0.1) if direction=="up" else max(0.0, current-0.1)
            volume.SetMasterVolumeLevelScalar(new_vol, None)
            return int(new_vol * 100)
        elif platform.system() == "Darwin":
            r = subprocess.run(["osascript","-e","output volume of (get volume settings)"],
                               capture_output=True, text=True)
            cur = int(r.stdout.strip())
            nv  = min(100,cur+10) if direction=="up" else max(0,cur-10)
            subprocess.run(["osascript","-e",f"set volume output volume {nv}"])
            return nv
        else:
            pyautogui.press("volumeup" if direction=="up" else "volumedown")
    except Exception:
        pass
    return -1

# ── Finger states ─────────────────────────────────────────────────────────────
def get_finger_states(lm):
    tips=[4,8,12,16,20]; pip=[3,6,10,14,18]
    s = [lm[4].x < lm[3].x]
    for i in range(1,5):
        s.append(lm[tips[i]].y < lm[pip[i]].y)
    return s   # [thumb, index, middle, ring, pinky]

# ── Gesture recognition ───────────────────────────────────────────────────────
def detect_gesture(lm, fs):
    thumb,index,middle,ring,pinky = fs
    if all(fs):                                                    return "OPEN_PALM","Volume UP"
    if not any(fs):                                                return "FIST",     "Volume DOWN"
    if index and not middle and not ring and not pinky:            return "POINT_UP", "Scroll UP"
    if index and middle and not ring and not pinky:                return "PEACE",    "Scroll DOWN"
    if index and middle and ring and not pinky and not thumb:      return "THREE_UP", "Alt + Tab"
    if thumb and not index and not middle and not ring and not pinky: return "THUMBS_UP","Play/Pause"
    dist = ((lm[4].x-lm[8].x)**2+(lm[4].y-lm[8].y)**2)**0.5
    if dist < 0.05:                                                return "PINCH",    "Click"
    return "NONE","---"

# ── Draw hand landmarks ───────────────────────────────────────────────────────
CONNECTIONS=[(0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),(5,9),(9,10),
             (10,11),(11,12),(9,13),(13,14),(14,15),(15,16),(13,17),(17,18),
             (18,19),(19,20),(0,17)]

def draw_landmarks(frame, lm):
    h,w = frame.shape[:2]
    pts = [(int(p.x*w),int(p.y*h)) for p in lm]
    for a,b in CONNECTIONS:
        cv2.line(frame,pts[a],pts[b],DIM_COLOR,1,cv2.LINE_AA)
    for pt in pts:
        cv2.circle(frame,pt,4,HUD_COLOR,-1,cv2.LINE_AA)

# ── Build keyboard key rects ──────────────────────────────────────────────────
def build_keys(frame_w, frame_h):
    """Returns list of (label, x, y, w, h) for every key."""
    keys     = []
    key_w    = 52
    key_h    = 48
    gap      = 8
    start_y  = frame_h - 220   # keyboard sits in lower portion

    for row_i, row in enumerate(KB_ROWS):
        total_w = len(row)*(key_w+gap) - gap
        start_x = (frame_w - total_w) // 2 + row_i * 16  # slight indent per row
        for col_i, letter in enumerate(row):
            x = start_x + col_i*(key_w+gap)
            y = start_y + row_i*(key_h+gap)
            keys.append((letter, x, y, key_w, key_h))
    return keys

# ── Draw keyboard overlay ─────────────────────────────────────────────────────
def draw_keyboard(frame, keys, hovered_key, dwell_progress):
    overlay = frame.copy()
    for (label, x, y, w, h) in keys:
        is_hovered = (label == hovered_key)
        # Dark semi-transparent background per key
        cv2.rectangle(overlay, (x,y), (x+w,y+h), (0,0,0), -1)
        cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
        overlay = frame.copy()

        border_col = HOV_COLOR if is_hovered else KEY_COLOR
        cv2.rectangle(frame, (x,y), (x+w,y+h), border_col, 1, cv2.LINE_AA)

        # Dwell fill
        if is_hovered and dwell_progress > 0:
            fill_h = int(h * dwell_progress)
            cv2.rectangle(frame, (x, y+h-fill_h), (x+w, y+h),
                          (0,180,160), -1)

        # Key label
        txt_size = cv2.getTextSize(label, FONT, 0.55, 1)[0]
        tx = x + (w - txt_size[0])//2
        ty = y + (h + txt_size[1])//2
        cv2.putText(frame, label, (tx,ty), FONT, 0.55,
                    (255,255,255) if is_hovered else HUD_COLOR, 1, cv2.LINE_AA)

# ── Main HUD ──────────────────────────────────────────────────────────────────
def draw_hud(frame, gesture_name, gesture_label, volume_pct, fps,
             cooldown_active, kb_mode, typed_text):
    h,w = frame.shape[:2]

    # Top bar
    ov = frame.copy()
    cv2.rectangle(ov,(0,0),(w,92),(0,0,0),-1)
    cv2.addWeighted(ov,0.55,frame,0.45,0,frame)

    cv2.putText(frame,"IRONHAND  v1.0",(14,26),FONT,0.65,HUD_COLOR,1,cv2.LINE_AA)
    cv2.putText(frame,f"FPS: {fps:.0f}",(w-110,26),FONT,0.55,DIM_COLOR,1,cv2.LINE_AA)

    mode_label = "[ KEYBOARD MODE ]" if kb_mode else gesture_name
    mode_col   = TYP_COLOR if kb_mode else (RED_COLOR if cooldown_active else HUD_COLOR)
    cv2.putText(frame,f"Gesture : {mode_label}",(14,56),FONT,0.6,mode_col,1,cv2.LINE_AA)
    cv2.putText(frame,f"Action  : {gesture_label}",(14,80),FONT,0.6,DIM_COLOR,1,cv2.LINE_AA)

    # Typed text bar (shown always, prominent in KB mode)
    if kb_mode:
        ov2 = frame.copy()
        cv2.rectangle(ov2,(0,h-60),(w,h),(0,0,0),-1)
        cv2.addWeighted(ov2,0.6,frame,0.4,0,frame)
        display = typed_text[-42:] if len(typed_text)>42 else typed_text
        cv2.putText(frame,f"> {display}_",(14,h-22),FONT,0.6,TYP_COLOR,1,cv2.LINE_AA)
        cv2.putText(frame,"Fist=Backspace  Thumb=Space  Both Fists=Exit KB",
                    (14,h-6),FONT,0.38,DIM_COLOR,1,cv2.LINE_AA)
    else:
        if volume_pct >= 0:
            ov2=frame.copy()
            cv2.rectangle(ov2,(0,h-60),(w,h),(0,0,0),-1)
            cv2.addWeighted(ov2,0.55,frame,0.45,0,frame)
            bx,by,bw,bh = 14,h-40,200,14
            filled = int(bw*volume_pct/100)
            cv2.rectangle(frame,(bx,by),(bx+bw,by+bh),DIM_COLOR,1)
            cv2.rectangle(frame,(bx,by),(bx+filled,by+bh),HUD_COLOR,-1)
            cv2.putText(frame,f"VOL {volume_pct}%",(bx+bw+10,by+11),FONT,0.5,HUD_COLOR,1,cv2.LINE_AA)
            cv2.putText(frame,"[4 fingers up = Keyboard Mode]",(bx+bw+80,by+11),FONT,0.38,DIM_COLOR,1,cv2.LINE_AA)

    # Corner brackets
    s,t = 22,2
    for p in [((0,0),(s,0)),((0,0),(0,s)),((w-s,0),(w,0)),((w,0),(w,s)),
              ((0,h-s),(0,h)),((0,h),(s,h)),((w-s,h),(w,h)),((w,h-s),(w,h))]:
        cv2.line(frame,p[0],p[1],HUD_COLOR,t)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("ERROR: Could not open webcam.")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    # Read actual resolution
    fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    keys = build_keys(fw, fh)

    current_volume  = 50
    last_action     = 0
    COOLDOWN        = 1.0
    prev_time       = time.time()

    # Keyboard state
    kb_mode         = False
    typed_text      = ""
    hovered_key     = None
    hover_start     = 0.0
    last_key_fired  = None
    key_fire_time   = 0.0

    print("\n IronHand started!")
    print("  Open Palm      -> Volume UP")
    print("  Closed Fist    -> Volume DOWN")
    print("  Index Up       -> Scroll UP")
    print("  Peace Sign     -> Scroll DOWN")
    print("  3 Fingers Up   -> Alt+Tab")
    print("  Thumbs Up      -> Play/Pause")
    print("  Pinch          -> Left Click")
    print("  4 Fingers Up   -> Toggle Keyboard Mode")
    print("  Press Q to quit\n")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("ERROR: Lost camera feed.")
            break

        frame    = cv2.flip(frame, 1)
        rgb      = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result   = detector.detect(mp_image)

        gesture_name    = "NO HAND"
        gesture_label   = "---"
        cooldown_active = (time.time() - last_action) < COOLDOWN
        dwell_progress  = 0.0

        if result.hand_landmarks:
            lm = result.hand_landmarks[0]
            draw_landmarks(frame, lm)
            fs = get_finger_states(lm)
            thumb,index,middle,ring,pinky = fs

            # ── 4 fingers up = toggle keyboard mode ──────────────────────
            four_up = index and middle and ring and pinky and not thumb
            if four_up and not cooldown_active:
                kb_mode      = not kb_mode
                last_action  = time.time()
                hovered_key  = None
                gesture_name  = "FOUR_UP"
                gesture_label = "Keyboard ON" if kb_mode else "Keyboard OFF"

            elif kb_mode:
                # ── KEYBOARD MODE ─────────────────────────────────────────
                gesture_name  = "KB MODE"
                gesture_label = "Hover to type"

                # Fist = backspace
                if not any(fs) and not cooldown_active:
                    if typed_text:
                        typed_text = typed_text[:-1]
                        pyautogui.press("backspace")
                    last_action   = time.time()
                    gesture_label = "Backspace"

                # Thumbs up = space
                elif thumb and not index and not middle and not ring and not pinky and not cooldown_active:
                    typed_text   += " "
                    pyautogui.press("space")
                    last_action   = time.time()
                    gesture_label = "Space"

                else:
                    # Track index fingertip for key hover
                    ix = int(lm[8].x * fw)
                    iy = int(lm[8].y * fh)

                    # Draw fingertip cursor
                    cv2.circle(frame, (ix,iy), 10, HOV_COLOR, 2, cv2.LINE_AA)
                    cv2.circle(frame, (ix,iy),  3, HOV_COLOR, -1, cv2.LINE_AA)

                    found_key = None
                    for (label,kx,ky,kw,kh) in keys:
                        if kx <= ix <= kx+kw and ky <= iy <= ky+kh:
                            found_key = label
                            break

                    now = time.time()
                    if found_key:
                        if found_key == hovered_key:
                            elapsed        = now - hover_start
                            dwell_progress = min(elapsed / DWELL_TIME, 1.0)

                            # Fire key after dwell
                            if elapsed >= DWELL_TIME:
                                # Prevent re-firing same key immediately
                                if found_key != last_key_fired or (now - key_fire_time) > 1.0:
                                    pyautogui.press(found_key.lower())
                                    typed_text    += found_key
                                    last_key_fired = found_key
                                    key_fire_time  = now
                                    hover_start    = now   # reset so it doesn't spam
                        else:
                            hovered_key = found_key
                            hover_start = now
                            dwell_progress = 0.0
                    else:
                        hovered_key    = None
                        dwell_progress = 0.0

                # Draw keyboard
                draw_keyboard(frame, keys, hovered_key, dwell_progress)

            else:
                # ── GESTURE CONTROL MODE ──────────────────────────────────
                gesture_name, gesture_label = detect_gesture(lm, fs)

                if not cooldown_active and gesture_name != "NONE":
                    last_action = time.time()
                    if   gesture_name == "OPEN_PALM":
                        vol = set_volume("up");   current_volume = vol if vol>=0 else current_volume
                    elif gesture_name == "FIST":
                        vol = set_volume("down"); current_volume = vol if vol>=0 else current_volume
                    elif gesture_name == "POINT_UP":  pyautogui.scroll(300)
                    elif gesture_name == "PEACE":     pyautogui.scroll(-300)
                    elif gesture_name == "THREE_UP":  pyautogui.hotkey("alt","tab")
                    elif gesture_name == "THUMBS_UP": pyautogui.press("playpause")
                    elif gesture_name == "PINCH":     pyautogui.click()

        now       = time.time()
        fps       = 1.0 / max(now - prev_time, 0.001)
        prev_time = now

        draw_hud(frame, gesture_name, gesture_label, current_volume,
                 fps, cooldown_active, kb_mode, typed_text)

        cv2.imshow("IronHand - JARVIS Interface", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    detector.close()
    print("IronHand stopped.")

if __name__ == "__main__":
    main()