import cv2
import secrets
import sys, time, threading, logging, subprocess, os
from flask import Flask, jsonify, request, Response
from flask_socketio import SocketIO, emit
from dwarflab_controller import DwarfLab

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dwarf_server")
TELESCOPE_IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.88.1"
app = Flask(__name__, static_folder="static", template_folder="static")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
dwarf = None

def on_telescope_notify(pkt):
    cmd = pkt["cmd"]
    socketio.emit("telescope_event", {"cmd":cmd,"data":pkt["data"].hex(),"state":dwarf.state})

def connect_telescope():
    global dwarf
    dwarf = DwarfLab(TELESCOPE_IP, on_notify=on_telescope_notify)
    log.info(f"Connecting to {TELESCOPE_IP}...")
    ok = dwarf.connect(timeout=8)
    if ok:
        log.info("Telescope connected!")
        dwarf.get_device_state()
        socketio.emit("status",{"connected":True,"ip":TELESCOPE_IP,"state":dwarf.state})
    else:
        log.warning("Telescope not reachable - demo mode")
        socketio.emit("status",{"connected":False,"ip":TELESCOPE_IP,"state":{}})

def rtsp_to_mjpeg(channel="ch0"):
    """
    Stream RTSP from DWARF II telescope as MJPEG.

    Confirmed RTSP paths from APK source (CaptureActivity.java k7()):
      Tele lens  : rtsp://<ip>:554/ch0/stream0
      Wide lens  : rtsp://<ip>:554/ch1/stream0

    The camera must be opened first via WebSocket (CMD_CAMERA_TELE_OPEN_CAMERA=10000)
    and live-view started (CMD_ASTRO_GO_LIVE=11010) before RTSP is available.
    """
    import cv2, time
    rtsp_url = f"rtsp://{TELESCOPE_IP}:554/{channel}/stream0"
    log.info(f"RTSP stream starting: {rtsp_url}")
    # Suppress HEVC decoder noise (POC reference warnings) from FFmpeg stderr
    import os; os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "0")
    CRLF = bytes([13,10])
    cap = None
    while True:
        try:
            if cap is None or not cap.isOpened():
                cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
                if not cap.isOpened():
                    log.warning(f"RTSP not available yet ({rtsp_url}), retrying in 2s...")
                    time.sleep(2)
                    continue
                log.info(f"RTSP connected: {rtsp_url}")
            ret, frame = cap.read()
            if not ret:
                log.warning("RTSP read failed, reconnecting...")
                cap.release(); cap = None
                time.sleep(1); continue
            # Resize to max width 960 keeping aspect ratio
            h, w = frame.shape[:2]
            if w > 960:
                frame = cv2.resize(frame, (960, int(h*960/w)))
            ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if not ok: continue
            header = b"--frame" + CRLF + b"Content-Type: image/jpeg" + CRLF + CRLF
            yield header + jpg.tobytes() + CRLF
        except GeneratorExit:
            if cap: cap.release()
            return
        except Exception as e:
            log.error(f"Stream error: {e}")
            if cap: cap.release(); cap = None
            time.sleep(2)

