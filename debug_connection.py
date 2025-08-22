#!/usr/bin/env python3
"""
Debug script để kiểm tra FFmpeg và connection issues với WhisperLiveKit
"""

import asyncio
import subprocess
import sys
import logging
import websockets
import json
import os
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def check_ffmpeg():
    """Kiểm tra xem FFmpeg có được cài đặt không"""
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            version_line = result.stdout.split('\n')[0]
            logger.info(f"✅ FFmpeg found: {version_line}")
            return True
        else:
            logger.error(f"❌ FFmpeg error: {result.stderr}")
            return False
    except FileNotFoundError:
        logger.error("❌ FFmpeg not found in PATH")
        return False
    except subprocess.TimeoutExpired:
        logger.error("❌ FFmpeg command timeout")
        return False
    except Exception as e:
        logger.error(f"❌ Error checking FFmpeg: {e}")
        return False

def check_dependencies():
    """Kiểm tra các dependencies cần thiết"""
    required_packages = [
        'fastapi',
        'websockets',
        'torch',
        'transformers',
        'numpy',
        'scipy'
    ]

    missing_packages = []
    for package in required_packages:
        try:
            __import__(package)
            logger.info(f"✅ {package} found")
        except ImportError:
            missing_packages.append(package)
            logger.error(f"❌ {package} not found")

    return len(missing_packages) == 0, missing_packages

async def test_websocket_connection(url="ws://localhost:8000/asr"):
    """Test WebSocket connection"""
    logger.info(f"Testing WebSocket connection to {url}")

    try:
        async with websockets.connect(url) as websocket:
            logger.info("✅ WebSocket connection established")

            # Send test audio data (empty bytes to trigger stop)
            test_data = b'\x00' * 1024  # 1KB of silence
            await websocket.send(test_data)
            logger.info("✅ Test data sent")

            # Try to receive response
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                logger.info(f"✅ Received response: {response[:100]}...")
            except asyncio.TimeoutError:
                logger.warning("⚠️ No response received within 5 seconds")

            # Send empty message to stop
            await websocket.send(b'')
            logger.info("✅ Stop signal sent")

    except websockets.exceptions.ConnectionClosed as e:
        logger.error(f"❌ WebSocket connection closed: code={e.code}, reason={e.reason}")
    except ConnectionRefusedError:
        logger.error("❌ Connection refused - server might not be running")
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}")

async def test_local_ffmpeg():
    """Test FFmpeg subprocess directly"""
    logger.info("Testing FFmpeg subprocess...")

    try:
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-i", "pipe:0",
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-ac", "1",
            "-ar", "16000",
            "pipe:1"
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        logger.info("✅ FFmpeg process started")

        # Send test audio data
        test_audio = b'\x00' * 3200  # 0.1 second of silence at 16kHz
        process.stdin.write(test_audio)
        await process.stdin.drain()

        # Try to read output
        try:
            output = await asyncio.wait_for(process.stdout.read(1024), timeout=2.0)
            logger.info(f"✅ FFmpeg processed {len(output)} bytes")
        except asyncio.TimeoutError:
            logger.warning("⚠️ FFmpeg output timeout")

        # Clean shutdown
        process.stdin.close()
        await process.stdin.wait_closed()
        await process.wait()
        logger.info("✅ FFmpeg process terminated cleanly")

    except Exception as e:
        logger.error(f"❌ FFmpeg subprocess error: {e}")

def check_system_resources():
    """Kiểm tra system resources"""
    import psutil

    logger.info("System Resources:")
    logger.info(f"  CPU count: {psutil.cpu_count()}")
    logger.info(f"  Memory: {psutil.virtual_memory().total / (1024**3):.1f} GB")
    logger.info(f"  Available memory: {psutil.virtual_memory().available / (1024**3):.1f} GB")
    logger.info(f"  CPU usage: {psutil.cpu_percent(interval=1):.1f}%")

def check_project_structure():
    """Kiểm tra cấu trúc project"""
    current_dir = Path.cwd()
    logger.info(f"Current directory: {current_dir}")

    expected_files = [
        "whisperlivekit/__init__.py",
        "whisperlivekit/basic_server.py",
        "whisperlivekit/audio_processor.py",
        "whisperlivekit/ffmpeg_manager.py"
    ]

    for file_path in expected_files:
        full_path = current_dir / file_path
        if full_path.exists():
            logger.info(f"✅ {file_path} exists")
        else:
            logger.error(f"❌ {file_path} not found")

async def main():
    """Main debug function"""
    logger.info("🔍 WhisperLiveKit Connection Debug Tool")
    logger.info("=" * 50)

    # 1. Check FFmpeg
    logger.info("\n1. Checking FFmpeg...")
    ffmpeg_ok = check_ffmpeg()

    # 2. Check dependencies
    logger.info("\n2. Checking Python dependencies...")
    deps_ok, missing = check_dependencies()
    if not deps_ok:
        logger.error(f"Missing packages: {missing}")

    # 3. Check project structure
    logger.info("\n3. Checking project structure...")
    check_project_structure()

    # 4. Check system resources
    logger.info("\n4. Checking system resources...")
    try:
        check_system_resources()
    except ImportError:
        logger.warning("psutil not available, skipping system check")

    # 5. Test FFmpeg directly
    if ffmpeg_ok:
        logger.info("\n5. Testing FFmpeg subprocess...")
        await test_local_ffmpeg()

    # 6. Test WebSocket connection (if server is running)
    logger.info("\n6. Testing WebSocket connection...")
    logger.info("Make sure the server is running with: python -m whisperlivekit.basic_server")

    # Check different possible URLs
    urls_to_test = [
        "ws://localhost:8000/asr",
        "ws://127.0.0.1:8000/asr",
        "ws://localhost:8001/asr"
    ]

    for url in urls_to_test:
        logger.info(f"\nTesting {url}...")
        await test_websocket_connection(url)

    logger.info("\n" + "=" * 50)
    logger.info("🏁 Debug complete!")

    # Summary
    logger.info("\n📋 SUMMARY:")
    if ffmpeg_ok:
        logger.info("✅ FFmpeg is working")
    else:
        logger.error("❌ FFmpeg issues detected")

    if deps_ok:
        logger.info("✅ Dependencies are OK")
    else:
        logger.error("❌ Missing dependencies")

if __name__ == "__main__":
    asyncio.run(main())
