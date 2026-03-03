
# 
from flask import Flask, render_template_string, request, send_from_directory, Response
from flask_socketio import SocketIO, emit
import threading
import time
import random
import math
import os
import io
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super-secret-key-123-change-this-in-production'

socketio = SocketIO(app, cors_allowed_origins="*")

# ────────────────────────────────────────────────
# Upload settings – now allows ALL file types
# ────────────────────────────────────────────────
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# No extension restriction anymore – allow everything
def allowed_file(filename):
    return True  # Accept all files

# ────────────────────────────────────────────────
# Picamera2 MJPEG Live Stream
# ────────────────────────────────────────────────
try:
    from picamera2 import Picamera2
    picam2 = Picamera2()
    camera_config = picam2.create_video_configuration(
        main={"size": (640, 480), "format": "MJPEG"}
    )
    picam2.configure(camera_config)
    picam2.start()
    print("Camera initialized successfully")
except Exception as e:
    print("Camera init failed:", e)
    picam2 = None

def gen_frames():
    if picam2 is None:
        # Placeholder if camera failed
        placeholder = b'\xFF\xD8\xFF\xE0' + b'\x00\x10JFIF' + (b'\x00' * 100) + b'\xFF\xD9'
        while True:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + placeholder + b'\r\n')
            time.sleep(1)
    stream = io.BytesIO()
    while True:
        try:
            picam2.capture_file(stream, format='jpeg')
            frame = stream.getvalue()
            stream.seek(0)
            stream.truncate(0)
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        except Exception as e:
            print("Capture error:", e)
            time.sleep(1)
        time.sleep(0.05)  # ~20 fps

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

# ────────────────────────────────────────────────
# Fake Telemetry Generator
# ────────────────────────────────────────────────
telemetry_data = {
    'lat': 19.8762,
    'lon': 75.3433,
    'alt': 0.0,
    'speed': 0.0,
    'heading': 0,
    'battery': 100,
    'armed': 'Disarmed',
    'flight_mode': 'STABILIZE',
    'timestamp': time.time()
}

lock = threading.Lock()

def fake_telemetry_generator():
    print("Fake telemetry generator started (updates ~every 1.2s)")
    base_lat = 19.8762
    base_lon = 75.3433
    sim_time = 0.0
    
    while True:
        sim_time += 1.2
        with lock:
            telemetry_data['lat'] = base_lat + 0.0008 * math.sin(sim_time * 0.3)
            telemetry_data['lon'] = base_lon + 0.0012 * math.cos(sim_time * 0.3)
            telemetry_data['alt'] = max(0, 50 * math.sin(sim_time * 0.15) + 30 + random.uniform(-2, 2))
            telemetry_data['speed'] = 12 + random.uniform(-4, 6)
            telemetry_data['heading'] = (telemetry_data['heading'] + random.uniform(-8, 12)) % 360
            
            if random.random() < 0.03:
                telemetry_data['battery'] = 100
            else:
                telemetry_data['battery'] = max(15, telemetry_data['battery'] - random.uniform(0.1, 0.6))
            
            if random.random() < 0.02:
                telemetry_data['armed'] = 'Armed' if telemetry_data['armed'] == 'Disarmed' else 'Disarmed'
            
            if random.random() < 0.04:
                modes = ['STABILIZE', 'LOITER', 'AUTO', 'RTL', 'LAND', 'GUIDED']
                telemetry_data['flight_mode'] = random.choice(modes)
            
            telemetry_data['timestamp'] = time.time()
        
        socketio.emit('telemetry_update', telemetry_data)
        time.sleep(1.2)

threading.Thread(target=fake_telemetry_generator, daemon=True).start()

