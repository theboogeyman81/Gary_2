import cv2
import threading
import time

# Dictionary to explicitly isolate and hold individual frames
camera_data = {0: None, 1: None}
data_lock = threading.Lock()

def capture_worker(camera_index):
    """Thread worker tasked ONLY with reading hardware frames."""
    # Force AVFOUNDATION backend for stability on your Mac mini
    cap = cv2.VideoCapture(camera_index, cv2.CAP_AVFOUNDATION)
    
    # Cap resolution immediately to save USB bus bandwidth
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    
    if not cap.isOpened():
        print(f"[ERROR] Camera {camera_index} hardware could not be initialized.")
        return

    print(f"[INFO] Camera {camera_index} started successfully.")

    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            continue
        
        # Lock and update the separate array index safely
        with data_lock:
            camera_data[camera_index] = frame.copy()

    cap.release()

if __name__ == "__main__":
    # Initialize background daemon capture threads
    t1 = threading.Thread(target=capture_worker, args=(0,), daemon=True)
    t2 = threading.Thread(target=capture_worker, args=(1,), daemon=True)
    
    t1.start()
    time.sleep(0.6)  # Pause to avoid macOS AVFoundation index allocation race conditions
    t2.start()

    print("[INFO] Starting separate window displays on the Main Thread...")

    while True:
        # Safely pull isolated frames out of memory blocks
        with data_lock:
            img0 = camera_data[0].copy() if camera_data[0] is not None else None
            img1 = camera_data[1].copy() if camera_data[1] is not None else None

        # Display separate window for Camera 0
        if img0 is not None:
            cv2.imshow("Camera Window 1", img0)

        # Display separate window for Camera 1
        if img1 is not None:
            cv2.imshow("Camera Window 2", img1)

        # Break out loop if user presses 'q' inside either window
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cv2.destroyAllWindows()
