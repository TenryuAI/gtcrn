"""
Validates the C++ processing chain by simulating it in Python using numpy/onnxruntime.
Compares against the pure PyTorch streaming version.
"""
import sys
import numpy as np
import onnxruntime
import torch

sys.path.insert(0, '.')
sys.path.insert(0, 'stream')

from gtcrn import GTCRN
from stream.modules.convert import convert_to_stream
from stream.gtcrn_stream import StreamGTCRN

WINDOW_SIZE = 512
BLOCK_SIZE = 256
NUM_BINS = 257

# === Window: torch.hann_window(N) is periodic=True: w[n] = 0.5*(1-cos(2*pi*n/N)) ===
window_pt = torch.hann_window(WINDOW_SIZE).pow(0.5)
window_np = window_pt.numpy()

# Verify: numpy window (periodic Hann)
window_np_check = np.array([0.5 * (1 - np.cos(2 * np.pi * i / WINDOW_SIZE)) for i in range(WINDOW_SIZE)], dtype=np.float32)
window_np_check = np.sqrt(window_np_check)
print(f"[Window check] Max diff between PyTorch and numpy periodic Hann: {np.max(np.abs(window_np - window_np_check)):.2e}")

# === Test audio ===
fs = 16000
t = np.arange(BLOCK_SIZE * 8) / fs
audio = (np.sin(2 * np.pi * 440 * t) + 0.1 * np.random.randn(len(t))).astype(np.float32)

# === Load models ===
print("\nLoading models...")
device = torch.device('cpu')
model = GTCRNN = GTCRN().eval()
ckpt = torch.load('checkpoints/model_trained_on_dns3.tar', map_location=device)
model.load_state_dict(ckpt['model'])
stream_model = StreamGTCRN().eval()
convert_to_stream(stream_model, model)

session = onnxruntime.InferenceSession('onnx_models/gtcrn_simple.onnx', providers=['CPUExecutionProvider'])
print("Models loaded.")

# Print ONNX model info
print("\nONNX model inputs:")
for inp in session.get_inputs():
    print(f"  {inp.name}: shape={inp.shape}, type={inp.type}")
print("ONNX model outputs:")
for out in session.get_outputs():
    print(f"  {out.name}: shape={out.shape}, type={out.type}")

# === PyTorch streaming (reference) ===
pt_conv = torch.zeros(2, 1, 16, 16, 33)
pt_tra = torch.zeros(2, 3, 1, 1, 16)
pt_inter = torch.zeros(2, 1, 33, 16)
pt_in_buf = torch.zeros(WINDOW_SIZE)
pt_out_buf = torch.zeros(WINDOW_SIZE)
pt_outputs = []
pt_fft_list = []
pt_model_out_list = []

# === C++ simulation (numpy + ONNX) ===
ort_conv = np.zeros([2, 1, 16, 16, 33], dtype=np.float32)
ort_tra = np.zeros([2, 3, 1, 1, 16], dtype=np.float32)
ort_inter = np.zeros([2, 1, 33, 16], dtype=np.float32)
ort_in_buf = np.zeros(WINDOW_SIZE, dtype=np.float32)
ort_out_buf = np.zeros(WINDOW_SIZE, dtype=np.float32)
ort_outputs = []
ort_fft_list = []
ort_model_out_list = []