# ────────────────────────────────────────────────
# Image / File Upload
# ────────────────────────────────────────────────
def get_latest_file():
    try:
        files = os.listdir(UPLOAD_FOLDER)
        if not files:
            return None
        latest = max(files, key=lambda f: os.path.getmtime(os.path.join(UPLOAD_FOLDER, f)))
        return latest
    except:
        return None

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return 'No file part', 400
    file = request.files['file']
    if file.filename == '':
        return 'No selected file', 400
    if file:
        filename = secure_filename(file.filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(save_path)
        socketio.emit('new_file', {'filename': filename, 'url': f'/uploads/{filename}'})
        return f'File saved: {filename}', 200
    return 'Upload failed', 400

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ────────────────────────────────────────────────
# Main Dashboard
# ────────────────────────────────────────────────
@app.route('/')
def index():
    latest = get_latest_file()
    latest_url = f'/uploads/{latest}' if latest else 'https://via.placeholder.com/400x300?text=No+File+Yet'
    
    return render_template_string('''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>RPi Telemetry + Live Cam + File Upload</title>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.js"></script>
        <style>
            body { font-family: Arial, sans-serif; background:#0a0a0a; color:#00ff88; margin:0; padding:20px; }
            h1, h2 { color:#00ffcc; text-align:center; }
            .card { background:#1a1a1a; padding:20px; margin:20px auto; max-width:680px; border-radius:10px; box-shadow:0 0 15px rgba(0,255,150,0.3); }
            img, video { width:100%; border-radius:8px; margin:10px 0; box-shadow:0 4px 12px rgba(0,0,0,0.5); }
            button { background:#00cc99; color:black; padding:10px 20px; border:none; border-radius:6px; cursor:pointer; font-weight:bold; }
            #status { color:#ffcc00; margin-top:10px; font-weight:bold; }
            p { margin:12px 0; font-size:1.1em; }
            strong { color:#00ffaa; }
            small { color:#aaa; }
            .file-list img { max-width:120px; margin:6px; border-radius:4px; }
        </style>
    </head>
    <body>
        <h1>Raspberry Pi Telemetry Dashboard</h1>

        <div class="card">
            <h2>Live Camera Feed (MJPEG)</h2>
            <img src="/video_feed" alt="Live RPi Camera Stream">
            <p><small>Streaming from connected camera (USB/CSI)</small></p>
        </div>

        <div class="card">
            <h2>Upload Any File</h2>
            <form id="uploadForm" enctype="multipart/form-data">
                <input type="file" name="file" required style="color:#fff; margin-bottom:12px;">
                <button type="submit">Upload File</button>
            </form>
            <p id="status"></p>
        </div>

        <div class="card">
            <h2>Latest Uploaded File</h2>
            {% if latest_url.endswith(('.png','.jpg','.jpeg','.gif')) %}
                <img id="latest-file" src="{{ latest_url }}" alt="Latest file">
            {% else %}
                <p><strong>File:</strong> <a href="{{ latest_url }}" target="_blank">{{ latest or 'None yet' }}</a></p>
            {% endif %}
            <p id="file-name">Latest: {{ latest or 'None yet' }}</p>
        </div>

        <div class="card">
            <h2>Uploaded Files</h2>
            <div id="file-list" class="file-list"></div>
        </div>

        <div class="card">
            <p><strong>Status:</strong> <span id="armed">—</span> | <span id="flight_mode">—</span></p>
            <p><strong>Battery:</strong> <span id="battery">—</span>%</p>
            <p><strong>Altitude:</strong> <span id="alt">—</span> m</p>
            <p><strong>Speed:</strong> <span id="speed">—</span> m/s</p>
            <p><strong>Heading:</strong> <span id="heading">—</span>°</p>
            <p><strong>GPS:</strong> <span id="lat">—</span>, <span id="lon">—</span></p>
            <small>Last update: <span id="time">waiting...</span></small>
        </div>

        <script>
            const socket = io();

            socket.on('connect', () => console.log('Connected to server'));

            socket.on('telemetry_update', (data) => {
                document.getElementById('lat').innerText = data.lat.toFixed(6);
                document.getElementById('lon').innerText = data.lon.toFixed(6);
                document.getElementById('alt').innerText = data.alt.toFixed(1);
                document.getElementById('speed').innerText = data.speed.toFixed(1);
                document.getElementById('heading').innerText = Math.round(data.heading);
                document.getElementById('battery').innerText = Math.round(data.battery);
                document.getElementById('armed').innerText = data.armed;
                document.getElementById('flight_mode').innerText = data.flight_mode;
                const date = new Date(data.timestamp * 1000);
                document.getElementById('time').innerText = date.toLocaleTimeString();
            });

            socket.on('new_file', (info) => {
                const list = document.getElementById('file-list');
                let item;
                if (info.filename.toLowerCase().match(/\.(png|jpg|jpeg|gif)$/)) {
                    item = `<img src="${info.url}?t=${Date.now()}" alt="${info.filename}" style="max-width:140px; margin:6px; border-radius:4px;">`;
                } else {
                    item = `<a href="${info.url}" target="_blank">${info.filename}</a><br>`;
                }
                list.innerHTML += item;
                document.getElementById('file-name').innerText = 'Latest: ' + info.filename;
                document.getElementById('status').innerText = 'New file: ' + info.filename;
                setTimeout(() => { document.getElementById('status').innerText = ''; }, 5000);
            });

            document.getElementById('uploadForm').addEventListener('submit', function(e) {
                e.preventDefault();
                const formData = new FormData(this);
                document.getElementById('status').innerText = 'Uploading...';
                fetch('/upload', {
                    method: 'POST',
                    body: formData
                })
                .then(response => response.text())
                .then(data => {
                    document.getElementById('status').innerText = data;
                    setTimeout(() => { document.getElementById('status').innerText = ''; }, 4000);
                })
                .catch(err => {
                    document.getElementById('status').innerText = 'Error: ' + err;
                });
            });
        </script>
    </body>
    </html>
    ''', latest_url=latest_url, latest=latest or 'None')

if __name__ == '__main__':
    print("TELEMETRY USING RASPBERRY AND JETSON NANO")
    print("RPi Server starting...")
    print("Dashboard:      http://<your-pi-ip>:5000")
    print("Live stream:    http://<your-pi-ip>:5000/video_feed")
    print("Uploads folder: ./uploads/")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
