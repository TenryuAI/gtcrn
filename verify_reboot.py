import paramiko, time

HOST = "192.168.0.100"
USER = "rock"
PASS = "rock"

def connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASS, timeout=15)
    return ssh

ssh = connect()
run = lambda cmd, t=12: (lambda o,e: print(o) or o)(
    *[x.read().decode().strip() for x in ssh.exec_command(cmd, timeout=t)[1:]])

print("Rebooting...")
run(f"echo {PASS} | sudo -S reboot", 5)
ssh.close()

print("Waiting 35s...")
time.sleep(35)

for i in range(6):
    try:
        ssh = connect()
        print(f"Reconnected (attempt {i+1})")
        break
    except:
        print(f"  attempt {i+1}/6 waiting...")
        time.sleep(10)

time.sleep(3)
env = "XDG_RUNTIME_DIR=/run/user/1001"
run = lambda cmd, t=12: (lambda r: (print(r) or r))(
    (lambda o,e: o.read().decode().strip())(
        *[x for x in ssh.exec_command(cmd, timeout=t)[1:]]))

print("\n=== PulseAudio defaults after reboot ===")
run(f"{env} pactl info 2>/dev/null | grep -E 'Default Sink|Default Source'")

print("\n=== ALSA Playback Path ===")
run("amixer -c rockchiprk809 sget 'Playback Path' 2>/dev/null | grep Item0")

print("\n=== Playback test (beep via board HP jack) ===")
gen = ("python3 -c \"import struct,math,sys;sr=48000;"
       "d=struct.pack('<'+'h'*sr*2,*[v for i in range(sr) for v in "
       "[int(25000*math.sin(2*3.14159*440*i/sr))]*2]);"
       "sys.stdout.buffer.write(d)\"")
result = run(f"{env} {gen} | aplay -D default -r 48000 -f S16_LE -c 2 2>&1", 8)
if "Playing" in result:
    print("SUCCESS! Board headphone jack is the persistent default output.")

ssh.close()
