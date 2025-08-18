<h1 align="center">WhisperLiveKit</h1>

<p align="center">
<img src="https://raw.githubusercontent.com/QuentinFuxa/WhisperLiveKit/refs/heads/main/demo.png" alt="WhisperLiveKit Demo" width="730">
</p>

<p align="center"><b>Real-time, Fully Local Speech-to-Text with Speaker Diarization</b></p>

<p align="center">
<a href="https://pypi.org/project/whisperlivekit/"><img alt="PyPI Version" src="https://img.shields.io/pypi/v/whisperlivekit?color=g"></a>
<a href="https://pepy.tech/project/whisperlivekit"><img alt="PyPI Downloads" src="https://static.pepy.tech/personalized-badge/whisperlivekit?period=total&units=international_system&left_color=grey&right_color=brightgreen&left_text=downloads"></a>
<a href="https://pypi.org/project/whisperlivekit/"><img alt="Python Versions" src="https://img.shields.io/badge/python-3.9--3.13-dark_green"></a>
<a href="https://github.com/QuentinFuxa/WhisperLiveKit/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/badge/License-MIT/Dual Licensed-dark_green"></a>
</p>


WhisperLiveKit brings real-time speech transcription directly to your browser, with a ready-to-use backend+server and a simple frontend. ✨

#### Powered by Leading Research:

