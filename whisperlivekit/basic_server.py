from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from whisperlivekit import TranscriptionEngine, AudioProcessor, get_web_interface_html, parse_args
import asyncio
import logging
import json
from typing import Dict
import uuid as uuid_lib

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logging.getLogger().setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

args = parse_args()
transcription_engine = None
# Store active sessions for multi-customer support
# Structure: session_uuid -> {customers: {customer_id: {...}}, session_info: {...}}
active_sessions: Dict[str, Dict] = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    global transcription_engine
    transcription_engine = TranscriptionEngine(
        **vars(args),
    )
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def get():
    return HTMLResponse(get_web_interface_html())


async def handle_websocket_results(websocket, results_generator):
    """Consumes results from the audio processor and sends them via WebSocket."""
    try:
        async for response in results_generator:
            await websocket.send_json(response)
        # when the results_generator finishes it means all audio has been processed
        logger.info("Results generator finished. Sending 'ready_to_stop' to client.")
        await websocket.send_json({"type": "ready_to_stop"})
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected while handling results (client likely closed connection).")
    except Exception as e:
        logger.error(f"Error in WebSocket results handler: {e}")


async def handle_websocket_results_multicam(websocket, results_generator, session_uuid, stream_id, customer_id):
    """Enhanced results handler with transcript logging and keyword detection."""
    try:
        async for response in results_generator:
            # Log transcript for monitoring
            if "lines" in response and response["lines"]:
                for line in response["lines"]:
                    transcript_text = line.get("text", "")
                    speaker = line.get("speaker", 0)
                    logger.info(f"🗣️ TRANSCRIPT [{session_uuid}][{customer_id}][{stream_id}] Speaker {speaker}: {transcript_text}")

                    # Keyword detection for experience events
                    transcript_lower = transcript_text.lower()
                    if "xin chào" in transcript_lower:
                        logger.info(f"🎉 KEYWORD DETECTED: SAY_HELLO - Session: {session_uuid}, Customer: {customer_id}")
                        # TODO: Call experience-event API here
                        # await call_experience_event_api(session_uuid, customer_id, "SAY_HELLO", transcript_text)
                    elif "xin lỗi" in transcript_lower:
                        logger.info(f"😔 KEYWORD DETECTED: SAY_SORRY - Session: {session_uuid}, Customer: {customer_id}")
                        # TODO: Call experience-event API here
                        # await call_experience_event_api(session_uuid, customer_id, "SAY_SORRY", transcript_text)

            # Log buffer content for debugging
            if "buffer_transcription" in response and response["buffer_transcription"]:
                logger.debug(f"📝 BUFFER [{session_uuid}][{customer_id}]: {response['buffer_transcription']}")

            # Add session metadata to response
            enhanced_response = {
                **response,
                "session_uuid": session_uuid,
                "customer_id": customer_id,
                "stream_id": stream_id,
                "timestamp": asyncio.get_event_loop().time()
            }
            await websocket.send_json(enhanced_response)

        # Send final message with session info
        logger.info(f"✅ Results generator finished for session {session_uuid}, customer {customer_id}, stream {stream_id}")
        await websocket.send_json({
            "type": "ready_to_stop",
            "data": {
                "session_uuid": session_uuid,
                "customer_id": customer_id,
                "stream_id": stream_id
            }
        })
    except WebSocketDisconnect:
        logger.info(f"🔌 WebSocket disconnected for session {session_uuid}, customer {customer_id}, stream {stream_id}")
    except Exception as e:
        logger.error(f"❌ Error in multicam WebSocket results handler: {e}")


@app.websocket("/asr")
async def websocket_endpoint(websocket: WebSocket):
    global transcription_engine
    audio_processor = AudioProcessor(
        transcription_engine=transcription_engine,
    )
    await websocket.accept()
    logger.info("WebSocket connection opened.")

    results_generator = await audio_processor.create_tasks()
    websocket_task = asyncio.create_task(handle_websocket_results(websocket, results_generator))

    try:
        while True:
            message = await websocket.receive_bytes()
            await audio_processor.process_audio(message)
    except KeyError as e:
        if 'bytes' in str(e):
            logger.warning("Client has closed the connection.")
        else:
            logger.error(f"Unexpected KeyError in websocket_endpoint: {e}", exc_info=True)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected by client during message receiving loop.")
    except Exception as e:
        logger.error(f"Unexpected error in websocket_endpoint main loop: {e}", exc_info=True)
    finally:
        logger.info("Cleaning up WebSocket endpoint...")
        if not websocket_task.done():
            websocket_task.cancel()
        try:
            await websocket_task
        except asyncio.CancelledError:
            logger.info("WebSocket results handler task was cancelled.")
        except Exception as e:
            logger.warning(f"Exception while awaiting websocket_task completion: {e}")

        await audio_processor.cleanup()
        logger.info("WebSocket endpoint cleaned up successfully.")


