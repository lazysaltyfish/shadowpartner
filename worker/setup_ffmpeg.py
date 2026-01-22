"""FFmpeg setup for the Whisper GPU worker."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

from logger import get_logger

logger = get_logger(__name__)


def ensure_ffmpeg() -> None:
    """Ensure ffmpeg and ffprobe are available, install locally if missing."""
    _setup_local_bin_path()

    if _ffmpeg_ready():
        logger.info("FFmpeg is available.")
        return

    logger.warning("FFmpeg not found in PATH; attempting local install.")
    bin_dir = _bin_dir()
    if not _install_ffmpeg(bin_dir):
        raise RuntimeError(
            "FFmpeg setup failed. Install ffmpeg manually and ensure it is on PATH."
        )

    _setup_local_bin_path()
    if not _ffmpeg_ready():
        raise RuntimeError("FFmpeg install completed but binaries are not usable.")


def _bin_dir() -> Path:
    return Path(__file__).resolve().parent / "bin"


def _setup_local_bin_path() -> None:
    bin_dir = _bin_dir()
    if not bin_dir.exists():
        return

    path = os.environ.get("PATH", "")
    path_parts = path.split(os.pathsep) if path else []
    if str(bin_dir) not in path_parts:
        os.environ["PATH"] = str(bin_dir) + (os.pathsep + path if path else "")
        logger.info(f"Added local bin to PATH: {bin_dir}")


def _ffmpeg_ready() -> bool:
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    if not ffmpeg_path or not ffprobe_path:
        return False
    return _binary_operational(ffmpeg_path) and _binary_operational(ffprobe_path)


def _binary_operational(path: str) -> bool:
    try:
        subprocess.run(
            [path, "-version"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return True
    except Exception as e:
        logger.warning(f"Binary check failed for {path}: {e}")
        return False


def _install_ffmpeg(bin_dir: Path) -> bool:
    system = platform.system()
    machine = platform.machine().lower()
    logger.info(f"Detected system: {system}, machine: {machine}")

    if system == "Linux":
        url = (
            "https://johnvansickle.com/ffmpeg/releases/"
            "ffmpeg-release-amd64-static.tar.xz"
        )
        archive_name = "ffmpeg.tar.xz"
    elif system == "Windows":
        url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        archive_name = "ffmpeg.zip"
    elif system == "Darwin":
        logger.error(
            "MacOS automatic setup is not implemented. Install ffmpeg manually "
            "(e.g. brew install ffmpeg)."
        )
        return False
    else:
        logger.error(f"Unsupported OS: {system}")
        return False

    bin_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg_exe_name = "ffmpeg.exe" if system == "Windows" else "ffmpeg"
    ffprobe_exe_name = "ffprobe.exe" if system == "Windows" else "ffprobe"
    ffmpeg_exe = bin_dir / ffmpeg_exe_name
    ffprobe_exe = bin_dir / ffprobe_exe_name

    if ffmpeg_exe.exists() and ffprobe_exe.exists():
        if _binary_operational(str(ffmpeg_exe)) and _binary_operational(
            str(ffprobe_exe)
        ):
            logger.info(f"FFmpeg found at {ffmpeg_exe}")
            return True

    archive_file = bin_dir / archive_name
    logger.info(f"Downloading FFmpeg to {bin_dir}...")

    try:
        if shutil.which("curl"):
            subprocess.run(
                ["curl", "-L", "-o", str(archive_file), url],
                check=True,
            )
        else:
            import urllib.request

            urllib.request.urlretrieve(url, archive_file)
            logger.info("Downloaded using urllib.")
    except Exception as e:
        logger.error(f"Download failed: {e}")
        return False

    logger.info("Extracting FFmpeg archive...")
    try:
        if archive_name.endswith(".zip"):
            with zipfile.ZipFile(archive_file, "r") as zip_ref:
                zip_ref.extractall(bin_dir)
        else:
            with tarfile.open(archive_file, "r:xz") as tar_ref:
                tar_ref.extractall(bin_dir)
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        if system != "Windows":
            try:
                subprocess.run(
                    ["tar", "xf", str(archive_file), "-C", str(bin_dir)],
                    check=True,
                )
                logger.info("Extracted using system tar.")
            except Exception as e2:
                logger.error(f"System tar extraction also failed: {e2}")
                return False
        else:
            return False

    found_ffmpeg = False
    found_ffprobe = False
    for root, _dirs, files in os.walk(bin_dir):
        if ffmpeg_exe_name in files:
            src_ffmpeg = Path(root) / ffmpeg_exe_name
            if src_ffmpeg != ffmpeg_exe:
                if ffmpeg_exe.exists():
                    ffmpeg_exe.unlink()
                shutil.move(str(src_ffmpeg), str(ffmpeg_exe))
            found_ffmpeg = True

        if ffprobe_exe_name in files:
            src_ffprobe = Path(root) / ffprobe_exe_name
            if src_ffprobe != ffprobe_exe:
                if ffprobe_exe.exists():
                    ffprobe_exe.unlink()
                shutil.move(str(src_ffprobe), str(ffprobe_exe))
            found_ffprobe = True

    for item in bin_dir.iterdir():
        if item.is_dir():
            shutil.rmtree(item)

    if archive_file.exists():
        archive_file.unlink()

    if found_ffmpeg and found_ffprobe:
        logger.info(f"FFmpeg installed successfully to {ffmpeg_exe}")
        if system != "Windows":
            os.chmod(ffmpeg_exe, 0o755)
            os.chmod(ffprobe_exe, 0o755)
        return True

    logger.error("Failed to find ffmpeg/ffprobe binaries in extracted files.")
    return False


if __name__ == "__main__":
    ensure_ffmpeg()
