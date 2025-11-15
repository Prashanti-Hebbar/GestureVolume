# GestureVolume

Control your system volume using hand gestures detected through your webcam!  
Built with Python, OpenCV, and Mediapipe.

## Features
- Real-time hand gesture detection via webcam
- Adjusts system volume based on finger distance
- Logs hand and fingertip distances for analysis

## Files
- `gesture_volume.ipynb`: Main notebook for gesture volume control
- `volume.ipynb`: Additional experiments with volume
- `hand_distance_log.csv`: Log of hand distances
- `fingertip_distances_log.csv`: Log of fingertip distances
- `cat.jpeg`: Sample image

## Installation

1. Clone the repository: git clone https://github.com/Prashanti-Hebbar/GestureVolume.git
                         cd GestureVolume
2. (Optional but recommended) Create and activate a virtual environment: python -m venv venv
    On Windows:
    venv\Scripts\activate
    
    On Mac/Linux:
    source venv/bin/activate

3. Install the required packages: jupyter notebook

## How to Run

1. Open `gesture_volume.ipynb` in Jupyter Notebook.
2. Run the cells and follow the instructions in the notebook.
3. Make sure your webcam is connected.
4. Enjoy adjusting your volume with your hand gestures!

## Requirements
- Python 3.x
- OpenCV
- Mediapipe
- Jupyter Notebook
