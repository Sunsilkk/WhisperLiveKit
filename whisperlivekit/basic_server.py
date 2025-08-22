import asyncio
import logging
from contextlib import asynccontextmanager
import os
from typing import Optional
from dotenv import load_dotenv
import time

import httpx
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from whisperlivekit import AudioProcessor, TranscriptionEngine, get_web_interface_html, parse_args

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logging.getLogger().setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

args = parse_args()
transcription_engine = None

load_dotenv()
API_BASE = os.getenv("API_BASE")
ACTOR_ID = os.getenv("ACTOR_ID")


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


async def handle_websocket_results(
    websocket,
    results_generator,
    camera_id: Optional[str] = None,
):
    try:
        async for response in results_generator:
            await websocket.send_json(response)

        logger.info("Results generator finished. Sending 'ready_to_stop' to client.")
        await websocket.send_json({"type": "ready_to_stop"})

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected (camera_id={camera_id})")

    except Exception as e:
        logger.error(f"Error in WebSocket results handler (camera_id={camera_id}): {e}")


async def save_event_to_db(
    camera_id: Optional[str],
    event: str,
    voice_text: str,
):
    if not camera_id:
        logger.warning("camera_id is None, skip saving event.")
        return

    if not API_BASE:
        logger.warning("API_BASE is not configured, skip saving event.")
        return

    event_map = {
        "xin chào": "SAY_HELLO",
        "xin lỗi": "SAY_SORRY",
        "cảm ơn": "SAY_GOODBYE",
    }
    event_code = event_map.get(event)
    if not event_code:
        logger.warning(f"No mapping found for event={event}, skip.")
        return

    async with httpx.AsyncClient() as client:
        try:
            # resp = await client.post(
            #     f"{API_BASE}/latest/uuid-waiting-to-pay",
            #     json={"camera_id": camera_id},
            #     headers={
            #         "Content-Type": "application/json",
            #         "accept": "*/*",
            #     },
            # )
            # resp.raise_for_status()
            # uuid = resp.json().get("data", {}).get("uuid")
            uuid = "vanlinhtruongdang"
            if not uuid:
                logger.warning(f"Cannot get uuid for camera_id={camera_id}")
                return

            post_resp = await client.post(
                API_BASE,
                json={
                    "event": event_code,
                    "voice_text": voice_text,
                    "camera_id": camera_id,
                    # "actor_id": ACTOR_ID,
                    "uuid": uuid,
                },
                headers={
                    "Content-Type": "application/json",
                    "accept": "*/*",
                },
            )
            post_resp.raise_for_status()
            logger.info(f"[DB] Saved event {event_code} for camera_id={camera_id}, uuid={uuid}")

        except Exception as e:
            logger.error(f"Error saving event to DB: {e}")


async def process_lines_worker(camera_id, response, event_state_ref):
    try:
        lines = response.get("lines", [])
        last_line_with_text = None
        for line in reversed(lines):
            if line.get("text", "").strip():
                last_line_with_text = line
                break

        if not last_line_with_text:
            return

        text = last_line_with_text.get("text", "").lower().strip()

        # More strict pattern matching
        new_event = None
        if "xin chào" in text:
            new_event = "xin chào"
        if "xin lỗi" in text:
            new_event = "xin lỗi"
        if "cảm ơn" in text:
            new_event = "cảm ơn"

        if new_event:
            last_event = event_state_ref[0]

            if new_event != last_event:
                logger.info(f"Triggering event: {new_event} for camera {camera_id}")
                await save_event_to_db(
                    camera_id,
                    new_event,
                    last_line_with_text["text"],
                )
                event_state_ref[0] = new_event

    except Exception as e:
        logger.error(f"Error in process_lines_worker (camera_id={camera_id}): {e}")


async def handle_websocket_results_v2(
    websocket,
    results_generator,
    camera_id: Optional[str] = None,
):
    event_state_ref = [None]

    try:
        async for response in results_generator:
            await websocket.send_json(response)
            asyncio.create_task(
                process_lines_worker(
                    camera_id,
                    response,
                    event_state_ref,
                )
            )

        logger.info("Results generator finished. Sending 'ready_to_stop' to client.")
        await websocket.send_json({"type": "ready_to_stop"})

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected (camera_id={camera_id})")
    except Exception as e:
        logger.error(f"Error in WebSocket results handler (camera_id={camera_id}): {e}")


