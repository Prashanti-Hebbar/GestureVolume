# hand_volume_dashboard.py  (UI Enhanced Version Only)

import cv2
import mediapipe as mp
import numpy as np
from ctypes import cast, POINTER
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
import time

devices = AudioUtilities.GetSpeakers()
interface = devices.Activate(IAudioEndpointVolume._iid_, 0, None)
volume_interface = cast(interface, POINTER(IAudioEndpointVolume))

def set_system_volume_scalar(scalar: float):
    s = min(max(scalar, 0.0), 1.0)
    try:
        volume_interface.SetMasterVolumeLevelScalar(s, None)
    except:
        pass

mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    model_complexity=1,
    min_detection_confidence=0.6,
    min_tracking_confidence=0.5
)

FINGER_TO_PERCENT = {0: 0, 1: 20, 2: 40, 3: 60, 4: 80, 5: 100}
TIP_IDS = [4, 8, 12, 16, 20]
PIP_IDS = [3, 6, 10, 14, 18]

FRAME_W = 1280
FRAME_H = 720
PANEL_W = 420
CAM_W = FRAME_W - PANEL_W

cap = cv2.VideoCapture(0)
cap.set(3, FRAME_W)
cap.set(4, FRAME_H)

GRAD_START = np.array([176,160,61])
GRAD_END   = np.array([56,157,211])

prev_pct = None
last_set_time = 0
SET_DELAY = 0.12

fps_time = time.time()
fps = 0


def count_open_fingers(landmarks, handedness):
    lm = np.array([[p.x, p.y] for p in landmarks])
    fingers = 0

    for i in range(1, 5):
        if lm[TIP_IDS[i],1] < lm[PIP_IDS[i],1] - 0.02:
            fingers += 1

    thumb_tip = lm[TIP_IDS[0],0]
    thumb_ip  = lm[PIP_IDS[0],0]
    m = 0.02

    if handedness == "Right":
        if thumb_tip < thumb_ip - m:
            fingers += 1
    else:
        if thumb_tip > thumb_ip + m:
            fingers += 1

    return max(0, min(5, fingers))


def draw_hand_icon(img, x, y, color):
    cv2.circle(img, (x+18, y+12), 8, color, 2)
    cv2.line(img, (x+18, y+20), (x+18, y+35), color, 2)
    cv2.line(img, (x+12, y+25), (x+25, y+25), color, 2)

def draw_volume_icon(img, x, y, color):
    cv2.rectangle(img, (x, y+10), (x+14, y+25), color, 2)
    cv2.line(img, (x+16, y+12), (x+24, y+8), color, 2)
    cv2.line(img, (x+16, y+23), (x+24, y+27), color, 2)

def draw_fps_icon(img, x, y, color):
    cv2.circle(img, (x+14, y+20), 10, color, 2)
    cv2.line(img, (x+14, y+20), (x+14, y+10), color, 2)


def draw_control_panel(panel, volume_pct, fingers, fps_display):

    panel[:] = (25, 25, 25)

    # ------------------- FIXED TITLE HERE -------------------
    title = "HAND VOLUME DASHBOARD"
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 1
    thick = 3
    (tw, th), _ = cv2.getTextSize(title, font, scale, thick)
    x = (panel.shape[1] - tw) // 2
    y = 50
    cv2.putText(panel, title, (x, y), font, scale, (0,255,255), thick, cv2.LINE_AA)
    # --------------------------------------------------------

    cx, cy = panel.shape[1]//2, 170
    radius = 95
    thickness = 20

    cv2.circle(panel, (cx, cy), radius, (60,60,60), thickness, cv2.LINE_AA)

    end_angle = int(volume_pct * 3.6)
    for a in range(end_angle):
        t = a / 360
        color = (GRAD_START*(1-t) + GRAD_END*t).astype(int)
        cv2.ellipse(panel, (cx,cy), (radius,radius), 270,
                    a, a+1, tuple(map(int,color)), thickness, cv2.LINE_AA)

    txt = f"{volume_pct}%"
    cv2.putText(panel, txt, (cx-70, cy+20),
                cv2.FONT_HERSHEY_SIMPLEX, 2.2, (255,255,255), 5, cv2.LINE_AA)

    bx, by = 40, cy+130
    bw, bh = panel.shape[1]-80, 30

    cv2.rectangle(panel, (bx,by), (bx+bw,by+bh), (80,80,80), -1)
    cv2.rectangle(panel, (bx,by), (bx+bw,by+bh), (120,120,120), 2)

    fill = int((volume_pct/100)*bw)
    for i in range(fill):
        t = i/bw
        color = (GRAD_START*(1-t) + GRAD_END*t).astype(int)
        cv2.line(panel, (bx+i,by), (bx+i,by+bh), tuple(map(int,color)), 2)

    gx, gy = 20, by+70
    gw, gh = panel.shape[1]-40, 200

    overlay = panel.copy()
    cv2.rectangle(overlay, (gx,gy), (gx+gw,gy+gh), (255,255,255), -1)
    panel[:] = cv2.addWeighted(overlay, 0.09, panel, 0.91, 0)
    cv2.rectangle(panel, (gx,gy), (gx+gw,gy+gh), (70,255,90), 2)

    draw_hand_icon(panel, gx+20, gy+20, (70,255,120))
    cv2.putText(panel, f"Fingers: {fingers}", (gx+70, gy+50),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 3)

    draw_volume_icon(panel, gx+20, gy+85, (70,255,120))
    cv2.putText(panel, f"Volume: {volume_pct}%", (gx+70, gy+115),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 3)

    draw_fps_icon(panel, gx+20, gy+145, (70,255,120))
    cv2.putText(panel, f"FPS: {fps_display}", (gx+70, gy+175),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 3)


while True:
    ok, frame = cap.read()
    if not ok: break

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    res = hands.process(rgb)

    cam = cv2.resize(frame, (CAM_W, FRAME_H))
    fingers = 0
    volume_pct = prev_pct if prev_pct is not None else 0

    if res.multi_hand_landmarks:
        h_faces = res.multi_hand_landmarks[0]
        hand_label = "Right"
        if res.multi_handedness:
            hand_label = res.multi_handedness[0].classification[0].label

        for lm in h_faces.landmark:
            cx = int(lm.x * CAM_W)
            cy = int(lm.y * FRAME_H)
            cv2.circle(cam, (cx,cy), 6, (0,255,230), -1)

        fingers = count_open_fingers(h_faces.landmark, hand_label)
        volume_pct = FINGER_TO_PERCENT.get(fingers, 0)

        now = time.time()
        if prev_pct != volume_pct and now-last_set_time > SET_DELAY:
            set_system_volume_scalar(volume_pct/100)
            prev_pct = volume_pct
            last_set_time = now

    panel = np.zeros((FRAME_H, PANEL_W, 3), dtype=np.uint8)
    draw_control_panel(panel, volume_pct, fingers, fps)

    final = np.hstack((cam, panel))
    cv2.imshow("Hand Volume Dashboard", final)

    new = time.time()
    fps = int(1/(new-fps_time)) if new-fps_time>0 else fps
    fps_time = new

    if cv2.waitKey(1) & 0xFF in (27, ord('q')):
        break

cap.release()
cv2.destroyAllWindows()
