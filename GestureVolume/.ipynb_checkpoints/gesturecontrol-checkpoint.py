# main.py — Gesture Volume Control (Final Neon Dashboard, Option A)
# Requires: streamlit, opencv-python, mediapipe, numpy, pandas, pycaw (Windows)
# Save as main.py and run: streamlit run main.py

import streamlit as st
from streamlit import rerun
import cv2
import numpy as np
import mediapipe as mp
import platform
import time
from collections import deque
import pandas as pd
import math
import traceback

# -------------------------
# Windows pycaw (optional)
# -------------------------
if platform.system() == "Windows":
    try:
        from ctypes import cast, POINTER
        from comtypes import CoInitialize, CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    except Exception:
        AudioUtilities = None
        IAudioEndpointVolume = None

class VolumeController:
    """Minimal pycaw wrapper — harmless no-op on non-Windows or when pycaw missing."""
    def __init__(self):
        self.volume = None
        if platform.system() != "Windows" or AudioUtilities is None:
            return
        try:
            try:
                CoInitialize()
            except Exception:
                pass
            speakers = AudioUtilities.GetSpeakers()
            interface = speakers.Activate(
                IAudioEndpointVolume._iid_,
                CLSCTX_ALL,
                None
            )
            self.volume = cast(interface, POINTER(IAudioEndpointVolume))
        except Exception:
            self.volume = None

    def set_volume_scalar(self, scalar: float):
        if self.volume is None:
            return
        scalar = float(np.clip(scalar, 0.0, 1.0))
        try:
            self.volume.SetMasterVolumeLevelScalar(scalar, None)
        except Exception:
            pass

    def get_volume(self):
        if self.volume is None:
            return None
        try:
            return float(self.volume.GetMasterVolumeLevelScalar())
        except Exception:
            return None

# -------------------------
# Streamlit UI styling (neon)
# -------------------------
st.set_page_config(page_title="HoloVolume", layout="wide")
st.markdown("""
<style>
@keyframes neonPulse {
    0% { box-shadow: 0 0 8px rgba(0,255,255,0.12); }
    50% { box-shadow: 0 0 20px rgba(0,255,255,0.28); }
    100% { box-shadow: 0 0 8px rgba(0,255,255,0.12); }
}
@keyframes glowText {
    0% { text-shadow: 0 0 6px #00faff; }
    50% { text-shadow: 0 0 20px #00faff, 0 0 40px #00faff; }
    100% { text-shadow: 0 0 6px #00faff; }
}
html, body, [class*="css"] { font-family: 'Segoe UI', sans-serif; }
.stApp { background: radial-gradient(circle at top, #00151f, #000000); color: #dfefff; }
.neon-card {
    background: rgba(0, 255, 255, 0.03);
    border: 1px solid rgba(0,255,255,0.12);
    border-radius: 12px;
    padding: 14px;
    margin-bottom: 12px;
    animation: neonPulse 3s infinite;
}
.neon-title { font-size: 34px; font-weight: 900; color: #00faff; text-align:center; }
.start-screen { text-align:center; margin-top:80px; color:#9ff; }
.start-button {
    background: transparent;
    border: 2px solid #00faff !important;
    color: #00faff !important;
    padding: 12px 36px;
    border-radius: 12px;
    font-size: 20px;
    transition: 0.2s;
}
.start-button:hover { background:#00faff !important; color:#001; box-shadow:0 0 30px #00faff; }
.badge {
    padding:8px 14px; border-radius:10px; font-weight:700; display:inline-block;
}
.small-muted { color:#9fb; font-size:13px; }
</style>
""", unsafe_allow_html=True)

