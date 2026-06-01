"""Setup script for C/C++ Code Checker - downloads cppcheck and clang-tidy."""

import os
import sys
import zipfile
import urllib.request
import shutil
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(SCRIPT_DIR, "download")

CPPCHECK_VERSION = "2.20.0"
CPPCHECK_URL = f"https://github.com/danmar/cppcheck/releases/download/{CPPCHECK_VERSION}/cppcheck-{CPPCHECK_VERSION}-x64-Setup.msi"

LLVM_VERSION = "19.1.0"
LLVM_URL = f"https://github.com/llvm/llvm-project/releases/download/llvmorg-{LLVM_VERSION}/LLVM-{LLVM_VERSION}-win64.exe"

def download_file(url, dest_path):
    """Download a file with progress display."""
    print(f"Downloading {url} ...")
    try:
        urllib.request.urlretrieve(url, dest_path)
    except Exception as e:
        print(f"Download failed: {e}")
        print("Trying alternative...")
        raise

def find_7zip():
    """Find 7-Zip executable."""
    paths = [
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None

def extract_exe(exe_path, dest_dir, extract_cmd=None):
    """Extract from an installer EXE using 7-Zip."""
    seven_zip = find_7zip()
    if seven_zip:
        print(f"  Extracting with 7-Zip: {seven_zip}")
        os.makedirs(dest_dir, exist_ok=True)
        result = subprocess.run(
            [seven_zip, "x", f"-o{dest_dir}", "-y", exe_path],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return True
        print(f"  7-Zip extraction failed: {result.stderr}")
    return False

def find_tool(name, search_dir):
    """Find a tool executable in search_dir recursively."""
    for root, dirs, files in os.walk(search_dir):
        for f in files:
            if f.lower() == name.lower():
                return os.path.join(root, f)
    return None

def setup_cppcheck():
    """Download and set up cppcheck."""
    name = "cppcheck"
    exe_target = os.path.join(DOWNLOAD_DIR, name, f"{name}.exe")
    
    # Check if already exists in download dir
    if os.path.exists(exe_target):
        print(f"{name} already installed at {exe_target}")
        return exe_target
    
    # Check if already on PATH or common locations
    if shutil.which(name):
        print(f"{name} found on PATH: {shutil.which(name)}")
        return shutil.which(name)
    for d in [os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), name)]:
        candidate = os.path.join(d, f"{name}.exe")
        if os.path.exists(candidate):
            print(f"{name} found at {candidate}")
            return candidate
    
    # Try winget first
    print(f"Attempting winget install {name}...")
    result = subprocess.run(
        ["winget", "install", "Cppcheck.Cppcheck", "--accept-package-agreements", "--accept-source-agreements"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        for d in [os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), name)]:
            candidate = os.path.join(d, f"{name}.exe")
            if os.path.exists(candidate):
                print(f"  {name} installed to {candidate}")
                return candidate
        if shutil.which(name):
            print(f"  {name} installed to {shutil.which(name)}")
            return shutil.which(name)
    
    # Fallback: download from GitHub
    print(f"winget failed or not available, trying direct download...")
    exe_path = os.path.join(DOWNLOAD_DIR, f"{name}-setup.msi")
    try:
        download_file(CPPCHECK_URL, exe_path)
    except Exception:
        print(f"Failed to download {name}. Please install manually:")
        print(f"  winget install Cppcheck.Cppcheck")
        print(f"  or download from: {CPPCHECK_URL}")
        return None
    
    # Run MSI installer silently
    print("  Running MSI installer...")
    result = subprocess.run(["msiexec", "/i", exe_path, "/quiet", "/norestart"],
                           capture_output=True, text=True)
    if result.returncode == 0:
        # After MSI install, cppcheck should be in Program Files
        for d in [os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), name)]:
            candidate = os.path.join(d, f"{name}.exe")
            if os.path.exists(candidate):
                print(f"  {name} installed to {candidate}")
                return candidate
    
    print(f"  Could not automatically install {name}")
    return None

def setup_clang_tidy():
    """Download and set up clang-tidy (part of LLVM)."""
    name = "clang-tidy"
    exe_target = os.path.join(DOWNLOAD_DIR, "llvm", "bin", f"{name}.exe")
    
    # Check if already exists
    if os.path.exists(exe_target):
        print(f"{name} already installed at {exe_target}")
        return exe_target
    
    # Check if already on PATH
    if shutil.which(name):
        print(f"{name} found on PATH: {shutil.which(name)}")
        return shutil.which(name)
    
    # Also check common locations
    for base in [r"C:\Program Files\LLVM\bin", r"C:\Program Files (x86)\LLVM\bin"]:
        candidate = os.path.join(base, f"{name}.exe")
        if os.path.exists(candidate):
            print(f"{name} found at {candidate}")
            return candidate
    
    print(f"\n{name} not found. You have options:")
    print(f"  1. Install LLVM from: https://github.com/llvm/llvm-project/releases")
    print(f"  2. Or: choco install llvm")
    print(f"  3. Or: winget install LLVM.LLVM")
    print(f"\nWill attempt download from GitHub...")
    
    exe_path = os.path.join(DOWNLOAD_DIR, "LLVM-installer.exe")
    try:
        download_file(LLVM_URL, exe_path)
    except Exception:
        print(f"Automatic download failed.")
        return None
    
    extract_dir = os.path.join(DOWNLOAD_DIR, "llvm-extract")
    if extract_exe(exe_path, extract_dir):
        found = find_tool(f"{name}.exe", extract_dir)
        if found:
            dest_dir = os.path.join(DOWNLOAD_DIR, "llvm", "bin")
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, f"{name}.exe")
            shutil.copy2(found, dest)
            print(f"  {name} installed to {dest}")
            return dest
    
    return None

def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    
    print("=" * 60)
    print("C/C++ Code Checker - Setup")
    print("=" * 60)
    print()
    
    cppcheck_path = setup_cppcheck()
    clang_tidy_path = setup_clang_tidy()
    
    print()
    print("-" * 60)
    print("Setup Summary:")
    print(f"  cppcheck:   {'OK' if cppcheck_path else 'NOT FOUND'}")
    print(f"  clang-tidy: {'OK' if clang_tidy_path else 'NOT FOUND'}")
    print("-" * 60)
    
    if not cppcheck_path and not clang_tidy_path:
        print("\nWarning: No tools installed. At least one is needed.")
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())