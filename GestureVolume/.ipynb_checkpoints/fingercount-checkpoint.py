import streamlit as st
from streamlit import rerun
import cv2
import numpy as np
import mediapipe as mp
import platform
import time
import pandas as pd
import traceback

# ------------------------------------------------------------
# WINDOWS VOLUME CONTROL (Render + Capture) - Bulletproof COM Logic
# ------------------------------------------------------------
if platform.system() == "Windows":
    from ctypes import POINTER, cast
    from comtypes import CLSCTX_ALL, CoInitialize, CoUninitialize, GUID
    from comtypes.client import CreateObject
    from pycaw.pycaw import IAudioEndpointVolume, IMMDeviceEnumerator

    # DataFlow constants
    eRender = 0   # Speakers / system volume (render)
    eCapture = 1  # Microphone (capture)
    eConsole = 0

    def _create_enum():
        try:
            return CreateObject("MMDeviceEnumerator.MMDeviceEnumerator", interface=IMMDeviceEnumerator)
        except:
            clsid = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
            return CreateObject(clsid, interface=IMMDeviceEnumerator)

    def _pct_to_scalar(p):
        return max(0.0, min(1.0, p / 100.0))

    def _scalar_to_pct(s):
        return max(0.0, min(100.0, s * 100.0))

    class BaseEndpointVolume:
        def __init__(self, dataflow):
            self.dataflow = dataflow
            self._init_device()

        def _init_device(self):
            try: CoInitialize()
            except: pass

            enum = _create_enum()
            dev = enum.GetDefaultAudioEndpoint(self.dataflow, eConsole)
            iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            self.vol = cast(iface, POINTER(IAudioEndpointVolume))

        def set_volume_percent(self, pct):
            """Set volume in percent (0–100)."""
            try: CoInitialize()
            except: pass

            try:
                pct = max(0.0, min(100.0, pct))
                scalar = _pct_to_scalar(pct)
                self.vol.SetMasterVolumeLevelScalar(scalar, None)
            except Exception:
                # swallow - keep UI running even if the device is unavailable
                pass

            try: CoUninitialize()
            except: pass

        def get_volume_percent(self):
            try: CoInitialize()
            except: pass

            try:
                s = float(self.vol.GetMasterVolumeLevelScalar())
                pct = _scalar_to_pct(s)
            except Exception:
                pct = 0.0

            try: CoUninitialize()
            except: pass

            return pct

    # Specific controllers
    class SystemVolumeController(BaseEndpointVolume):
        def __init__(self):
            super().__init__(eRender)

    class MicVolumeController(BaseEndpointVolume):
        def __init__(self):
            super().__init__(eCapture)

else:
    # On non-Windows platforms, provide None placeholders so the UI still runs.
    SystemVolumeController = None
    MicVolumeController = None


# ------------------------------------------------------------
# UI Styling (UNCHANGED)
# ------------------------------------------------------------
st.set_page_config(page_title="HoloVolume", layout="wide")

st.markdown("""
<style>
html, body, [class*="css"] { font-family: 'Segoe UI', sans-serif; }
.stApp {
    background: radial-gradient(circle at top, #00151f, #000000);
    color: #dfefff;
}
.neon-title {
    font-size: 34px; font-weight: 900;
    color: #00faff; text-align:center;
}
.badge {
    padding:8px 14px; border-radius:10px;
    font-weight:700; display:inline-block;
}
</style>
""", unsafe_allow_html=True)



# ------------------------------------------------------------
# SESSION STATE
# ------------------------------------------------------------
if "started" not in st.session_state: st.session_state.started = False
if "running" not in st.session_state: st.session_state.running = False
if "history_dist" not in st.session_state: st.session_state.history_dist = []
if "history_volume" not in st.session_state: st.session_state.history_volume = []
if "gesture_label" not in st.session_state: st.session_state.gesture_label = "Idle"
if "gesture_color" not in st.session_state: st.session_state.gesture_color = "#00faff"
if "metrics" not in st.session_state: st.session_state.metrics = {"FPS": 0, "Latency": 0}



# ------------------------------------------------------------
# SIDEBAR
# ------------------------------------------------------------
with st.sidebar:
    st.markdown("### ⚙️ Controls")
    show_landmarks = st.checkbox("Show Landmarks", True)
    cam_index = st.number_input("Camera Index", 0, 5, 0)

    start_btn = st.button("▶ Start Tracking")
    stop_btn = st.button("⏹ Stop Tracking")
    st.markdown("---")
    st.info(f"Platform: **{platform.system()}**")



# ------------------------------------------------------------
# MAIN UI (UNCHANGED)
# ------------------------------------------------------------
st.markdown("<div class='neon-title'>HoloVolume</div>", unsafe_allow_html=True)
st.markdown("<p style='text-align:center;color:#9fb;'>Controlling Volume with Hand Gestures Using a Webcam</p>", unsafe_allow_html=True)

col_feed, col_mid, col_right = st.columns([2, 1.2, 1])
frame_placeholder = col_feed.empty()
gesture_box = col_mid.empty()
volume_box = col_mid.empty()
metrics_box = col_right.empty()
graph_box = col_right.empty()



# ------------------------------------------------------------
# START / STOP LOGIC
# ------------------------------------------------------------
if start_btn: st.session_state.running = True
if stop_btn: st.session_state.running = False