@app.websocket("/asr-multicam")
async def websocket_multicam_endpoint(websocket: WebSocket):
    """
    Enhanced WebSocket endpoint with multi-customer session support.

    Expected message formats:
    1. audio_stream_start - Initialize customer stream within session
    2. audio_chunk_meta - Metadata before each audio chunk
    3. Binary audio data - Actual audio chunks
    4. audio_stream_stop - End customer stream

    Multiple customers can share the same session_uuid with different customer_id/stream_id
    """
    global transcription_engine, active_sessions

    await websocket.accept()
    logger.info("🎤 Multi-camera WebSocket connection opened.")

    session_uuid = None
    customer_id = None
    stream_id = None
    audio_processor = None
    websocket_task = None
    stream_started = False
    expected_seq = 1

    try:
        while True:
            try:
                # Try to receive text message first (for control messages)
                message = await websocket.receive_text()
                data = json.loads(message)
                message_type = data.get("type")

                if message_type == "audio_stream_start":
                    # Initialize audio stream for customer
                    stream_data = data.get("data", {})
                    session_uuid = stream_data.get("session_uuid") or str(uuid_lib.uuid4())
                    customer_id = stream_data.get("customer_id") or stream_data.get("stream_id")  # fallback to stream_id
                    stream_id = stream_data.get("stream_id")
                    codec = stream_data.get("codec", "audio/webm;codecs=opus")
                    sample_rate = stream_data.get("sample_rate", 48000)
                    timeslice_ms = stream_data.get("timeslice_ms", 250)
                    client_ts = stream_data.get("client_ts")
                    metadata = stream_data.get("metadata", {})

                    if not stream_id:
                        await websocket.send_json({
                            "type": "error",
                            "message": "stream_id is required in audio_stream_start"
                        })
                        continue

                    if not customer_id:
                        await websocket.send_json({
                            "type": "error",
                            "message": "customer_id is required in audio_stream_start"
                        })
                        continue

                    # Initialize session if not exists
                    if session_uuid not in active_sessions:
                        active_sessions[session_uuid] = {
                            "customers": {},
                            "session_info": {
                                "start_time": asyncio.get_event_loop().time(),
                                "status": "active"
                            }
                        }

                    # Store customer info within session
                    active_sessions[session_uuid]["customers"][customer_id] = {
                        "stream_id": stream_id,
                        "codec": codec,
                        "sample_rate": sample_rate,
                        "timeslice_ms": timeslice_ms,
                        "metadata": metadata,
                        "start_time": asyncio.get_event_loop().time(),
                        "client_start_ts": client_ts,
                        "status": "active"
                    }

                    # Create audio processor for this session
                    audio_processor = AudioProcessor(
                        transcription_engine=transcription_engine,
                    )

                    # Send confirmation
                    await websocket.send_json({
                        "type": "audio_stream_ready",
                        "data": {
                            "session_uuid": session_uuid,
                            "customer_id": customer_id,
                            "stream_id": stream_id,
                            "message": "Audio stream initialized successfully"
                        }
                    })

                    logger.info(f"🚀 Audio stream started - Session: {session_uuid}, Customer: {customer_id}, Stream: {stream_id}, Codec: {codec}")
                    stream_started = True

                    # Start processing tasks
                    results_generator = await audio_processor.create_tasks()
                    websocket_task = asyncio.create_task(
                        handle_websocket_results_multicam(websocket, results_generator, session_uuid, stream_id, customer_id)
                    )

                elif message_type == "audio_chunk_meta":
                    # Audio chunk metadata
                    if not stream_started:
                        await websocket.send_json({
                            "type": "error",
                            "message": "Must send audio_stream_start first"
                        })
                        continue

                    chunk_data = data.get("data", {})
                    seq = chunk_data.get("seq", 0)
                    chunk_ts = chunk_data.get("ts")
                    duration_hint = chunk_data.get("duration_ms_hint", 250)

                    logger.debug(f"📦 Audio chunk meta - Seq: {seq}, TS: {chunk_ts}, Duration: {duration_hint}ms")

                    # Check sequence order
                    if seq != expected_seq and expected_seq > 1:
                        logger.warning(f"⚠️ Sequence mismatch - Expected: {expected_seq}, Got: {seq}")

                    expected_seq = seq + 1

                    # Now expect binary audio data next
                    audio_data = await websocket.receive_bytes()
                    if audio_processor and len(audio_data) > 0:
                        await audio_processor.process_audio(audio_data)
                        logger.debug(f"🎵 Processed audio chunk - {len(audio_data)} bytes")

                elif message_type == "audio_stream_stop":
                    # Stop audio stream for customer
                    stop_data = data.get("data", {})
                    stop_session_uuid = stop_data.get("session_uuid")
                    stop_customer_id = stop_data.get("customer_id")
                    stop_stream_id = stop_data.get("stream_id")
                    reason = stop_data.get("reason", "user_stopped")

                    logger.info(f"🛑 Audio stream stop - Session: {stop_session_uuid}, Customer: {stop_customer_id}, Stream: {stop_stream_id}, Reason: {reason}")

                    # Mark customer as stopped in session
                    if session_uuid in active_sessions and customer_id in active_sessions[session_uuid]["customers"]:
                        active_sessions[session_uuid]["customers"][customer_id]["status"] = "stopped"
                        active_sessions[session_uuid]["customers"][customer_id]["end_time"] = asyncio.get_event_loop().time()

                    # Send final empty audio to trigger processing completion
                    if audio_processor:
                        await audio_processor.process_audio(b"")

                    await websocket.send_json({
                        "type": "audio_stream_stopped",
                        "data": {
                            "session_uuid": session_uuid,
                            "customer_id": customer_id,
                            "stream_id": stream_id,
                            "message": "Audio stream stopped successfully"
                        }
                    })
                    break

                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Unknown message type: {message_type}"
                    })

            except json.JSONDecodeError:
                # If not JSON, might be binary audio data without metadata (fallback)
                if stream_started and audio_processor:
                    audio_data = await websocket.receive_bytes()
                    await audio_processor.process_audio(audio_data)
                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Invalid message format or stream not started"
                    })

    except WebSocketDisconnect:
        logger.info(f"🔌 WebSocket disconnected for session {session_uuid}, stream {stream_id}")
    except Exception as e:
        logger.error(f"❌ Unexpected error in multicam endpoint: {e}", exc_info=True)
    finally:
        logger.info(f"🧹 Cleaning up session {session_uuid}, customer {customer_id}...")

        # Cleanup customer from session
        if session_uuid and session_uuid in active_sessions and customer_id:
            if customer_id in active_sessions[session_uuid]["customers"]:
                active_sessions[session_uuid]["customers"][customer_id]["status"] = "closed"
                active_sessions[session_uuid]["customers"][customer_id]["end_time"] = asyncio.get_event_loop().time()

                # Check if all customers are closed, then close session
                all_customers_closed = all(
                    customer["status"] in ["closed", "stopped"]
                    for customer in active_sessions[session_uuid]["customers"].values()
                )
                if all_customers_closed:
                    active_sessions[session_uuid]["session_info"]["status"] = "closed"
                    active_sessions[session_uuid]["session_info"]["end_time"] = asyncio.get_event_loop().time()
                    logger.info(f"🏁 Session {session_uuid} fully closed - all customers disconnected")

        # Cancel websocket task
        if websocket_task and not websocket_task.done():
            websocket_task.cancel()
        try:
            if websocket_task:
                await websocket_task
        except asyncio.CancelledError:
            logger.info(f"📋 WebSocket results handler task cancelled for session {session_uuid}")
        except Exception as e:
            logger.warning(f"⚠️ Exception while awaiting websocket_task: {e}")

        # Cleanup audio processor
        if audio_processor:
            await audio_processor.cleanup()

        logger.info(f"✅ Multi-customer session {session_uuid}, customer {customer_id} cleaned up successfully.")





def main():
    """Entry point for the CLI command."""
    import uvicorn

    uvicorn_kwargs = {
        "app": "whisperlivekit.basic_server:app",
        "host":args.host,
        "port":args.port,
        "reload": False,
        "log_level": "info",
        "lifespan": "on",
    }

    ssl_kwargs = {}
    if args.ssl_certfile or args.ssl_keyfile:
        if not (args.ssl_certfile and args.ssl_keyfile):
            raise ValueError("Both --ssl-certfile and --ssl-keyfile must be specified together.")
        ssl_kwargs = {
            "ssl_certfile": args.ssl_certfile,
            "ssl_keyfile": args.ssl_keyfile
        }

    if ssl_kwargs:
        uvicorn_kwargs = {**uvicorn_kwargs, **ssl_kwargs}

    uvicorn.run(**uvicorn_kwargs)

if __name__ == "__main__":
    main()
