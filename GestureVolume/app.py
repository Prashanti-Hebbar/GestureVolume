import streamlit as st
import cv2
import mediapipe as mp
import numpy as np
import pandas as pd
import math
import time
from collections import deque
import os
from PIL import Image

# ----------------- Streamlit Config -----------------
st.set_page_config(page_title="Gesture Volume", layout="wide")

# ----------------- Custom CSS -----------------
st.markdown("""
    <style>
        .stApp {
            background: linear-gradient(to bottom right, #111827, #1f2937);
            color: #ffffff;
            font-family: 'Segoe UI', sans-serif;
        }
        h1, h2, h3 { color: #10b981 !important; text-align:center; }
        .metric-card {
            background: #1e293b;
            border-radius: 15px;
            padding: 1.2rem;
            box-shadow: 0 4px 10px rgba(0,0,0,0.4);
            margin-bottom: 1rem;
            text-align:center;
        }
        .metric-value {
            font-size: 1.4rem;
            font-weight: bold;
            color: #facc15;
        }
        .stSidebar { background-color: #0f172a !important; }
    </style>
""", unsafe_allow_html=True)

# ----------------- Sidebar -----------------
with st.sidebar:
    st.markdown("### GestureVolume")
    run = st.toggle("▶️ Run Detection", value=False)
    camera_index = st.number_input("📷 Camera Index", min_value=0, max_value=4, value=0)
    min_det_conf = st.slider("Detection Confidence", 0.1, 1.0, 0.5, 0.05)
    min_track_conf = st.slider("Tracking Confidence", 0.1, 1.0, 0.5, 0.05)
    log_csv = st.checkbox("Log Measurements to CSV", value=False)
    csv_path = st.text_input("CSV filename", value="hand_measurements.csv")
    st.markdown("---")
    st.caption("💡 If camera doesn’t start, increase camera index or close other apps using the webcam.")

# ----------------- Header -----------------
st.markdown("<h1>Gesture Volume & Landmark Analyzer ✨</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align:center;'>View live hand landmarks, distances, and aspect ratio in a unified dashboard.</p>", unsafe_allow_html=True)

# ----------------- MediaPipe Init -----------------
mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils
hands = mp_hands.Hands(static_image_mode=False,
                       model_complexity=1,
                       min_detection_confidence=float(min_det_conf),
                       min_tracking_confidence=float(min_track_conf),
                       max_num_hands=1)

LANDMARK_NAMES = {
    0: "WRIST", 1: "THUMB_CMC", 2: "THUMB_MCP", 3: "THUMB_IP", 4: "THUMB_TIP",
    5: "INDEX_MCP", 6: "INDEX_PIP", 7: "INDEX_DIP", 8: "INDEX_TIP",
    9: "MIDDLE_MCP", 10: "MIDDLE_PIP", 11: "MIDDLE_DIP", 12: "MIDDLE_TIP",
    13: "RING_MCP", 14: "RING_PIP", 15: "RING_DIP", 16: "RING_TIP",
    17: "PINKY_MCP", 18: "PINKY_PIP", 19: "PINKY_DIP", 20: "PINKY_TIP"
}

def calc_dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])

# ----------------- Data buffers -----------------
aspect_ratio_data = deque(maxlen=100)
time_data = deque(maxlen=100)
start_time = time.time()

if log_csv:
    first_write = not os.path.exists(csv_path)
    csv_file = open(csv_path, "a", newline="")
    import csv
    csv_writer = csv.writer(csv_file)
    if first_write:
        csv_writer.writerow(["iso_ts", "elapsed_s",
                             "pinky_ring_px", "ring_middle_px", "middle_index_px", "index_thumb_px",
                             "height_px", "width_px", "aspect_ratio"])