- [SimulStreaming](https://github.com/ufal/SimulStreaming) (SOTA 2025) - Ultra-low latency transcription with AlignAtt policy
- [WhisperStreaming](https://github.com/ufal/whisper_streaming) (SOTA 2023) - Low latency transcription with LocalAgreement policy
- [Streaming Sortformer](https://arxiv.org/abs/2507.18446) (SOTA 2025) - Advanced real-time speaker diarization
- [Diart](https://github.com/juanmc2005/diart) (SOTA 2021) - Real-time speaker diarization
- [Silero VAD](https://github.com/snakers4/silero-vad) (2024) - Enterprise-grade Voice Activity Detection


### Key Features

- **Real-time Transcription** - Locally (or on-prem) convert speech to text instantly as you speak
- **Speaker Diarization** - Identify different speakers in real-time.
- **Voice Activity Detection** – Reduce processing overhead when no voice is detected.
- **Punctuation-Based Speaker Splitting** - Align speaker changes with natural sentence boundaries.
- **Confidence Validation** – Immediately validate high-confidence tokens (WhisperStreaming only)
- **SimulStreaming Backend** - [Dual-licensed](https://github.com/ufal/SimulStreaming#-licence-and-contributions) - Ultra-low latency transcription using SOTA AlignAtt policy. 
- **Multi-User Support** - Handle multiple users simultaneously with a single backend/server


### Architecture

<img alt="Architecture" src="architecture.png" />

### Installation & Quick Start

```bash
pip install whisperlivekit
```

>  **FFmpeg is required** and must be installed before using WhisperLiveKit
> 
> | OS | How to install |
> |-----------|-------------|
>  | Ubuntu/Debian | `sudo apt install ffmpeg` |
> | MacOS | `brew install ffmpeg` |
> | Windows | Download .exe from https://ffmpeg.org/download.html and add to PATH |

#### Quick Start
1. **Start the transcription server:**
   ```bash
   whisperlivekit-server --model tiny.en
   ```

2. **Open your browser** and navigate to `http://localhost:8000`

3. **Start speaking** and watch your words appear in real-time!

> For production use or HTTPS requirements, see the [Parameters](#parameters) section for SSL configuration options.

#### Optional Dependencies

```bash

pip install whisperlivekit[diarization] # Speaker diarization

# Alternative Whisper backends (default is faster-whisper)
pip install whisperlivekit[whisper]              # Original Whisper
pip install whisperlivekit[whisper-timestamped]  # Improved timestamps
pip install whisperlivekit[mlx-whisper]          # Apple Silicon optimization
pip install whisperlivekit[openai]               # OpenAI API
```

 
> **Pyannote Models Setup** For diarization, you need access to pyannote.audio models:
> 1. [Accept user conditions](https://huggingface.co/pyannote/segmentation) for the `pyannote/segmentation` model
> 2. [Accept user conditions](https://huggingface.co/pyannote/segmentation-3.0) for the `pyannote/segmentation-3.0` model
> 3. [Accept user conditions](https://huggingface.co/pyannote/embedding) for the `pyannote/embedding` model
>4. Login with HuggingFace:
> ```bash
> huggingface-cli login
> ```

## 💻 Usage Examples

#### Command-line Interface

Start the transcription server with various options:

```bash
# Advanced configuration with diarization
whisperlivekit-server --host 0.0.0.0 --port 8000 --model medium --diarization --language auto

# SimulStreaming backend for ultra-low latency
whisperlivekit-server --backend simulstreaming --model large-v3 --frame-threshold 20
```


#### Python API Integration (Backend)
Check [basic_server](https://github.com/QuentinFuxa/WhisperLiveKit/blob/main/whisperlivekit/basic_server.py) for a more complete example of how to use the functions and classes.

```python
from whisperlivekit import TranscriptionEngine, AudioProcessor, parse_args
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
import asyncio

transcription_engine = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global transcription_engine
    transcription_engine = TranscriptionEngine(model="medium", diarization=True, lan="en")
    yield

app = FastAPI(lifespan=lifespan)

async def handle_websocket_results(websocket: WebSocket, results_generator):
    async for response in results_generator:
        await websocket.send_json(response)
    await websocket.send_json({"type": "ready_to_stop"})

@app.websocket("/asr")
async def websocket_endpoint(websocket: WebSocket):
    global transcription_engine

    # Create a new AudioProcessor for each connection, passing the shared engine
    audio_processor = AudioProcessor(transcription_engine=transcription_engine)    
    results_generator = await audio_processor.create_tasks()
    results_task = asyncio.create_task(handle_websocket_results(websocket, results_generator))
    await websocket.accept()
    while True:
        message = await websocket.receive_bytes()
        await audio_processor.process_audio(message)        
```

#### Frontend Implementation

The package includes an HTML/JavaScript implementation [here](https://github.com/QuentinFuxa/WhisperLiveKit/blob/main/whisperlivekit/web/live_transcription.html)

```python
from whisperlivekit import get_web_interface_html #You can also import it in your code
html_content = get_web_interface_html()
```

### ⚙️ Configuration Reference

WhisperLiveKit offers extensive configuration options:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--host` | Server host address | `localhost` |
| `--port` | Server port | `8000` |
| `--model` | Whisper model size. Caution : '.en' models do not work with Simulstreaming | `tiny` |
| `--language` | Source language code or `auto` | `en` |
| `--task` | `transcribe` or `translate` | `transcribe` |
| `--backend` | Processing backend | `faster-whisper` |
| `--diarization` | Enable speaker identification | `False` |
| `--punctuation-split` | Use punctuation to improve speaker boundaries | `True` |
| `--confidence-validation` | Use confidence scores for faster validation | `False` |
| `--min-chunk-size` | Minimum audio chunk size (seconds) | `1.0` |
| `--no-vac` | Disable Voice Activity Controller | `False` |
| `--no-vad` | Disable Voice Activity Detection | `False` |
| `--buffer_trimming` | Buffer trimming strategy (`sentence` or `segment`) | `segment` |
| `--warmup-file` | Audio file path for model warmup | `jfk.wav` |
| `--ssl-certfile` | Path to the SSL certificate file (for HTTPS support) | `None` |
| `--ssl-keyfile` | Path to the SSL private key file (for HTTPS support) | `None` |
| `--segmentation-model` | Hugging Face model ID for pyannote.audio segmentation model. [Available models](https://github.com/juanmc2005/diart/tree/main?tab=readme-ov-file#pre-trained-models) | `pyannote/segmentation-3.0` |
| `--embedding-model` | Hugging Face model ID for pyannote.audio embedding model. [Available models](https://github.com/juanmc2005/diart/tree/main?tab=readme-ov-file#pre-trained-models) | `speechbrain/spkrec-ecapa-voxceleb` |

**SimulStreaming-specific Options:**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--frame-threshold` | AlignAtt frame threshold (lower = faster, higher = more accurate) | `25` |
| `--beams` | Number of beams for beam search (1 = greedy decoding) | `1` |
| `--decoder` | Force decoder type (`beam` or `greedy`) | `auto` |
| `--audio-max-len` | Maximum audio buffer length (seconds) | `30.0` |
| `--audio-min-len` | Minimum audio length to process (seconds) | `0.0` |
| `--cif-ckpt-path` | Path to CIF model for word boundary detection | `None` |
| `--never-fire` | Never truncate incomplete words | `False` |
| `--init-prompt` | Initial prompt for the model | `None` |
| `--static-init-prompt` | Static prompt that doesn't scroll | `None` |
| `--max-context-tokens` | Maximum context tokens | `None` |
| `--model-path` | Direct path to .pt model file. Download it if not found | `./base.pt` |
| `--preloaded-model-count` | Optional. Number of models to preload in memory to speed up loading (set up to the expected number of concurrent users) | `1` |


### 🚀 Deployment Guide

To deploy WhisperLiveKit in production:

1. **Server Setup** (Backend):
   ```bash
   # Install production ASGI server
   pip install uvicorn gunicorn

   # Launch with multiple workers
   gunicorn -k uvicorn.workers.UvicornWorker -w 4 your_app:app
   ```

2. **Frontend**: Host your customized version of the `html` example & ensure WebSocket connection points correctly

3. **Nginx Configuration** (recommended for production):
    ```nginx    
   server {
       listen 80;
       server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }}
    ```

4. **HTTPS Support**: For secure deployments, use "wss://" instead of "ws://" in WebSocket URL

### 🐋 Docker

A basic Dockerfile is provided which allows re-use of Python package installation options. ⚠️ For **large** models, ensure that your **docker runtime** has enough **memory** available. See below usage examples:


#### All defaults
- Create a reusable image with only the basics and then run as a named container:
    ```bash
    docker build -t whisperlivekit-defaults .
    docker create --gpus all --name whisperlivekit -p 8000:8000 whisperlivekit-defaults --model base
    docker start -i whisperlivekit
    ```

    > **Note**: If you're running on a system without NVIDIA GPU support (such as Mac with Apple Silicon or any system without CUDA capabilities), you need to **remove the `--gpus all` flag** from the `docker create` command. Without GPU acceleration, transcription will use CPU only, which may be significantly slower. Consider using small models for better performance on CPU-only systems.

#### Customization

- `--build-arg` Options:
  - `EXTRAS="whisper-timestamped"` - Add extras to the image's installation (no spaces). Remember to set necessary container options!
  - `HF_PRECACHE_DIR="./.cache/"` - Pre-load a model cache for faster first-time start
  - `HF_TKN_FILE="./token"` - Add your Hugging Face Hub access token to download gated models

#### 🔮 Use Cases
Capture discussions in real-time for meeting transcription, help hearing-impaired users follow conversations through accessibility tools, transcribe podcasts or videos automatically for content creation, transcribe support calls with speaker identification for customer service...
