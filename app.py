
from flask import Flask, jsonify, render_template, request, send_file
from dotenv import load_dotenv
from groq import Groq
from io import BytesIO
from pydub import AudioSegment
from uuid import uuid4

import os
import asyncio
import edge_tts
import requests
import websocket
import json
import base64
import threading
import time


# ==========================================
# CONFIGURATION
# ==========================================

load_dotenv()

app = Flask(__name__)

API_URL = "https://api.liveavatar.com/v1"

LIVEAVATAR_API_KEY = os.getenv("LIVEAVATAR_API_KEY")
LIVEAVATAR_AVATAR_ID = os.getenv("LIVEAVATAR_AVATAR_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

current_session = {}

ws_lock = threading.Lock()

BYTES_PER_SECOND = 48000
FIRST_CHUNK_SIZE = int(BYTES_PER_SECOND * 0.6)
NEXT_CHUNK_SIZE = BYTES_PER_SECOND


# ==========================================
# LIVEAVATAR WEBSOCKET
# ==========================================

def connect_liveavatar_ws(ws_url):

    ws = websocket.create_connection(
        ws_url,
        timeout=15
    )

    ws.settimeout(1)

    deadline = time.time() + 30

    while time.time() < deadline:

        try:
            message = ws.recv()

        except websocket.WebSocketTimeoutException:
            continue

        if not message:
            continue

        try:
            event = json.loads(message)
        except (json.JSONDecodeError, TypeError):
            continue

        app.logger.info("LiveAvatar event: %s", event)

        if (
            event.get("type") == "session.state_updated"
            and event.get("state") == "connected"
        ):
            ws.settimeout(None)
            return ws

        if event.get("state") == "failed":
            ws.close()
            raise RuntimeError(
                f"LiveAvatar session failed: {event}"
            )

    ws.close()

    raise TimeoutError(
        "LiveAvatar connection timed out"
    )


# ==========================================
# LIVEAVATAR KEEP ALIVE
# ==========================================

def keep_alive_loop(ws, stop_event):

    while not stop_event.wait(120):

        try:
            with ws_lock:

                if not ws.connected:
                    break

                ws.send(json.dumps({
                    "type": "session.keep_alive",
                    "event_id": f"keepalive-{uuid4()}"
                }))

        except Exception:
            app.logger.exception(
                "LiveAvatar keep-alive failed"
            )
            break


# ==========================================
# SEND AUDIO TO AVATAR
# ==========================================

def send_audio_to_avatar(mp3_bytes):

    session = current_session.copy()

    ws = session.get("ws")

    if not ws or not ws.connected:
        raise RuntimeError(
            "LiveAvatar WebSocket is not connected"
        )

    audio = AudioSegment.from_file(
        BytesIO(mp3_bytes),
        format="mp3"
    )

    audio = (
        audio
        .set_channels(1)
        .set_frame_rate(24000)
        .set_sample_width(2)
    )

    pcm_data = audio.raw_data

    if not pcm_data:
        raise RuntimeError("Audio conversion produced no data")

    event_id = f"speak-{uuid4()}"

    offset = 0
    first_chunk = True

    with ws_lock:

        while offset < len(pcm_data):

            if first_chunk:
                chunk_size = FIRST_CHUNK_SIZE
            else:
                chunk_size = NEXT_CHUNK_SIZE

            chunk = pcm_data[
                offset:offset + chunk_size
            ]

            offset += len(chunk)

            ws.send(json.dumps({
                "type": "agent.speak",
                "event_id": event_id,
                "audio": base64.b64encode(
                    chunk
                ).decode("utf-8")
            }))

            first_chunk = False

        ws.send(json.dumps({
            "type": "agent.speak_end",
            "event_id": event_id
        }))

    app.logger.info("Avatar audio sent successfully")


# ==========================================
# HOME PAGE
# ==========================================

@app.route("/")
def home():

    return render_template("index.html")


# ==========================================
# CREATE LIVEAVATAR SESSION
# ==========================================

@app.route("/api/create-session", methods=["POST"])
def create_session():

    if not LIVEAVATAR_API_KEY or not LIVEAVATAR_AVATAR_ID:

        return jsonify({
            "error": "LiveAvatar API key or Avatar ID missing in .env"
        }), 500

    new_ws = None

    try:

        # STEP 1: CREATE SESSION TOKEN

        token_response = requests.post(
            f"{API_URL}/sessions/token",
            headers={
                "X-API-KEY": LIVEAVATAR_API_KEY,
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            json={
                "mode": "LITE",
                "avatar_id": LIVEAVATAR_AVATAR_ID,
                "is_sandbox": False
            },
            timeout=30
        )

        if not token_response.ok:

            app.logger.error(
                "Token creation failed: %s",
                token_response.text
            )

            return jsonify({
                "error": "LiveAvatar token creation failed",
                "status": token_response.status_code,
                "details": token_response.text
            }), 502

        token_data = token_response.json()["data"]

        token = token_data["session_token"]
        session_id = token_data["session_id"]

        # STEP 2: START SESSION

        start_response = requests.post(
            f"{API_URL}/sessions/start",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json"
            },
            timeout=60
        )

        if not start_response.ok:

            app.logger.error(
                "LiveAvatar start failed: HTTP %s | %s",
                start_response.status_code,
                start_response.text
            )

            return jsonify({
                "error": "LiveAvatar failed to start",
                "status": start_response.status_code,
                "details": start_response.text
            }), 502

        start_data = start_response.json()["data"]

        livekit_url = start_data.get("livekit_url")
        livekit_client_token = start_data.get(
            "livekit_client_token"
        )
        ws_url = start_data.get("ws_url")

        if not livekit_url or not livekit_client_token:
            raise RuntimeError(
                "LiveAvatar did not return LiveKit details"
            )

        if not ws_url:
            raise RuntimeError(
                "LiveAvatar did not return WebSocket URL"
            )

        # STEP 3: CONNECT WEBSOCKET

        new_ws = connect_liveavatar_ws(ws_url)

        # STEP 4: CLEAN PREVIOUS SESSION

        old_session = current_session.copy()

        if old_session.get("stop_event"):
            old_session["stop_event"].set()

        if old_session.get("ws"):
            try:
                old_session["ws"].close()
            except Exception:
                pass

        # STEP 5: SAVE CURRENT SESSION

        stop_event = threading.Event()

        current_session.clear()

        current_session.update({
            "token": token,
            "id": session_id,
            "ws": new_ws,
            "stop_event": stop_event
        })

        # STEP 6: START KEEP ALIVE

        threading.Thread(
            target=keep_alive_loop,
            args=(new_ws, stop_event),
            daemon=True
        ).start()

        app.logger.info(
            "LiveAvatar session connected: %s",
            session_id
        )

        return jsonify({
            "session_id": session_id,
            "livekit_url": livekit_url,
            "livekit_client_token": livekit_client_token,
            "ws_ready": True
        })

    except Exception as error:

        if new_ws:
            try:
                new_ws.close()
            except Exception:
                pass

        app.logger.exception(
            "Session creation failed"
        )

        return jsonify({
            "error": str(error)
        }), 502


# ==========================================
# STOP LIVEAVATAR SESSION
# ==========================================

@app.route("/api/stop-session", methods=["POST"])
def stop_session():

    session = current_session.copy()

    token = session.get("token")
    session_id = session.get("id")
    ws = session.get("ws")
    stop_event = session.get("stop_event")

    if not token or not session_id:

        return jsonify({
            "error": "No active session"
        }), 400

    try:

        if stop_event:
            stop_event.set()

        if ws:
            try:
                ws.close()
            except Exception:
                pass

        response = requests.delete(
            f"{API_URL}/sessions",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json"
            },
            timeout=30
        )

        if not response.ok:

            app.logger.error(
                "Session stop failed: HTTP %s | %s",
                response.status_code,
                response.text
            )

            return jsonify({
                "error": "Could not stop LiveAvatar session",
                "status": response.status_code,
                "details": response.text
            }), 502

        current_session.clear()

        return jsonify({
            "message": "Daniel session stopped successfully"
        })

    except Exception as error:

        app.logger.exception("Session stop failed")

        return jsonify({
            "error": str(error)
        }), 502


