#!/usr/bin/env python3
"""
Simple debug script để kiểm tra FFmpeg và system requirements
"""

import subprocess
import sys
import logging
import os
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def check_ffmpeg():
    """Kiểm tra xem FFmpeg có được cài đặt không"""
    logger.info("🔍 Checking FFmpeg...")
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
        logger.error("Install FFmpeg with:")
        logger.error("  Ubuntu/Debian: sudo apt update && sudo apt install ffmpeg")
        logger.error("  macOS: brew install ffmpeg")
        return False
    except subprocess.TimeoutExpired:
        logger.error("❌ FFmpeg command timeout")
        return False
    except Exception as e:
        logger.error(f"❌ Error checking FFmpeg: {e}")
        return False

def check_python_packages():
    """Kiểm tra các Python packages cần thiết"""
    logger.info("🔍 Checking Python packages...")

    required_packages = [
        'fastapi',
        'torch',
        'transformers',
        'numpy',
        'scipy',
        'asyncio',
        'uvicorn'
    ]

    missing_packages = []
    for package in required_packages:
        try:
            __import__(package)
            logger.info(f"✅ {package} found")
        except ImportError:
            missing_packages.append(package)
            logger.error(f"❌ {package} not found")

    if missing_packages:
        logger.error(f"Missing packages: {missing_packages}")
        logger.error("Install missing packages with: pip install " + " ".join(missing_packages))
        return False
    return True

def check_whisperlivekit_import():
    """Kiểm tra xem có import được whisperlivekit không"""
    logger.info("🔍 Checking WhisperLiveKit import...")
    try:
        sys.path.insert(0, str(Path.cwd()))
        from whisperlivekit import AudioProcessor, TranscriptionEngine
        logger.info("✅ WhisperLiveKit imports successful")
        return True
    except ImportError as e:
        logger.error(f"❌ Cannot import WhisperLiveKit: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Error importing WhisperLiveKit: {e}")
        return False

def check_project_structure():
    """Kiểm tra cấu trúc project"""
    logger.info("🔍 Checking project structure...")
    current_dir = Path.cwd()
    logger.info(f"Current directory: {current_dir}")

    expected_files = [
        "whisperlivekit/__init__.py",
        "whisperlivekit/basic_server.py",
        "whisperlivekit/audio_processor.py",
        "whisperlivekit/ffmpeg_manager.py"
    ]

    all_exist = True
    for file_path in expected_files:
        full_path = current_dir / file_path
        if full_path.exists():
            logger.info(f"✅ {file_path} exists")
        else:
            logger.error(f"❌ {file_path} not found")
            all_exist = False

    return all_exist

def test_ffmpeg_basic():
    """Test FFmpeg với command đơn giản"""
    logger.info("🔍 Testing FFmpeg basic functionality...")
    try:
        # Test FFmpeg help command
        result = subprocess.run(['ffmpeg', '-h'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            logger.info("✅ FFmpeg help command works")
            return True
        else:
            logger.error(f"❌ FFmpeg help failed: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"❌ FFmpeg basic test failed: {e}")
        return False

def check_system_info():
    """Hiển thị thông tin system"""
    logger.info("🔍 System Information:")
    logger.info(f"  Python version: {sys.version}")
    logger.info(f"  Platform: {sys.platform}")
    logger.info(f"  Current working directory: {os.getcwd()}")

    # Check memory if possible
    try:
        import psutil
        logger.info(f"  CPU count: {psutil.cpu_count()}")
        logger.info(f"  Memory: {psutil.virtual_memory().total / (1024**3):.1f} GB")
        logger.info(f"  Available memory: {psutil.virtual_memory().available / (1024**3):.1f} GB")
    except ImportError:
        logger.info("  (psutil not available for detailed system info)")

def check_common_issues():
    """Kiểm tra các vấn đề thường gặp"""
    logger.info("🔍 Checking common issues...")

    issues_found = []

    # Check if running as root (could cause permission issues)
    if os.geteuid() == 0:
        issues_found.append("Running as root - this might cause permission issues")

    # Check if port 8000 is in use
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('localhost', 8000))
        if result == 0:
            logger.info("✅ Port 8000 is accessible (server might be running)")
        else:
            logger.info("ℹ️ Port 8000 is not in use (server not running)")
        sock.close()
    except Exception as e:
        logger.warning(f"Cannot check port 8000: {e}")

    if issues_found:
        for issue in issues_found:
            logger.warning(f"⚠️ {issue}")
    else:
        logger.info("✅ No common issues detected")

def main():
    """Main debug function"""
    logger.info("🔍 WhisperLiveKit Simple Debug Tool")
    logger.info("=" * 50)

    all_checks_passed = True

    # 1. System info
    logger.info("\n1. System Information:")
    check_system_info()

    # 2. Check project structure
    logger.info("\n2. Checking project structure...")
    if not check_project_structure():
        all_checks_passed = False

    # 3. Check FFmpeg
    logger.info("\n3. Checking FFmpeg...")
    if not check_ffmpeg():
        all_checks_passed = False
    else:
        # Test FFmpeg basic functionality
        if not test_ffmpeg_basic():
            all_checks_passed = False

    # 4. Check Python packages
    logger.info("\n4. Checking Python packages...")
    if not check_python_packages():
        all_checks_passed = False

    # 5. Check WhisperLiveKit import
    logger.info("\n5. Checking WhisperLiveKit import...")
    if not check_whisperlivekit_import():
        all_checks_passed = False

    # 6. Check common issues
    logger.info("\n6. Checking common issues...")
    check_common_issues()

    # Summary
    logger.info("\n" + "=" * 50)
    logger.info("🏁 Debug Summary:")

    if all_checks_passed:
        logger.info("✅ All checks passed! Your setup looks good.")
        logger.info("If you're still having connection issues, try:")
        logger.info("  1. Start the server: python3 -m whisperlivekit.basic_server")
        logger.info("  2. Check server logs for specific error messages")
        logger.info("  3. Try connecting with a simple WebSocket client")
    else:
        logger.error("❌ Some checks failed. Please fix the issues above.")
        logger.error("Common fixes:")
        logger.error("  - Install FFmpeg: sudo apt install ffmpeg (Ubuntu) or brew install ffmpeg (macOS)")
        logger.error("  - Install missing Python packages: pip install [package_name]")
        logger.error("  - Make sure you're in the correct directory with WhisperLiveKit code")

if __name__ == "__main__":
    main()