# -------------------------
# Session state init
# -------------------------
if "started" not in st.session_state: st.session_state.started = False
if "running" not in st.session_state: st.session_state.running = False
if "px_per_cm" not in st.session_state: st.session_state.px_per_cm = None
if "pinch_samples" not in st.session_state: st.session_state.pinch_samples = []
if "history_dist" not in st.session_state: st.session_state.history_dist = []
if "history_volume" not in st.session_state: st.session_state.history_volume = []
if "metrics" not in st.session_state: st.session_state.metrics = {"FPS": 0, "Latency(ms)": 0.0, "Samples": 0}
if "gesture_label" not in st.session_state: st.session_state.gesture_label = "Idle"
if "gesture_color" not in st.session_state: st.session_state.gesture_color = "#00faff"
if "quality" not in st.session_state: st.session_state.quality = "Unknown"
if "last_chart_update" not in st.session_state: st.session_state.last_chart_update = 0.0


# -------------------------
# Sidebar controls
# -------------------------
with st.sidebar:
    st.markdown("### ⚙️ Controls")
    sensitivity_cm = st.slider("Gesture Sensitivity (cm)", 3.0, 25.0, 10.0, step=0.5)
    smoothing_frames = st.slider("Smoothing Frames", 1, 30, 6)
    mute_threshold_cm = st.slider("Pinch Mute Threshold (cm)", 0.4, 3.0, 1.2, step=0.1)
    show_landmarks = st.checkbox("Show Hand Landmarks", True)
    show_fps = st.checkbox("Show FPS", True)
    cam_index = st.number_input("Camera Index", 0, 5, 0)
    st.markdown("---")
    start_btn = st.button("▶ Start Tracking", use_container_width=True)
    stop_btn = st.button("⏹ Stop Tracking", use_container_width=True)
    st.markdown("---")
    st.info(f"Platform: **{platform.system()}**")
    st.success("Auto Calibration: ON")

# -------------------------
# Main layout placeholders
# -------------------------
st.markdown("<div class='neon-title'>HoloVolume</div>", unsafe_allow_html=True)
st.markdown("<p style='text-align:center;color:#9fb;'>Controlling Volume with Hand Gestures Using a Webcam</p>", unsafe_allow_html=True)

col_feed, col_center, col_right = st.columns([2, 1.2, 1])

frame_placeholder = col_feed.empty()
col_center.markdown("<div class='neon-card'>", unsafe_allow_html=True)
gesture_box = col_center.empty()
col_center.markdown("</div>", unsafe_allow_html=True)

col_center.markdown("<div class='neon-card'>", unsafe_allow_html=True)
volume_box = col_center.empty()
col_center.markdown("</div>", unsafe_allow_html=True)

col_right.markdown("<div class='neon-card'>", unsafe_allow_html=True)
metrics_box = col_right.empty()
col_right.markdown("</div>", unsafe_allow_html=True)

col_right.markdown("<div class='neon-card'>", unsafe_allow_html=True)
graph_box = col_right.empty()
col_right.markdown("</div>", unsafe_allow_html=True)

# -------------------------
# Start/stop toggle
# -------------------------
if start_btn:
    st.session_state.running = True
if stop_btn:
    st.session_state.running = False

# -------------------------
# Mediapipe and controller init
# -------------------------
mp_hands = mp.solutions.hands
mp_draw = mp.solutions.drawing_utils
vc = VolumeController()
smoothing = deque(maxlen=smoothing_frames)

def classify_gesture(cm_dist, px_dist, palm_px, mute_threshold):
    if cm_dist is None or math.isnan(cm_dist):
        return "No Hand", "#777", "Bad"
    if cm_dist < mute_threshold:
        return "Pinch (Mute)", "#ff4d6d", "Good"
    if cm_dist < 3.5:
        return "Short Pinch", "#ffb86b", "Good"
    if cm_dist < 7.0:
        return "Open Hand", "#7df9ff", "Good"
    return "Extended/Open", "#59bfff", "Good"

def update_metrics(fps, latency_ms, samples):
    st.session_state.metrics["FPS"] = int(round(fps))
    st.session_state.metrics["Latency(ms)"] = round(latency_ms, 2)
    st.session_state.metrics["Samples"] = int(samples)

