"""
RK3568 one-click deploy script for GTCRN realtime denoiser.
Usage: python deploy_rk3568.py
"""
import paramiko
import os
import sys
import time

HOST = "192.168.0.100"
USER = "rock"
PASS = "rock"
REMOTE_DIR = "/home/rock/gtcrn"
ORT_VERSION = "1.17.1"

def run(ssh, cmd, sudo=False, timeout=60):
    if sudo:
        cmd = f"echo {PASS} | sudo -S sh -c '{cmd}'"
    print(f"$ {cmd[:80]}...")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out:
        print(out)
    if err and "sudo" not in err and "password" not in err.lower():
        print("[STDERR]", err[:300])
    return out

def upload(sftp, local, remote, text_mode=False):
    print(f"Uploading {os.path.basename(local)} -> {remote}")
    if text_mode:
        # Convert Windows CRLF to Unix LF before uploading
        with open(local, 'rb') as f:
            content = f.read().replace(b'\r\n', b'\n')
        with sftp.open(remote, 'wb') as f:
            f.write(content)
    else:
        sftp.put(local, remote)

def main():
    print("=" * 50)
    print("GTCRN RK3568 Deployment Script")
    print("=" * 50)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"\nConnecting to {HOST}...")
    ssh.connect(HOST, username=USER, password=PASS, timeout=15)
    print("Connected!")

    sftp = ssh.open_sftp()

    # Step 1: Create remote directory structure
    print("\n[1/6] Creating remote directories...")
    run(ssh, f"mkdir -p {REMOTE_DIR}/cpp_src")

    # Step 2: Upload source files
    print("\n[2/6] Uploading source files...")
    base = os.path.dirname(os.path.abspath(__file__))
    files_to_upload = [
        ("cpp_src/AudioProcessor.cpp", f"{REMOTE_DIR}/cpp_src/AudioProcessor.cpp"),
        ("cpp_src/AudioProcessor.h",   f"{REMOTE_DIR}/cpp_src/AudioProcessor.h"),
        ("cpp_src/main_linux.cpp",     f"{REMOTE_DIR}/cpp_src/main_linux.cpp"),
        ("cpp_src/CMakeLists_linux.txt", f"{REMOTE_DIR}/cpp_src/CMakeLists.txt"),
    ]
    for local_rel, remote in files_to_upload:
        local_abs = os.path.join(base, local_rel)
        if os.path.exists(local_abs):
            upload(sftp, local_abs, remote)
        else:
            print(f"  WARNING: {local_abs} not found, skipping")

    # Upload ONNX model
    model_path = os.path.join(base, "onnx_models", "gtcrn_simple.onnx")
    if os.path.exists(model_path):
        print(f"Uploading ONNX model ({os.path.getsize(model_path)//1024}KB)...")
        upload(sftp, model_path, f"{REMOTE_DIR}/gtcrn_simple.onnx")
    else:
        print("ERROR: onnx_models/gtcrn_simple.onnx not found!")
        print("Run: python export_onnx.py  first")
        sftp.close()
        ssh.close()
        return

    sftp.close()

    # Step 3: Download ONNX Runtime for ARM64
    print("\n[3/6] Checking ONNX Runtime for ARM64...")
    ort_dir = f"/home/rock/onnxruntime-linux-aarch64-{ORT_VERSION}"
    result = run(ssh, f"test -d {ort_dir} && echo EXISTS || echo MISSING")
    if "MISSING" in result:
        print(f"  Downloading ONNX Runtime {ORT_VERSION} for ARM64...")
        ort_url = f"https://github.com/microsoft/onnxruntime/releases/download/v{ORT_VERSION}/onnxruntime-linux-aarch64-{ORT_VERSION}.tgz"
        run(ssh, f"cd /home/rock && wget -q --show-progress '{ort_url}' -O ort.tgz", timeout=300)
        run(ssh, f"cd /home/rock && tar xzf ort.tgz && rm ort.tgz")
        print("  ONNX Runtime downloaded and extracted.")
    else:
        print(f"  Already exists at {ort_dir}")

    # Step 4: Build
    print("\n[4/6] Building...")
    build_dir = f"{REMOTE_DIR}/build"
    run(ssh, f"mkdir -p {build_dir}")
    run(ssh, f"cd {build_dir} && cmake ../cpp_src -DCMAKE_BUILD_TYPE=Release", timeout=60)
    result = run(ssh, f"cd {build_dir} && make -j4 2>&1", timeout=120)
    if "Error" in result or "error" in result.lower() and "no error" not in result.lower():
        print("\nBuild may have failed. Check output above.")
    else:
        print("  Build successful!")

    # Step 5: Copy model to build dir for convenience
    print("\n[5/6] Setting up runtime files...")
    run(ssh, f"cp {REMOTE_DIR}/gtcrn_simple.onnx {build_dir}/")
    run(ssh, f"ls -lh {build_dir}/gtcrn_realtime {build_dir}/gtcrn_simple.onnx 2>/dev/null || ls {build_dir}/")

    # Step 6: Quick test (just check it loads)
    print("\n[6/6] Quick load test...")
    result = run(ssh, f"cd {build_dir} && LD_LIBRARY_PATH=/home/rock/onnxruntime-linux-aarch64-{ORT_VERSION}/lib timeout 3 ./gtcrn_realtime 2>&1 || true")
    if "Model loaded!" in result or "WEAR HEADPHONES" in result:
        print("  Model loads successfully!")
    else:
        print("  Test output:", result[:200])

    print("\n" + "=" * 50)
    print("Deployment complete!")
    print(f"\nTo run on RK3568:")
    print(f"  ssh rock@{HOST}")
    print(f"  cd {build_dir}")
    print(f"  LD_LIBRARY_PATH=/home/rock/onnxruntime-linux-aarch64-{ORT_VERSION}/lib ./gtcrn_realtime")
    print(f"\nOr use the run script:")
    print(f"  ~/gtcrn/run.sh")

    # Create a convenient run script on the device
    run_script = f"""#!/bin/bash
cd {build_dir}
export LD_LIBRARY_PATH=/home/rock/onnxruntime-linux-aarch64-{ORT_VERSION}/lib:$LD_LIBRARY_PATH
./gtcrn_realtime "$@"
"""
    sftp = ssh.open_sftp()
    with sftp.open(f"{REMOTE_DIR}/run.sh", 'wb') as f:
        f.write(run_script.encode('utf-8').replace(b'\r\n', b'\n'))
    sftp.close()
    run(ssh, f"chmod +x {REMOTE_DIR}/run.sh")
    print(f"\nRun script created: ~/gtcrn/run.sh")

    ssh.close()

if __name__ == "__main__":
    main()
