import os
import subprocess
import shutil
import platform
import zipfile

def setup_deno():
    """Setup Deno by downloading it to the bin directory"""
    system = platform.system()
    machine = platform.machine().lower()

    print(f"Detected System: {system}, Machine: {machine}")

    # Determine URL based on OS and architecture
    if system == "Linux":
        if "x86_64" in machine or "amd64" in machine:
            url = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip"
        elif "aarch64" in machine or "arm64" in machine:
            url = "https://github.com/denoland/deno/releases/latest/download/deno-aarch64-unknown-linux-gnu.zip"
        else:
            print(f"Unsupported Linux architecture: {machine}")
            return
    elif system == "Windows":
        url = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"
    elif system == "Darwin":  # macOS
        if "arm64" in machine or "aarch64" in machine:
            url = "https://github.com/denoland/deno/releases/latest/download/deno-aarch64-apple-darwin.zip"
        else:
            url = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-apple-darwin.zip"
    else:
        print(f"Unsupported OS: {system}")
        return

    base_dir = os.path.dirname(os.path.abspath(__file__))
    bin_dir = os.path.join(base_dir, "bin")

    if not os.path.exists(bin_dir):
        os.makedirs(bin_dir)

    deno_exe_name = "deno.exe" if system == "Windows" else "deno"
    deno_exe = os.path.join(bin_dir, deno_exe_name)

    # Check if deno already exists and works
    if os.path.exists(deno_exe):
        print(f"Deno found at {deno_exe}")
        try:
            subprocess.run([deno_exe, "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            print("Deno is operational.")
            return
        except Exception as e:
            print(f"Existing Deno check failed: {e}, reinstalling...")

    print(f"Downloading Deno to {bin_dir}...")

    archive_file = os.path.join(bin_dir, "deno.zip")
    try:
        if shutil.which("curl"):
            subprocess.run(["curl", "-L", "-o", archive_file, url], check=True)
        else:
            import urllib.request
            urllib.request.urlretrieve(url, archive_file)
            print("Downloaded using urllib.")
    except Exception as e:
        print(f"Download failed: {e}")
        return

    print("Extracting...")
    try:
        with zipfile.ZipFile(archive_file, 'r') as zip_ref:
            zip_ref.extractall(bin_dir)
    except Exception as e:
        print(f"Extraction failed: {e}")
        return

    # Cleanup archive file
    if os.path.exists(archive_file):
        os.remove(archive_file)

    # Make executable on Unix systems
    if system != "Windows" and os.path.exists(deno_exe):
        os.chmod(deno_exe, 0o755)

    # Verify installation
    if os.path.exists(deno_exe):
        print(f"Deno installed successfully to {deno_exe}")
        try:
            result = subprocess.run([deno_exe, "--version"],
                                  check=True,
                                  stdout=subprocess.PIPE,
                                  text=True)
            print(f"Deno version:\n{result.stdout}")
        except Exception as e:
            print(f"Deno verification failed: {e}")
    else:
        print("Failed to find deno binary after extraction.")

if __name__ == "__main__":
    setup_deno()
