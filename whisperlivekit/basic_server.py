import asyncio
import logging
from contextlib import asynccontextmanager
import os
from typing import Optional

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

    event_map = {
        "xin chào": "SAY_HELLO",
        "xin lỗi": "SAY_SORRY",
        "tạm biệt": "SAY_GOODBYE",
    }
    event_code = event_map.get(event)
    if not event_code:
        logger.warning(f"No mapping found for event={event}, skip.")
        return

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{API_BASE}/latest/waiting-to-pay",
                json={"camera_id": camera_id},
                headers={
                    "Content-Type": "application/json",
                    "accept": "*/*",
                },
            )
            resp.raise_for_status()
            uuid = resp.json().get("uuid")
            if not uuid:
                logger.warning(f"Cannot get uuid for camera_id={camera_id}")
                return

            payload = {
                "event": event_code,
                "voice_text": voice_text,
                "camera_id": camera_id,
                "actor_id": ACTOR_ID,
                "uuid": uuid,
            }
            post_resp = await client.post(
                API_BASE,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "accept": "*/*",
                },
            )
            post_resp.raise_for_status()
            logger.info(f"[DB] Saved event {event_code} for camera_id={camera_id}, uuid={uuid}")

        except Exception as e:
            logger.error(f"Error saving event to DB: {e}")


async def handle_websocket_results_v2(
    websocket,
    results_generator,
    camera_id: Optional[str] = None,
):
    last_event = None

    try:
        async for response in results_generator:
            await websocket.send_json(response)

            lines = response.get("lines", [])
            last_line_with_text = None
            for line in reversed(lines):
                if line.get("text", "").strip():
                    last_line_with_text = line
                    break

            if not last_line_with_text:
                continue

            text = last_line_with_text.get("text", "").lower()

            new_event = None
            if "xin chào" in text:
                new_event = "xin chào"
            elif "xin lỗi" in text:
                new_event = "xin lỗi"
            elif "tạm biệt" in text:
                new_event = "tạm biệt"

            if new_event and new_event != last_event:
                await save_event_to_db(
                    camera_id,
                    new_event,
                    last_line_with_text["text"],
                )
                last_event = new_event

        logger.info("Results generator finished. Sending 'ready_to_stop' to client.")
        await websocket.send_json({"type": "ready_to_stop"})

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected (camera_id={camera_id})")

    except Exception as e:
        logger.error(f"Error in WebSocket results handler (camera_id={camera_id}): {e}")


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
        if "bytes" in str(e):
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


@app.websocket("/asr-v2")
async def websocket_endpoint_v2(
    websocket: WebSocket,
    camera_id: Optional[str] = Query(None, description="The unique ID of camera"),
):
    global transcription_engine
    audio_processor = AudioProcessor(
        transcription_engine=transcription_engine,
    )
    await websocket.accept()
    logger.info("WebSocket connection opened.")

    results_generator = await audio_processor.create_tasks()
    websocket_task = asyncio.create_task(handle_websocket_results_v2(websocket, results_generator, camera_id))

    try:
        while True:
            message = await websocket.receive_bytes()
            await audio_processor.process_audio(message)

    except KeyError as e:
        if "bytes" in str(e):
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
