import streamlit as st
import cv2
import mediapipe as mp
import math
import time
import platform
import threading
import traceback

# ============================================
# STREAMLIT SETUP
# ============================================
st.set_page_config(page_title="Gesture Volume", layout="wide")

st.markdown("""
<style>
    .stApp {
        background: linear-gradient(to bottom right, #111827, #1f2937);
        color: #ffffff;
        font-family: 'Segoe UI', sans-serif;
    }
    h1, h2 { 
        color: #10b981 !important; 
        text-align:center; 
    }
    .stSidebar { background-color: #0f172a !important; }
</style>
""", unsafe_allow_html=True)

# ============================================
# SIDEBAR
# ============================================
with st.sidebar:
    st.markdown("### GestureVolume")
    run = st.toggle("▶️ Run Detection", False)
    camera_index = st.number_input("📷 Camera Index", 0, 4, 0)
    min_det_conf = st.slider("Detection Confidence", 0.1, 1.0, 0.6)
    min_track_conf = st.slider("Tracking Confidence", 0.1, 1.0, 0.6)
    st.markdown("---")
    st.caption("💡 If camera doesn’t start, switch camera index or close other apps.")

# ============================================
# HEADER
# ============================================
st.markdown("<h1>Gesture Volume Control</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align:center;'>Pinch gesture controls your Windows system volume.</p>", unsafe_allow_html=True)

# ============================================
# GLOBALS
# ============================================
hotkeys_started = False
hotkey_stop = threading.Event()
hotkey_error = None

volume_thread_started = False
volume_stop = threading.Event()
requested_volume = None
volume_lock = threading.Lock()

sys_set_volume = None

latest_frame = None
frame_lock = threading.Lock()
camera_running = False
camera_thread_obj = None

# ============================================
# HOTKEYS (WINDOWS ONLY)
# ============================================
if platform.system() == "Windows":
    try:
        import keyboard
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL, CoInitialize, CoUninitialize, GUID
        from comtypes.client import CreateObject
        from functools import wraps
        from pycaw.pycaw import IAudioEndpointVolume, IMMDeviceEnumerator

        STEP_PERCENT = 5.0
        eRender = 0
        eCapture = 1
        eConsole = 0

        def ensure_com(func):
            @wraps(func)
            def wrapper(*a, **k):
                CoInitialize()
                try:
                    return func(*a, **k)
                finally:
                    try: CoUninitialize()
                    except: pass
            return wrapper

        def _create_enum():
            try:
                return CreateObject("MMDeviceEnumerator.MMDeviceEnumerator", interface=IMMDeviceEnumerator)
            except Exception:
                clsid = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
                return CreateObject(clsid, interface=IMMDeviceEnumerator)

        def _get_mic_volume():
            enum = _create_enum()
            dev = enum.GetDefaultAudioEndpoint(eCapture, eConsole)
            iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            return cast(iface, POINTER(IAudioEndpointVolume))

        def _get_system_volume():
            enum = _create_enum()
            dev = enum.GetDefaultAudioEndpoint(eRender, eConsole)
            iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            return cast(iface, POINTER(IAudioEndpointVolume))

        def _pct_to_scalar(p): return max(0.0, min(1.0, p / 100.0))
        def _scalar_to_pct(s): return max(0.0, min(100.0, s * 100.0))

        @ensure_com
        def sys_up():
            v = _get_system_volume()
            cur = v.GetMasterVolumeLevelScalar()
            v.SetMasterVolumeLevelScalar(min(1.0, cur + STEP_PERCENT / 100.0), None)

        @ensure_com
        def sys_down():
            v = _get_system_volume()
            cur = v.GetMasterVolumeLevelScalar()
            v.SetMasterVolumeLevelScalar(max(0.0, cur - STEP_PERCENT / 100.0), None)

        @ensure_com
        def sys_toggle_mute():
            v = _get_system_volume()
            v.SetMute(1 if not bool(v.GetMute()) else 0, None)

        @ensure_com
        def _sys_set_volume(percent):
            v = _get_system_volume()
            scalar = max(0.0, min(1.0, percent / 100.0))
            v.SetMasterVolumeLevelScalar(scalar, None)

        sys_set_volume = _sys_set_volume

        def hotkey_runner():
            try: keyboard.unhook_all()
            except: pass

            keyboard.add_hotkey("ctrl+alt+right", sys_up)
            keyboard.add_hotkey("ctrl+alt+left", sys_down)
            keyboard.add_hotkey("ctrl+alt+shift+m", sys_toggle_mute)
            keyboard.add_hotkey("ctrl+alt+q", lambda: hotkey_stop.set())

            while not hotkey_stop.is_set():
                time.sleep(0.1)

        def start_hotkeys():
            global hotkeys_started
            if not hotkeys_started:
                threading.Thread(target=hotkey_runner, daemon=True).start()
                hotkeys_started = True

    except Exception as e:
        hotkey_error = str(e) + "\n" + traceback.format_exc()