# ----------------- Main Detection -----------------
if run:
    cap = cv2.VideoCapture(int(camera_index))
    frame_display = st.empty()
    metrics_container = st.container()
    st.markdown("---")
    st.markdown("### 📊 Landmark Table")
    table_display = st.empty()
    st.markdown("### 📈 Aspect Ratio Chart")
    chart_area = st.empty()

    while run:
        ret, frame = cap.read()
        if not ret:
            st.error("⚠️ Unable to access camera.")
            break

        frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]
        results = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

        if results.multi_hand_landmarks:
            hand_landmarks = results.multi_hand_landmarks[0]
            mp_drawing.draw_landmarks(frame, hand_landmarks, mp_hands.HAND_CONNECTIONS)

            df_rows, coords = [], []
            for idx, lm in enumerate(hand_landmarks.landmark):
                x_px, y_px = int(lm.x * w), int(lm.y * h)
                coords.append((x_px, y_px))
                df_rows.append({
                    "Index": idx,
                    "Landmark": LANDMARK_NAMES.get(idx, f"LM_{idx}"),
                    "X (px)": x_px,
                    "Y (px)": y_px
                })
            df = pd.DataFrame(df_rows).set_index("Index")

            # Compute distances
            dist_pinky_ring = calc_dist(coords[20], coords[16])
            dist_ring_middle = calc_dist(coords[16], coords[12])
            dist_middle_index = calc_dist(coords[12], coords[8])
            dist_index_thumb = calc_dist(coords[8], coords[4])
            height_px = calc_dist(coords[0], coords[12])
            width_px = calc_dist(coords[2], coords[17])
            aspect_ratio = height_px / width_px if width_px != 0 else 0.0

            # Draw measurement lines
            cv2.line(frame, coords[20], coords[16], (0,255,255), 2)
            cv2.line(frame, coords[16], coords[12], (0,255,255), 2)
            cv2.line(frame, coords[12], coords[8], (0,255,255), 2)
            cv2.line(frame, coords[8], coords[4], (0,255,255), 2)
            cv2.line(frame, coords[0], coords[12], (255,0,0), 2)
            cv2.line(frame, coords[2], coords[17], (255,0,255), 2)

            # Append chart data
            t = time.time() - start_time
            time_data.append(t)
            aspect_ratio_data.append(aspect_ratio)

            # Show frame
            frame_display.image(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), channels="RGB", use_container_width=True)

            # Measurements cards
            with metrics_container:
                st.markdown("### 📏 Live Measurements")
                col1, col2, col3 = st.columns(3)
                col1.markdown(f"<div class='metric-card'><div>Pinky–Ring</div><div class='metric-value'>{dist_pinky_ring:.1f}px</div></div>", unsafe_allow_html=True)
                col2.markdown(f"<div class='metric-card'><div>Ring–Middle</div><div class='metric-value'>{dist_ring_middle:.1f}px</div></div>", unsafe_allow_html=True)
                col3.markdown(f"<div class='metric-card'><div>Middle–Index</div><div class='metric-value'>{dist_middle_index:.1f}px</div></div>", unsafe_allow_html=True)
                col1.markdown(f"<div class='metric-card'><div>Index–Thumb</div><div class='metric-value'>{dist_index_thumb:.1f}px</div></div>", unsafe_allow_html=True)
                col2.markdown(f"<div class='metric-card'><div>Height (Wrist→MiddleTip)</div><div class='metric-value'>{height_px:.1f}px</div></div>", unsafe_allow_html=True)
                col3.markdown(f"<div class='metric-card'><div>Width (ThumbMCP→PinkyMCP)</div><div class='metric-value'>{width_px:.1f}px</div></div>", unsafe_allow_html=True)
                st.markdown(f"<div class='metric-card'><div>Aspect Ratio</div><div class='metric-value'>{aspect_ratio:.3f}</div></div>", unsafe_allow_html=True)

            # Table
            table_display.dataframe(df, use_container_width=True)

            # Chart
            chart_df = pd.DataFrame({"Time (s)": list(time_data), "Aspect Ratio": list(aspect_ratio_data)})
            chart_area.line_chart(chart_df.set_index("Time (s)"), height=300, use_container_width=True)

            # CSV logging
            if log_csv:
                iso_ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
                elapsed = time.time() - start_time
                csv_writer.writerow([iso_ts, f"{elapsed:.3f}",
                                    dist_pinky_ring, dist_ring_middle, dist_middle_index,
                                    dist_index_thumb, height_px, width_px, aspect_ratio])
                if int(elapsed) % 5 == 0:
                    csv_file.flush()

        time.sleep(0.03)

    cap.release()
    if log_csv:
        csv_file.close()

else:
    st.markdown("""
    <div style='text-align:center; margin-top:60px;'>
        <img src='https://cdn-icons-png.flaticon.com/512/1995/1995626.png' width='120'/>
        <h2>👋 Welcome to Gesture Volume Control</h2>
        <p>Enable <b>“Run Detection”</b> in the sidebar to start live hand tracking.</p>
        <p>Analyze landmarks, distances, and aspect ratio — all in one view!</p>
    </div>
    """, unsafe_allow_html=True)