# -------------------------
# Safe camera loop (no blue bars, stable)
# -------------------------
if st.session_state.running:
    metrics_box.success("Camera starting...")
    cap = cv2.VideoCapture(int(cam_index))
    if not cap.isOpened():
        metrics_box.error("Cannot open camera. Check camera index.")
        st.session_state.running = False

    hands = mp_hands.Hands(min_detection_confidence=0.6, min_tracking_confidence=0.6)
    prev_time = time.time()
    was_muted = False
    last_volume = vc.get_volume() or 0.5

    # Chart update interval (seconds) — keeps UI updates occasional and safe
    chart_interval = 0.6
    try:
        while st.session_state.running:
            loop_start = time.time()
            ret, frame = cap.read()
            if not ret:
                metrics_box.error("Camera disconnected.")
                break

            frame = cv2.flip(frame, 1)
            h, w, _ = frame.shape
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # Process hand
            results = hands.process(rgb)
            volume_scalar = None
            muted = False
            cm_dist = None
            px_dist = None
            palm_px = None

            if results.multi_hand_landmarks:
                hand = results.multi_hand_landmarks[0]
                lm = hand.landmark

                x4, y4 = int(lm[4].x * w), int(lm[4].y * h)
                x8, y8 = int(lm[8].x * w), int(lm[8].y * h)
                x5, y5 = int(lm[5].x * w), int(lm[5].y * h)
                x17, y17 = int(lm[17].x * w), int(lm[17].y * h)

                palm_px = np.linalg.norm([x5 - x17, y5 - y17])
                px_dist = np.linalg.norm([x4 - x8, y4 - y8])

                if show_landmarks:
                    mp_draw.draw_landmarks(frame, hand, mp_hands.HAND_CONNECTIONS)
                
                    # Thumb and Index tip markers
                    cv2.circle(frame, (x4, y4), 8, (0, 255, 255), -1)
                    cv2.circle(frame, (x8, y8), 8, (0, 255, 255), -1)
                
                    # Line between thumb and index
                    cv2.line(frame, (x4, y4), (x8, y8), (255, 0, 150), 3)


                # Auto calibration
                if st.session_state.px_per_cm is None and palm_px > 10:
                    st.session_state.px_per_cm = palm_px / 8.5

                if 2.0 < px_dist < 400.0:
                    st.session_state.pinch_samples.append(px_dist)

                if len(st.session_state.pinch_samples) > 30:
                    avg_px = np.mean(st.session_state.pinch_samples)
                    pinch_cal = avg_px / 3.5
                    if st.session_state.px_per_cm is None:
                        st.session_state.px_per_cm = pinch_cal
                    else:
                        st.session_state.px_per_cm = 0.85 * st.session_state.px_per_cm + 0.15 * pinch_cal
                    st.session_state.pinch_samples = []

                if st.session_state.px_per_cm and px_dist is not None:
                    cm_dist = px_dist / st.session_state.px_per_cm

                # Gesture & volume
                label, color, quality = classify_gesture(cm_dist, px_dist, palm_px, mute_threshold_cm)
                st.session_state.gesture_label = label
                st.session_state.gesture_color = color
                st.session_state.quality = quality

                if cm_dist is not None:
                    if cm_dist < mute_threshold_cm:
                        muted = True
                        was_muted = True
                        last_volume = vc.get_volume() or last_volume
                        vc.set_volume_scalar(0.0)
                    else:
                        mapped = np.interp(cm_dist, [1.0, sensitivity_cm], [0.0, 1.0])
                        mapped = float(np.clip(mapped, 0.0, 1.0))
                        smoothing.append(mapped)
                        volume_scalar = float(np.mean(smoothing))
                        if was_muted:
                            volume_scalar = last_volume * 0.6 + volume_scalar * 0.4
                            was_muted = False
                        vc.set_volume_scalar(volume_scalar)

            # FPS & latency
            now = time.time()
            fps = 1.0 / (now - prev_time + 1e-6) if prev_time else 0.0
            prev_time = now
            processing_ms = (time.time() - loop_start) * 1000.0
            update_metrics(fps, processing_ms, len(st.session_state.pinch_samples))

            # Update gesture + volume cards (text-only updates are cheap)
            badge_html = f"""
            <div style='text-align:center;'>
                <div class='badge' style='background:rgba(0,0,0,0.45); border:1px solid {st.session_state.gesture_color};
                    box-shadow:0 0 12px {st.session_state.gesture_color}; color:{st.session_state.gesture_color};'>
                    {st.session_state.gesture_label}
                </div>
                <div style='margin-top:8px;color:#bfe; font-weight:600;'>Quality: <span style='color: #ffd;'>{st.session_state.quality}</span></div>
            </div>
            """
            gesture_box.markdown(badge_html, unsafe_allow_html=True)

            current_vol = vc.get_volume() if vc.get_volume() is not None else (volume_scalar or 0.0)
            vol_pct = int(round((current_vol or 0.0) * 100))
            volume_text = f"### 🔊 Volume: **{vol_pct}%**"
            if cm_dist is not None:
                volume_text += f"\nDistance: **{cm_dist:.2f} cm**  •  Thumb-Index px: **{px_dist:.1f}**"
            else:
                volume_text += "\nNo valid distance measurement yet."
            volume_box.markdown(volume_text)

            metrics_html = f"""
            <div style='font-size:14px;'>
                <b>FPS:</b> {int(st.session_state.metrics['FPS'])} &nbsp;&nbsp;
                <b>Latency (ms):</b> {st.session_state.metrics['Latency(ms)']} &nbsp;&nbsp;
                <b>Calibration Samples:</b> {st.session_state.metrics['Samples']}
            </div>
            """
            metrics_box.markdown(metrics_html, unsafe_allow_html=True)

            # Append history (in-memory) — keep bounded length
            if px_dist is not None and cm_dist is not None and volume_scalar is not None:
                st.session_state.history_dist.append(cm_dist)
                st.session_state.history_volume.append(volume_scalar * 100)
                max_hist = 300
                if len(st.session_state.history_dist) > max_hist:
                    st.session_state.history_dist = st.session_state.history_dist[-max_hist:]
                    st.session_state.history_volume = st.session_state.history_volume[-max_hist:]

            # Update chart & history at controlled intervals to avoid UI churn
            if time.time() - st.session_state.last_chart_update > chart_interval:
                st.session_state.last_chart_update = time.time()
                if len(st.session_state.history_dist) > 1:
                    df = pd.DataFrame({
                        "Distance (cm)": st.session_state.history_dist,
                        "Volume (%)": st.session_state.history_volume
                    })
                    # Render combined line chart (two series)
                    graph_box.line_chart(df)
                else:
                    graph_box.markdown("Distance↔Volume graph will appear here as you move your fingers.")

            # Render only the camera frame each iteration
            try:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frame_placeholder.image(frame_rgb, channels="RGB")
            except Exception:
                frame_placeholder.write("Unable to render camera frame.")

            # small sleep for CPU-friendly loop (still responsive)
            time.sleep(0.006)

    except Exception as e:
        metrics_box.error("Unexpected error — see details.")
        metrics_box.text(traceback.format_exc())
    finally:
        try:
            cap.release()
        except Exception:
            pass
        try:
            hands.close()
        except Exception:
            pass
        st.session_state.running = False
        metrics_box.info("Stopped tracking.")

else:
    metrics_box.info("Press ▶ Start Tracking to begin gesture control.")

# -------------------------
# Expanders: history export and project notes
# -------------------------
with st.expander("📜 Volume History & Export"):
    st.write("Recent volume values (most recent 100):")
    if st.session_state.history_volume:
        hist_df = pd.DataFrame({
            "idx": range(len(st.session_state.history_volume)),
            "volume_pct": st.session_state.history_volume
        })
        st.dataframe(hist_df.tail(100))
        csv = pd.DataFrame({
            "distance_cm": st.session_state.history_dist,
            "volume_pct": st.session_state.history_volume
        }).to_csv(index=False).encode('utf-8')
        st.download_button("⬇️ Download history CSV", data=csv, file_name="gesture_volume_history.csv", mime="text/csv")
    else:
        st.write("No history yet. Move your thumb & index finger while tracking is active.")
# End of file