if platform.system() == "Windows":
    if hotkey_error:
        st.error("Hotkeys failed:\n" + hotkey_error)
    else:
        if not hotkeys_started:
            start_hotkeys()
            st.success("🎧 Hotkeys active (Ctrl + Alt + Q to stop)")
else:
    st.warning("Hotkeys work only on Windows.")

# ============================================
# BACKGROUND VOLUME WORKER
# ============================================
def volume_worker(poll_interval=0.15):
    last_sent = None
    while not volume_stop.is_set():
        time.sleep(poll_interval)
        with volume_lock:
            vol = requested_volume
        if vol is None or vol == last_sent:
            continue
        last_sent = vol
        try:
            if platform.system() == "Windows" and sys_set_volume:
                sys_set_volume(vol)
        except:
            pass

if not volume_thread_started:
    threading.Thread(target=volume_worker, daemon=True).start()
    volume_thread_started = True

# ============================================
# GESTURE → VOLUME MAP
# ============================================
def map_distance_to_volume(dist, min_d=20, max_d=200):
    dist_clamped = max(min_d, min(max_d, dist))
    return int((dist_clamped - min_d) * 100 / (max_d - min_d))

# ============================================
# CAMERA BACKGROUND THREAD
# ============================================
mp_hands = mp.solutions.hands
mp_draw = mp.solutions.drawing_utils

def camera_capture_thread(cam_index, det_conf, track_conf):
    global latest_frame, camera_running

    cap = cv2.VideoCapture(int(cam_index))
    if not cap.isOpened():
        camera_running = False
        return

    hands = mp_hands.Hands(
        static_image_mode=False,
        model_complexity=1,
        min_detection_confidence=det_conf,
        min_tracking_confidence=track_conf,
        max_num_hands=1
    )

    while camera_running:
        ok, frame = cap.read()
        if not ok:
            continue

        frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]
        results = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

        if results.multi_hand_landmarks:
            lm = results.multi_hand_landmarks[0]
            mp_draw.draw_landmarks(frame, lm, mp_hands.HAND_CONNECTIONS)

            x4, y4 = int(lm.landmark[4].x * w), int(lm.landmark[4].y * h)
            x8, y8 = int(lm.landmark[8].x * w), int(lm.landmark[8].y * h)

            dist = int(math.hypot(x8 - x4, y8 - y4))
            cv2.line(frame, (x4, y4), (x8, y8), (0, 255, 255), 3)

            cx, cy = (x4 + x8) // 2, (y4 + y8) // 2
            cv2.putText(frame, f"{dist}px", (cx, cy - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

            volume_pct = map_distance_to_volume(dist)
            with volume_lock:
                global requested_volume
                requested_volume = volume_pct

            cv2.putText(frame, f"Vol: {volume_pct}%", (10, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 3)

        with frame_lock:
            latest_frame = frame.copy()

    cap.release()
    hands.close()

# ============================================
# STREAMLIT CAMERA CONTROLLER
# ============================================
if run and not camera_running:
    camera_running = True
    camera_thread_obj = threading.Thread(
        target=camera_capture_thread,
        args=(camera_index, min_det_conf, min_track_conf),
        daemon=True
    )
    camera_thread_obj.start()

if not run and camera_running:
    camera_running = False

# ============================================
# DISPLAY FRAME
# ============================================
frame_box = st.empty()

if camera_running:
    with frame_lock:
        if latest_frame is not None:
            frame_box.image(cv2.cvtColor(latest_frame, cv2.COLOR_BGR2RGB),
                            channels="RGB", width=600)
else:
    st.info("Camera stopped.")

# ============================================
# STATUS PANEL
# ============================================
with st.expander("Status & Controls"):
    with volume_lock:
        st.write("Requested volume:", requested_volume)

    if platform.system() == "Windows":
        if st.button("Stop Hotkeys"):
            hotkey_stop.set()
            st.info("Hotkeys stopping...")




def set_volume(percent):
    """Set Windows master volume (0–100%)"""
    percent = max(0, min(100, percent))  # clamp
    scalar = percent / 100
    volume_interface.SetMasterVolumeLevelScalar(scalar, None)
