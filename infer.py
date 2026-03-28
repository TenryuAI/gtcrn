import os
import torch
import numpy as np
import soundfile as sf
from gtcrn import GTCRN


## load model
device = torch.device("cpu")
model = GTCRN().eval()
ckpt = torch.load(os.path.join('checkpoints', 'model_trained_on_dns3.tar'), map_location=device)
model.load_state_dict(ckpt['model'])

## load data
mix_orig, fs = sf.read(os.path.join('test_wavs', 'test.wav'), dtype='float32')
assert fs == 16000

## inference
if mix_orig.ndim == 1:
    mix = mix_orig[None, :]
else:
    mix = mix_orig.T

input_complex = torch.stft(torch.from_numpy(mix), 512, 256, 512, torch.hann_window(512).pow(0.5), return_complex=True)
input = torch.view_as_real(input_complex)

with torch.no_grad():
    output = model(input)

output_complex = torch.view_as_complex(output.contiguous())
enh = torch.istft(output_complex, 512, 256, 512, torch.hann_window(512).pow(0.5), length=mix.shape[-1], return_complex=False)

if enh.shape[0] == 1:
    enh = enh[0]
else:
    enh = enh.T

## save enhanced wav
enh_np = enh.detach().cpu().numpy()

# ==========================================
# 参数调整区
# ==========================================
# 1. 降噪强度 (Dry/Wet Mix)
# 范围: 0.0 到 1.0
# 1.0 = 完全降噪 (默认), 0.0 = 完全原声
denoise_strength = 0.8 
final_out = denoise_strength * enh_np + (1.0 - denoise_strength) * mix_orig

# 2. 音量峰值归一化 (防止爆音)
# True = 开启, False = 关闭
normalize_audio = True
if normalize_audio:
    max_val = np.max(np.abs(final_out))
    if max_val > 0:
        final_out = final_out / max_val * 0.95 # 留出一点动态余量

sf.write(os.path.join('test_wavs', 'test_enh.wav'), final_out, fs)