@app.route("/stream")
def video_stream():
    """Tele lens stream (ch0/stream0) - default"""
    return Response(rtsp_to_mjpeg("ch0"), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/stream/wide")
def video_stream_wide():
    """Wide lens stream (ch1/stream0)"""
    return Response(rtsp_to_mjpeg("ch1"), mimetype="multipart/x-mixed-replace; boundary=frame")

def api_ok(msg="ok",**kw): return jsonify({"status":"ok","message":msg,**kw})
def api_err(msg): return jsonify({"status":"error","message":msg}), 400
def require_dwarf(f):
    from functools import wraps
    @wraps(f)
    def w(*a,**kw):
        if not dwarf: return api_err("Telescope not initialised")
        return f(*a,**kw)
    return w

@app.route("/api/status")
def api_status():
    c = dwarf.state["connected"] if dwarf else False
    return jsonify({"connected":c,"ip":TELESCOPE_IP,"state":dwarf.state if dwarf else {}})

@app.route("/api/connect",methods=["POST"])
def api_connect():
    if dwarf and dwarf.state.get("connected"):
        return api_ok("Already connected")
    threading.Thread(target=connect_telescope,daemon=True).start()
    return api_ok("Connecting...")

@app.route("/api/device_info")
@require_dwarf
def api_device_info(): return jsonify(dwarf.http_device_info())

@app.route("/api/camera/open",methods=["POST"])
@require_dwarf
def cam_open():
    # Full app-equivalent sequence: enter_camera first, then open_camera with RTSP payload
    dwarf.enter_camera(encode_type=1)
    time.sleep(0.3)
    dwarf.open_camera(rtsp_encode_type=1)
    return api_ok("Camera opened")

@app.route("/api/camera/close",methods=["POST"])
@require_dwarf
def cam_close(): dwarf.close_camera(); return api_ok()

@app.route("/api/camera/photo",methods=["POST"])
@require_dwarf
def cam_photo(): dwarf.take_photo(); return api_ok("Photo taken")

@app.route("/api/camera/photo_raw",methods=["POST"])
@require_dwarf
def cam_photo_raw(): dwarf.take_photo_raw(); return api_ok("RAW photo taken")

@app.route("/api/camera/burst",methods=["POST"])
@require_dwarf
def cam_burst():
    n = (request.json or {}).get("count",3)
    dwarf.start_burst(n); return api_ok(f"Burst x{n}")

@app.route("/api/camera/burst_stop",methods=["POST"])
@require_dwarf
def cam_burst_stop(): return api_ok("Burst stop not supported on Dwarf3 firmware (command removed in June 2026 APK)")

@app.route("/api/camera/record_start",methods=["POST"])
@require_dwarf
def cam_rec_start(): dwarf.start_record(); return api_ok("Recording started")

@app.route("/api/camera/record_stop",methods=["POST"])
@require_dwarf
def cam_rec_stop(): dwarf.stop_record(); return api_ok("Recording stopped")

@app.route("/api/camera/timelapse_start",methods=["POST"])
@require_dwarf
def cam_tl_start(): dwarf.start_timelapse(); return api_ok("Timelapse started")

@app.route("/api/camera/timelapse_stop",methods=["POST"])
@require_dwarf
def cam_tl_stop(): dwarf.stop_timelapse(); return api_ok("Timelapse stopped")

@app.route("/api/camera/params",methods=["POST"])
@require_dwarf
def cam_params():
    d = request.json or {}
    if "exposure"    in d: dwarf.set_exposure(d["exposure"])
    if "gain"        in d: dwarf.set_gain(d["gain"])
    if "brightness"  in d: dwarf.set_brightness(d["brightness"])
    if "contrast"    in d: dwarf.set_contrast(d["contrast"])
    if "saturation"  in d: dwarf.set_saturation(d["saturation"])
    if "sharpness"   in d: dwarf.set_sharpness(d["sharpness"])
    if "wb_mode"     in d: dwarf.set_wb_mode(d["wb_mode"])
    if "wb_ct"       in d: dwarf.set_wb_ct(d["wb_ct"])
    if "ircut"       in d: dwarf.set_ircut(d["ircut"])
    if "jpg_quality" in d: dwarf.set_jpg_quality(d["jpg_quality"])
    return api_ok("Params updated")

@app.route("/api/camera/resolution",methods=["POST"])
@require_dwarf
def cam_resolution():
    d = request.json or {}
    if "resolution" in d: dwarf.switch_resolution(d["resolution"])
    if "framerate"  in d: dwarf.switch_framerate(d["framerate"])
    return api_ok()

@app.route("/api/astro/calibrate_start",methods=["POST"])
@require_dwarf
def astro_cs(): dwarf.start_calibration(); return api_ok("Calibration started")

@app.route("/api/astro/calibrate_stop",methods=["POST"])
@require_dwarf
def astro_cs2(): dwarf.stop_calibration(); return api_ok()

@app.route("/api/astro/goto_dso",methods=["POST"])
@require_dwarf
def astro_goto_dso():
    d=request.json or {}
    ra=float(d.get("ra",0)); dec=float(d.get("dec",0)); name=d.get("name","")
    dwarf.goto_dso(ra,dec,name); return api_ok(f"GoTo {name}")

@app.route("/api/astro/goto_solar",methods=["POST"])
@require_dwarf
def astro_gs():
    N=["Sun","Moon","Mercury","Venus","Mars","Jupiter","Saturn","Uranus","Neptune"]
    try:
        idx=int((request.json or {}).get("target",1))
    except (ValueError,TypeError):
        return api_err("target must be an integer 0-8")
    if not 0<=idx<len(N):
        return api_err(f"target must be 0-{len(N)-1} (Sun=0 … Neptune={len(N)-1})")
    dwarf.goto_solar(idx); return api_ok(f"GoTo {N[idx]}")

@app.route("/api/astro/goto_stop",methods=["POST"])
@require_dwarf
def astro_gstop(): dwarf.stop_goto(); return api_ok("GoTo aborted")

@app.route("/api/astro/goto_one_click",methods=["POST"])
@require_dwarf
def astro_oc():
    d=request.json or {}
    dwarf.one_click_goto_dso(float(d.get("ra",0)),float(d.get("dec",0)),d.get("name",""))
    return api_ok("One-click GoTo started")

@app.route("/api/astro/one_click_stop",methods=["POST"])
@require_dwarf
def astro_ocs(): dwarf.stop_one_click_goto(); return api_ok()

@app.route("/api/astro/go_live",methods=["POST"])
@require_dwarf
def astro_gl(): dwarf.go_live(); return api_ok("Live view")

@app.route("/api/camera/start_live",methods=["POST"])
@require_dwarf
def cam_start_live():
    """
    Full startup sequence to activate RTSP stream from cold, without needing the phone app.
    Replicates the exact sequence from WsEnterCamReq → WsOpenCameraReq → CMD_ASTRO_GO_LIVE.
    """
    def _sequence():
        dwarf.enter_camera(encode_type=1)   # 16404 — init camera subsystem with H.265
        time.sleep(0.5)
        dwarf.open_camera(rtsp_encode_type=1)  # 10000 — open tele cam + activate RTSP
        time.sleep(1.5)
        dwarf.go_live()                       # 11010 — start live view stream
        log.info("start_live sequence complete")
    threading.Thread(target=_sequence, daemon=True).start()
    return api_ok("Live start sequence initiated — stream ready in ~2s")

@app.route("/api/astro/stack_start",methods=["POST"])
@require_dwarf
def astro_ss():
    d=request.json or {}
    dwarf.start_stacking(d.get("exp_ms",10000),d.get("gain",0),d.get("count",0))
    return api_ok("Stacking started")

@app.route("/api/astro/stack_stop",methods=["POST"])
@require_dwarf
def astro_ss2(): dwarf.stop_stacking(); return api_ok("Stacking stopped")

@app.route("/api/astro/plate_solve",methods=["POST"])
@require_dwarf
def astro_ps(): dwarf.start_plate_solve(); return api_ok("Plate solving started")

@app.route("/api/astro/plate_solve_stop",methods=["POST"])
@require_dwarf
def astro_ps2(): dwarf.stop_plate_solve(); return api_ok()

@app.route("/api/astro/sky_finder",methods=["POST"])
@require_dwarf
def astro_sf(): dwarf.start_sky_finder(); return api_ok("Sky finder started")

@app.route("/api/astro/sky_finder_stop",methods=["POST"])
@require_dwarf
def astro_sf2(): dwarf.stop_sky_finder(); return api_ok()

@app.route("/api/astro/ai_enhance",methods=["POST"])
@require_dwarf
def astro_ai(): dwarf.start_ai_enhance(); return api_ok("AI enhance started")

@app.route("/api/astro/ai_enhance_stop",methods=["POST"])
@require_dwarf
def astro_ai2(): dwarf.stop_ai_enhance(); return api_ok()

@app.route("/api/astro/one_click_shoot",methods=["POST"])
@require_dwarf
def astro_ocs2(): dwarf.one_click_shoot(); return api_ok("One-click shooting started")

@app.route("/api/focus/auto",methods=["POST"])
@require_dwarf
def fa(): dwarf.auto_focus(); return api_ok("Auto focus triggered")

@app.route("/api/focus/astro",methods=["POST"])
@require_dwarf
def fa2(): dwarf.astro_focus(); return api_ok("Astro AF started")

@app.route("/api/focus/astro_stop",methods=["POST"])
@require_dwarf
def fa3(): dwarf.stop_astro_focus(); return api_ok()

@app.route("/api/focus/in",methods=["POST"])
@require_dwarf
def fi(): dwarf.focus_in(); return api_ok()

@app.route("/api/focus/out",methods=["POST"])
@require_dwarf
def fo(): dwarf.focus_out(); return api_ok()

@app.route("/api/focus/stop",methods=["POST"])
@require_dwarf
def fs(): dwarf.focus_stop(); return api_ok()

@app.route("/api/focus/step",methods=["POST"])
@require_dwarf
def fst():
    n=int((request.json or {}).get("steps",1))
    dwarf.focus_step(n); return api_ok(f"Focus step {n}")

@app.route("/api/motion/joystick",methods=["POST"])
@require_dwarf
def mj():
    d=request.json or {}
    dwarf.joystick(int(d.get("x",0)),int(d.get("y",0))); return api_ok()

@app.route("/api/motion/joystick_stop",methods=["POST"])
@require_dwarf
def mjs(): dwarf.joystick_stop(); return api_ok()

@app.route("/api/motion/track_start",methods=["POST"])
@require_dwarf
def mts(): dwarf.start_tracking(); return api_ok("Tracking started")

@app.route("/api/motion/track_stop",methods=["POST"])
@require_dwarf
def mtss(): dwarf.stop_tracking(); return api_ok("Tracking stopped")

@app.route("/api/system/sync_time",methods=["POST"])
@require_dwarf
def sst(): dwarf.sync_time(); return api_ok("Time synced")

@app.route("/api/system/location",methods=["POST"])
@require_dwarf
def sloc():
    d=request.json or {}
    dwarf.set_location(float(d.get("lat",0)),float(d.get("lon",0)),float(d.get("alt",0)))
    return api_ok("Location set")

@app.route("/api/system/led_on",methods=["POST"])
@require_dwarf
def slo(): dwarf.led_on(); return api_ok()

@app.route("/api/system/led_off",methods=["POST"])
@require_dwarf
def slof(): dwarf.led_off(); return api_ok()

@app.route("/api/system/reboot",methods=["POST"])
@require_dwarf
def srb(): dwarf.reboot(); return api_ok("Rebooting...")

@app.route("/api/system/power_down",methods=["POST"])
@require_dwarf
def spd(): dwarf.power_down(); return api_ok("Powering down...")

@app.route("/snapshot")
def snapshot():
    """Capture a single JPEG frame from the tele stream and return it."""
    import cv2
    channel = request.args.get("channel", "ch0")
    if channel not in ("ch0", "ch1"):
        return api_err("channel must be ch0 or ch1")
    rtsp_url = f"rtsp://{TELESCOPE_IP}:554/{channel}/stream0"
    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    frame_data = None
    if cap.isOpened():
        # Skip a few frames to get past HEVC IDR wait
        for _ in range(5):
            cap.read()
        ret, frame = cap.read()
        if ret:
            h, w = frame.shape[:2]
            if w > 1920:
                frame = cv2.resize(frame, (1920, int(h*1920/w)))
            ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
            if ok:
                frame_data = jpg.tobytes()
    cap.release()
    if frame_data:
        from flask import send_file
        import io
        return send_file(io.BytesIO(frame_data), mimetype="image/jpeg",
                         as_attachment=True,
                         download_name=f"dwarf_{channel}_snapshot.jpg")
    return api_err("Could not capture frame — is the camera open?")

@app.route("/stream/info")
def stream_info():
    """Quick probe of RTSP stream availability."""
    import subprocess, json
    results = {}
    for ch, label in [("ch0","tele"), ("ch1","wide")]:
        url = f"rtsp://{TELESCOPE_IP}:554/{ch}/stream0"
        try:
            out = subprocess.check_output(
                ["ffprobe","-v","quiet","-rtsp_transport","tcp",
                 "-show_streams","-of","json", url],
                timeout=4, stderr=subprocess.DEVNULL
            )
            data = json.loads(out)
            s = data["streams"][0] if data.get("streams") else {}
            results[label] = {"up": True, "codec": s.get("codec_name","?"),
                               "width": s.get("width"), "height": s.get("height"),
                               "fps": s.get("r_frame_rate","?")}
        except Exception as e:
            results[label] = {"up": False, "error": str(e)}
    return jsonify({"telescope": TELESCOPE_IP, "streams": results})

@app.route("/")
def index():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"static","index.html")) as f:
        return f.read()

@socketio.on("connect")
def on_ws_connect():
    if dwarf:
        emit("status",{"connected":dwarf.state["connected"],"ip":TELESCOPE_IP,"state":dwarf.state})

def state_broadcaster():
    last_connected = None
    while True:
        time.sleep(2)
        if dwarf:
            cur_connected = dwarf.state.get("connected", False)
            # Emit full status event on connection state change
            if cur_connected != last_connected:
                socketio.emit("status", {"connected": cur_connected,
                                          "ip": TELESCOPE_IP, "state": dwarf.state})
                last_connected = cur_connected
                if cur_connected:
                    log.info("Telescope reconnected — emitting status")
            socketio.emit("state_update", dwarf.state)

if __name__ == "__main__":
    threading.Thread(target=connect_telescope,daemon=True).start()
    threading.Thread(target=state_broadcaster,daemon=True).start()
    print("DWARF Lab Web Controller")
    print("Telescope IP: " + TELESCOPE_IP)
    print("Open browser: http://localhost:5000")
    socketio.run(app,host="0.0.0.0",port=5000,debug=False,allow_unsafe_werkzeug=True)