@app.websocket("/asr")
async def websocket_endpoint(websocket: WebSocket):
    global transcription_engine
    client_ip = websocket.client.host if websocket.client else "unknown"
    logger.info(f"New WebSocket connection from {client_ip}")

    try:
        audio_processor = AudioProcessor(
            transcription_engine=transcription_engine,
        )
        await websocket.accept()
        logger.info(f"WebSocket connection accepted for {client_ip}")

        results_generator = await audio_processor.create_tasks()
        logger.info(f"Audio processor tasks created for {client_ip}")

        websocket_task = asyncio.create_task(handle_websocket_results(websocket, results_generator))

        message_count = 0
        try:
            while True:
                logger.debug(f"Waiting for message from {client_ip}")
                message = await websocket.receive_bytes()
                message_count += 1
                logger.debug(f"Received message #{message_count} from {client_ip}, size: {len(message)} bytes")
                await audio_processor.process_audio(message)

        except KeyError as e:
            if "bytes" in str(e):
                logger.warning(f"Client {client_ip} has closed the connection (KeyError: {e})")
            else:
                logger.error(f"Unexpected KeyError in websocket_endpoint for {client_ip}: {e}", exc_info=True)

        except WebSocketDisconnect as e:
            logger.info(f"WebSocket disconnected by client {client_ip} during message receiving loop. Code: {e.code}, Reason: {e.reason}")

        except Exception as e:
            logger.error(f"Unexpected error in websocket_endpoint main loop for {client_ip}: {e}", exc_info=True)

    except Exception as e:
        logger.error(f"Error during WebSocket setup for {client_ip}: {e}", exc_info=True)

    finally:
        logger.info(f"Cleaning up WebSocket endpoint for {client_ip}...")
        if not websocket_task.done():
            websocket_task.cancel()
        try:
            await websocket_task
        except asyncio.CancelledError:
            logger.info("WebSocket results handler task was cancelled.")
        except Exception as e:
            logger.warning(f"Exception while awaiting websocket_task completion: {e}")

        await audio_processor.cleanup()
        logger.info(f"WebSocket endpoint cleaned up successfully for {client_ip}.")


@app.websocket("/asr-v2")
async def websocket_endpoint_v2(
    websocket: WebSocket,
    camera_id: Optional[str] = Query(None, description="The unique ID of camera"),
):
    global transcription_engine
    client_ip = websocket.client.host if websocket.client else "unknown"
    logger.info(f"New WebSocket v2 connection from {client_ip}, camera_id={camera_id}")

    try:
        audio_processor = AudioProcessor(
            transcription_engine=transcription_engine,
        )
        await websocket.accept()
        logger.info(f"WebSocket v2 connection accepted for {client_ip}, camera_id={camera_id}")

        results_generator = await audio_processor.create_tasks()
        logger.info(f"Audio processor tasks created for {client_ip}, camera_id={camera_id}")

        websocket_task = asyncio.create_task(handle_websocket_results_v2(websocket, results_generator, camera_id))

        message_count = 0
        try:
            while True:
                logger.debug(f"Waiting for message from {client_ip}, camera_id={camera_id}")
                message = await websocket.receive_bytes()
                message_count += 1
                logger.debug(f"Received message #{message_count} from {client_ip}, camera_id={camera_id}, size: {len(message)} bytes")
                await audio_processor.process_audio(message)

        except KeyError as e:
            if "bytes" in str(e):
                logger.warning(f"Client {client_ip} (camera_id={camera_id}) has closed the connection (KeyError: {e})")
            else:
                logger.error(f"Unexpected KeyError in websocket_endpoint for {client_ip} (camera_id={camera_id}): {e}", exc_info=True)

        except WebSocketDisconnect as e:
            logger.info(f"WebSocket disconnected by client {client_ip} (camera_id={camera_id}) during message receiving loop. Code: {e.code}, Reason: {e.reason}")

        except Exception as e:
            logger.error(f"Unexpected error in websocket_endpoint main loop for {client_ip} (camera_id={camera_id}): {e}", exc_info=True)

    except Exception as e:
        logger.error(f"Error during WebSocket v2 setup for {client_ip} (camera_id={camera_id}): {e}", exc_info=True)

    finally:
        logger.info(f"Cleaning up WebSocket v2 endpoint for {client_ip}, camera_id={camera_id}...")
        if not websocket_task.done():
            websocket_task.cancel()
        try:
            await websocket_task
        except asyncio.CancelledError:
            logger.info("WebSocket results handler task was cancelled.")

        except Exception as e:
            logger.warning(f"Exception while awaiting websocket_task completion: {e}")

        await audio_processor.cleanup()
        logger.info(f"WebSocket v2 endpoint cleaned up successfully for {client_ip}, camera_id={camera_id}.")


def main():
    """Entry point for the CLI command."""
    import uvicorn

    uvicorn_kwargs = {
        "app": "whisperlivekit.basic_server:app",
        "host": args.host,
        "port": args.port,
        "reload": False,
        "log_level": "info",
        "lifespan": "on",
    }

    ssl_kwargs = {}
    if args.ssl_certfile or args.ssl_keyfile:
        if not (args.ssl_certfile and args.ssl_keyfile):
            raise ValueError("Both --ssl-certfile and --ssl-keyfile must be specified together.")
        ssl_kwargs = {"ssl_certfile": args.ssl_certfile, "ssl_keyfile": args.ssl_keyfile}

    if ssl_kwargs:
        uvicorn_kwargs = {**uvicorn_kwargs, **ssl_kwargs}

    uvicorn.run(**uvicorn_kwargs)


if __name__ == "__main__":
    main()
