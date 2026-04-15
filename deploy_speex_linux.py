import paramiko
from pathlib import Path

HOST = "192.168.0.100"
USER = "rock"
PASSWORD = "rock"

ROOT = Path(r"D:\github\gtcrn")


def upload_text(sftp, local_path: Path, remote_path: str):
    data = local_path.read_bytes().replace(b"\r\n", b"\n")
    with sftp.open(remote_path, "wb") as f:
        f.write(data)


def run(ssh, cmd: str, timeout: int = 120):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    return out, err


ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASSWORD, timeout=15)
sftp = ssh.open_sftp()

for local, remote in [
    (ROOT / "cpp_src" / "AudioProcessor.h", "/home/rock/gtcrn/cpp_src/AudioProcessor.h"),
    (ROOT / "cpp_src" / "AudioProcessor.cpp", "/home/rock/gtcrn/cpp_src/AudioProcessor.cpp"),
    (ROOT / "cpp_src" / "main_linux.cpp", "/home/rock/gtcrn/cpp_src/main_linux.cpp"),
    (ROOT / "cpp_src" / "CMakeLists_linux.txt", "/home/rock/gtcrn/cpp_src/CMakeLists.txt"),
    (ROOT / "run_rk3568.sh", "/home/rock/gtcrn/run.sh"),
]:
    upload_text(sftp, local, remote)

sftp.close()

cmd = (
    "echo rock | sudo -S apt-get update && "
    "echo rock | sudo -S apt-get install -y libspeexdsp-dev && "
    "chmod +x /home/rock/gtcrn/run.sh && "
    "cd /home/rock/gtcrn/build && "
    "cmake ../cpp_src -DCMAKE_BUILD_TYPE=Release && "
    "make -j4"
)
out, err = run(ssh, cmd, timeout=600)
print(out[-6000:])
if err.strip():
    print(err[-2000:])

ssh.close()