# ------------------------------------------------------------
# FINGER COUNT FUNCTION (UNCHANGED)
# ------------------------------------------------------------
def count_fingers(lm, w, h):
    fingers = []

    thumb_tip = lm[4].x * w
    thumb_ip = lm[3].x * w
    wrist_x = lm[0].x * w

    # Thumb detection
    if (thumb_tip > thumb_ip and thumb_tip > wrist_x) or (thumb_tip < thumb_ip and thumb_tip < wrist_x):
        fingers.append(1)
    else:
        fingers.append(0)

    tip_ids  = [8, 12, 16, 20]
    base_ids = [6, 10, 14, 18]

    for tip, base in zip(tip_ids, base_ids):
        fingers.append(1 if lm[tip].y * h < lm[base].y * h else 0)

    return sum(fingers)



# ------------------------------------------------------------
# MEDIAPIPE + VOLUME CONTROLLERS
# ------------------------------------------------------------
mp_hands = mp.solutions.hands
mp_draw = mp.solutions.drawing_utils

# instantiate controllers if available on this platform
sys_vc = SystemVolumeController() if SystemVolumeController else None
mic_vc = MicVolumeController() if MicVolumeController else None



# ------------------------------------------------------------
# CAMERA LOOP (draw landmarks before converting for display)
# ------------------------------------------------------------
if st.session_state.running:

    cap = cv2.VideoCapture(int(cam_index))

    if not cap.isOpened():
        metrics_box.error("Camera not found.")
        st.session_state.running = False

    hands = mp_hands.Hands(min_detection_confidence=0.6, min_tracking_confidence=0.6)
    prev_time = time.time()

    finger_labels = ["Mute (0%)", "20%", "40%", "60%", "80%", "100%"]
    finger_colors = ["#ff4d6d", "#ff9d5c", "#ffd85c", "#7df9ff", "#59bfff", "#00faff"]

    try:
        while st.session_state.running:
            loop_start = time.time()

            ret, frame = cap.read()
            if not ret:
                metrics_box.error("Camera disconnected.")
                break

            frame = cv2.flip(frame, 1)
            h, w, _ = frame.shape

            # Convert for processing but draw to the BGR frame
            rgb_for_processing = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = hands.process(rgb_for_processing)

            if results.multi_hand_landmarks:
                hand = results.multi_hand_landmarks[0]
                lm = hand.landmark

                # draw landmarks on BGR frame so displayed image shows them
                if show_landmarks:
                    mp_draw.draw_landmarks(frame, hand, mp_hands.HAND_CONNECTIONS)

                fingers_up = count_fingers(lm, w, h)
            else:
                fingers_up = 0  # no hand -> treat as mute

            # ------------------------------------------------
            # VOLUME MAPPING (Option A: same mapping for both)
            # ------------------------------------------------
            pct = (fingers_up / 5.0) * 100.0  # 0,20,40,60,80,100

            # Update both system and mic volumes (safely — swallow errors)
            try:
                if sys_vc:
                    sys_vc.set_volume_percent(pct)
            except Exception:
                pass

            try:
                if mic_vc:
                    mic_vc.set_volume_percent(pct)
            except Exception:
                pass

            # UI Updates (unchanged visuals)
            label = finger_labels[fingers_up]
            color = finger_colors[fingers_up]

            st.session_state.gesture_label = label
            st.session_state.gesture_color = color

            volume_box.markdown(
                f"### 🔊 System & 🎤 Mic Volume: **{int(pct)}%**\nFingers: **{fingers_up}**"
            )

            gesture_box.markdown(
                f"""
                <div style='text-align:center;'>
                    <div class='badge'
                    style='border:1px solid {color}; color:{color};
                    box-shadow:0 0 12px {color};'>
                    {label}
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )

            # FPS + latency
            now = time.time()
            fps = 1 / (now - prev_time + 1e-6)
            prev_time = now
            latency = (time.time() - loop_start) * 1000

            st.session_state.metrics["FPS"] = int(fps)
            st.session_state.metrics["Latency"] = round(latency, 2)

            metrics_box.markdown(
                f"**FPS:** {int(fps)}  \n**Latency:** {round(latency, 2)} ms"
            )

            # History graph
            st.session_state.history_dist.append(fingers_up)
            st.session_state.history_volume.append(int(pct))

            # keep history bounded
            if len(st.session_state.history_dist) > 250:
                st.session_state.history_dist = st.session_state.history_dist[-250:]
                st.session_state.history_volume = st.session_state.history_volume[-250:]

            df = pd.DataFrame({
                "Fingers": st.session_state.history_dist[-200:],
                "Volume (%)": st.session_state.history_volume[-200:]
            })

            graph_box.line_chart(df)

            # Show camera frame — convert annotated BGR -> RGB for display
            display_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_placeholder.image(display_rgb, channels="RGB")

            time.sleep(0.005)

    except Exception:
        metrics_box.error("Error occurred.")
        metrics_box.text(traceback.format_exc())

    finally:
        try: cap.release()
        except: pass
        try: hands.close()
        except: pass
        st.session_state.running = False
        metrics_box.info("Stopped tracking.")

else:
    metrics_box.info("Press ▶ Start Tracking to begin.")



# ------------------------------------------------------------
# EXPORT HISTORY (UNCHANGED)
# ------------------------------------------------------------
with st.expander("📜 Volume History & Export"):
    if st.session_state.history_volume:
        hist_df = pd.DataFrame({
            "Fingers": st.session_state.history_dist,
            "Volume (%)": st.session_state.history_volume
        })
        st.dataframe(hist_df.tail(100))

        csv = hist_df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download CSV", csv, "volume_history.csv", "text/csv")
    else:
        st.write("No data yet.")