print("\nProcessing frames...")
for frame_idx in range(len(audio) // BLOCK_SIZE):
    chunk = audio[frame_idx * BLOCK_SIZE: (frame_idx + 1) * BLOCK_SIZE]

    # --- PyTorch streaming ---
    pt_in_buf = torch.roll(pt_in_buf, -BLOCK_SIZE)
    pt_in_buf[-BLOCK_SIZE:] = torch.from_numpy(chunk)

    stft_out = torch.fft.rfft(pt_in_buf * window_pt)
    spec = torch.zeros(1, NUM_BINS, 1, 2)
    spec[0, :, 0, 0] = stft_out.real
    spec[0, :, 0, 1] = stft_out.imag

    with torch.no_grad():
        out_spec, pt_conv, pt_tra, pt_inter = stream_model(spec, pt_conv, pt_tra, pt_inter)

    out_c = torch.complex(out_spec[0, :, 0, 0], out_spec[0, :, 0, 1])
    y = torch.fft.irfft(out_c, n=WINDOW_SIZE) * window_pt
    pt_out_buf += y
    pt_outputs.append(pt_out_buf[:BLOCK_SIZE].numpy().copy())
    pt_fft_list.append(stft_out.numpy().copy())
    pt_model_out_list.append(out_spec[0, :, 0, :].numpy().copy())
    pt_out_buf = torch.roll(pt_out_buf, -BLOCK_SIZE)
    pt_out_buf[-BLOCK_SIZE:] = 0.0

    # --- C++ simulation (numpy + ONNX) ---
    # memmove + memcpy (same as C++)
    ort_in_buf[:WINDOW_SIZE - BLOCK_SIZE] = ort_in_buf[BLOCK_SIZE:]
    ort_in_buf[WINDOW_SIZE - BLOCK_SIZE:] = chunk

    # numpy rfft (same convention as pocketfft r2c FORWARD)
    fft_in = ort_in_buf * window_np
    fft_out_np = np.fft.rfft(fft_in).astype(np.complex64)

    spec_ort = np.zeros([1, NUM_BINS, 1, 2], dtype=np.float32)
    spec_ort[0, :, 0, 0] = fft_out_np.real
    spec_ort[0, :, 0, 1] = fft_out_np.imag

    ort_results = session.run(None, {
        'mix': spec_ort,
        'conv_cache': ort_conv,
        'tra_cache': ort_tra,
        'inter_cache': ort_inter
    })

    out_spec_ort = ort_results[0]   # shape should be (1, 257, 1, 2)
    ort_conv = ort_results[1]
    ort_tra = ort_results[2]
    ort_inter = ort_results[3]

    # numpy irfft (same as pocketfft c2r BACKWARD with scale=1/N)
    ifft_in_np = out_spec_ort[0, :, 0, 0] + 1j * out_spec_ort[0, :, 0, 1]
    ifft_out_np = np.fft.irfft(ifft_in_np.astype(np.complex64), n=WINDOW_SIZE).astype(np.float32)

    ort_out_buf += ifft_out_np * window_np
    ort_outputs.append(ort_out_buf[:BLOCK_SIZE].copy())
    ort_fft_list.append(fft_out_np.copy())
    ort_model_out_list.append(out_spec_ort[0, :, 0, :].copy())

    # memmove + memset (same as C++)
    ort_out_buf[:WINDOW_SIZE - BLOCK_SIZE] = ort_out_buf[BLOCK_SIZE:]
    ort_out_buf[WINDOW_SIZE - BLOCK_SIZE:] = 0.0

# === Comparison ===
print("\n=== Step-by-step comparison ===")

frame = 2  # Check frame 2 (after warmup)
pt_fft = pt_fft_list[frame]
ort_fft = ort_fft_list[frame]
print(f"\n[STFT comparison at frame {frame}]")
print(f"  PyTorch real  bins 0-4: {pt_fft[:5].real}")
print(f"  numpy   real  bins 0-4: {ort_fft[:5].real}")
print(f"  Max abs diff: {np.max(np.abs(pt_fft - ort_fft)):.2e}")

pt_mo = pt_model_out_list[frame]
ort_mo = ort_model_out_list[frame]
print(f"\n[Model output comparison at frame {frame}]")
print(f"  PyTorch out real bins 0-4: {pt_mo[:5, 0]}")
print(f"  ONNX    out real bins 0-4: {ort_mo[:5, 0]}")
print(f"  Max abs diff: {np.max(np.abs(pt_mo - ort_mo)):.2e}")

pt_all = np.concatenate(pt_outputs)
ort_all = np.concatenate(ort_outputs)
print(f"\n[Audio output comparison]")
print(f"  Max abs diff: {np.max(np.abs(pt_all - ort_all)):.2e}")
print(f"  Mean abs diff: {np.mean(np.abs(pt_all - ort_all)):.2e}")
print(f"  PyTorch RMS: {np.sqrt(np.mean(pt_all**2)):.4f}")
print(f"  ONNX    RMS: {np.sqrt(np.mean(ort_all**2)):.4f}")

if np.max(np.abs(pt_all - ort_all)) < 0.01:
    print("\n[RESULT] C++ simulation matches PyTorch reference. DSP/ONNX chain is CORRECT.")
    print("  -> Issue might be in PortAudio input/output handling.")
else:
    print("\n[RESULT] C++ simulation DIFFERS from PyTorch reference!")
    # Find which step diverges
    fft_diff = np.max(np.abs(np.array(pt_fft_list) - np.array(ort_fft_list)))
    model_diff = np.max(np.abs(np.array(pt_model_out_list) - np.array(ort_model_out_list)))
    print(f"  Max STFT diff:         {fft_diff:.2e}")
    print(f"  Max model output diff: {model_diff:.2e}")
    if fft_diff > 1e-4:
        print("  -> BUG: STFT computation is different!")
    elif model_diff > 1e-4:
        print("  -> BUG: ONNX model output differs from PyTorch model!")
    else:
        print("  -> BUG: iSTFT/OLA is different!")