# ==========================================
# WHISPER + GROQ VOICE CHAT
# ==========================================

@app.route("/api/voice-chat", methods=["POST"])
def voice_chat():

    if not groq_client:

        return jsonify({
            "error": "Groq API key missing"
        }), 500

    if "audio" not in request.files:

        return jsonify({
            "error": "No audio received"
        }), 400

    try:

        audio = request.files["audio"]

        transcription = groq_client.audio.transcriptions.create(
            file=(
                audio.filename or "recording.webm",
                audio.read()
            ),
            model="whisper-large-v3-turbo",
            language="en"
        )

        question = transcription.text.strip()

        if not question:

            return jsonify({
                "error": "No speech detected"
            }), 400

        completion = groq_client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Daniel, a friendly male AI assistant. "
                        "Give clear, helpful and natural answers. "
                        "Keep spoken responses concise."
                    )
                },
                {
                    "role": "user",
                    "content": question
                }
            ],
            max_tokens=500
        )

        answer = completion.choices[0].message.content

        return jsonify({
            "question": question,
            "answer": answer
        })

    except Exception as error:

        app.logger.exception("Voice chat failed")

        return jsonify({
            "error": str(error)
        }), 500


# ==========================================
# EDGE TTS + AVATAR SPEECH
# ==========================================

@app.route("/api/tts", methods=["POST"])
def text_to_speech():

    try:

        data = request.get_json(silent=True) or {}

        text = data.get("text", "").strip()

        if not text:

            return jsonify({
                "error": "No text provided"
            }), 400

        if not current_session.get("ws"):

            return jsonify({
                "error": "Daniel's LiveAvatar session is not connected"
            }), 400

        async def generate_audio():

            communicate = edge_tts.Communicate(
                text,
                "en-US-GuyNeural"
            )

            audio_buffer = BytesIO()

            async for chunk in communicate.stream():

                if chunk["type"] == "audio":
                    audio_buffer.write(chunk["data"])

            audio_buffer.seek(0)

            return audio_buffer

        audio_buffer = asyncio.run(generate_audio())

        mp3_bytes = audio_buffer.getvalue()

        # SEND AUDIO TO LIVEAVATAR

        send_audio_to_avatar(mp3_bytes)

        # RETURN MP3 TO FRONTEND

        return send_file(
            BytesIO(mp3_bytes),
            mimetype="audio/mpeg",
            download_name="daniel.mp3"
        )

    except Exception as error:

        app.logger.exception(
            "Text-to-speech failed"
        )

        return jsonify({
            "error": str(error)
        }), 500


# ==========================================
# START FLASK SERVER
# ==========================================

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True,
        threaded=True
    )
