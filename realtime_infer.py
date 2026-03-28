import os
import sys
import time
import torch
import numpy as np
import sounddevice as sd
import threading

# 添加 stream 目录到系统路径，解决 modules 导入问题
sys.path.append(os.path.join(os.path.dirname(__file__), 'stream'))

from gtcrn import GTCRN
from stream.modules.convert import convert_to_stream
from stream.gtcrn_stream import StreamGTCRN

# 全局变量控制模式
current_mode = 1
running = True

def main():
    global current_mode, running
    
    # ----------------------------------------
    # 1. 加载模型 (无论哪种模式都先加载，方便后续切换)
    # ----------------------------------------
    device = torch.device("cpu")
    print("正在加载模型...")
    model = GTCRN().to(device).eval()
    ckpt = torch.load(os.path.join('checkpoints', 'model_trained_on_dns3.tar'), map_location=device)
    model.load_state_dict(ckpt['model'])
    
    stream_model = StreamGTCRN().to(device).eval()
    convert_to_stream(stream_model, model)
    print("模型加载完成！")
    
    # ----------------------------------------
    # 2. 初始化流式处理的状态和缓存
    # ----------------------------------------
    fs = 16000
    block_size = 256
    window_size = 512
    
    # 降噪强度 (Dry/Wet Mix)
    # 1.0 = 完全降噪, 0.0 = 完全原声
    denoise_strength = 0.8
    
    window = torch.hann_window(window_size).pow(0.5).to(device)
    
    # 音频输入缓存 (用于重叠相加STFT)
    in_buffer = torch.zeros(window_size, device=device)
    # 音频输出缓存 (用于重叠相加iSTFT)
    out_buffer = torch.zeros(window_size, device=device)
    
    # 模型缓存
    conv_cache = torch.zeros(2, 1, 16, 16, 33, device=device)
    tra_cache = torch.zeros(2, 3, 1, 1, 16, device=device)
    inter_cache = torch.zeros(2, 1, 33, 16, device=device)
    
    # ----------------------------------------
    # 3. 定义音频回调函数
    # ----------------------------------------
    def audio_callback(indata, outdata, frames, time_info, status):
        nonlocal in_buffer, out_buffer
        nonlocal conv_cache, tra_cache, inter_cache
        
        if status:
            pass # 忽略小的下溢/上溢警告
            
        # indata: (256, channels)
        # 转换为单声道并放入输入缓存
        in_chunk = torch.from_numpy(indata[:, 0]).to(device)
        
        # 更新输入缓存 (左移256，右边填入新数据)
        in_buffer = torch.roll(in_buffer, -block_size)
        in_buffer[-block_size:] = in_chunk
        
        if current_mode == 1:
            # 模式1：不降噪，直接输出当前块 (带有256的延迟以对齐)
            out_chunk = in_buffer[:block_size].cpu().numpy()
            outdata[:, 0] = out_chunk
            if outdata.shape[1] > 1:
                for c in range(1, outdata.shape[1]):
                    outdata[:, c] = out_chunk
            return
            
        # 模式2：降噪处理
        # 1. STFT
        stft_out = torch.fft.rfft(in_buffer * window)
        
        # 2. 准备模型输入 (1, 257, 1, 2)
        spec = torch.zeros(1, 257, 1, 2, device=device)
        spec[0, :, 0, 0] = stft_out.real
        spec[0, :, 0, 1] = stft_out.imag
        
        # 3. 模型推理
        with torch.no_grad():
            out_spec, conv_cache, tra_cache, inter_cache = stream_model(
                spec, conv_cache, tra_cache, inter_cache
            )
            
        # 4. iSTFT
        out_real = out_spec[0, :, 0, 0]
        out_imag = out_spec[0, :, 0, 1]
        out_complex = torch.complex(out_real, out_imag)
        
        y_frame = torch.fft.irfft(out_complex, n=window_size) * window
        
        # 5. Overlap-Add
        out_buffer += y_frame
        
        # 6. 混合原声与降噪后的声音 (Dry/Wet Mix)
        out_chunk = out_buffer[:block_size].cpu().numpy()
        dry_chunk = in_buffer[:block_size].cpu().numpy()
        out_chunk = denoise_strength * out_chunk + (1.0 - denoise_strength) * dry_chunk
        
        # 7. 更新输出缓存 (左移256，右边清零)
        out_buffer = torch.roll(out_buffer, -block_size)
        out_buffer[-block_size:] = 0.0
        
        # 写入输出
        outdata[:, 0] = out_chunk
        if outdata.shape[1] > 1:
            for c in range(1, outdata.shape[1]):
                outdata[:, c] = out_chunk

    # ----------------------------------------
    # 4. 输入监听线程 (无需回车)
    # ----------------------------------------
    def input_thread():
        global current_mode, running
        import msvcrt
        
        while running:
            if msvcrt.kbhit():
                # 读取按下的键 (字节形式)
                key = msvcrt.getch()
                
                try:
                    # 尝试解码为普通字符
                    char = key.decode('utf-8').lower()
                    
                    if char == '1':
                        if current_mode != 1:
                            current_mode = 1
                            print("\n--> 已切换到模式 1: 监听原始声音 (不降噪)", flush=True)
                    elif char == '2':
                        if current_mode != 2:
                            current_mode = 2
                            print("\n--> 已切换到模式 2: 监听降噪后的声音", flush=True)
                    elif char == 'q' or key == b'\x03': # \x03 是 Ctrl+C
                        running = False
                        print("\n正在退出...", flush=True)
                        break
                except UnicodeDecodeError:
                    pass
            time.sleep(0.05)

    # ----------------------------------------
    # 5. 启动音频流
    # ----------------------------------------
    try:
        # 尝试获取默认设备的通道数
        default_in = sd.query_devices(sd.default.device[0], 'input')
        default_out = sd.query_devices(sd.default.device[1], 'output')
        in_channels = min(1, default_in['max_input_channels'])
        out_channels = min(2, default_out['max_output_channels'])
        
        if in_channels < 1:
            in_channels = 1
        if out_channels < 1:
            out_channels = 1
            
        print("\n========================================")
        print("GTCRN 实时降噪测试程序")
        print(">>> 请戴上耳机，以免产生啸叫 (回音)！ <<<")
        print("========================================")
        print("操作说明：")
        print("按 1 键: 监听原始声音 (当前默认)")
        print("按 2 键: 监听降噪后的声音")
        print("按 q 键或 Ctrl+C: 退出程序")
        print("========================================\n")
        
        # 启动输入监听线程
        t = threading.Thread(target=input_thread)
        t.daemon = True
        t.start()
        
        with sd.Stream(samplerate=fs, blocksize=block_size,
                       dtype='float32', channels=(in_channels, out_channels),
                       callback=audio_callback):
            # 主循环，检查 running 状态
            while running:
                time.sleep(0.1)
                
    except KeyboardInterrupt:
        running = False
        print("\n已停止。")
    except Exception as e:
        print(f"\n发生错误: {e}")
        print("尝试使用默认单声道重试...")
        try:
            with sd.Stream(samplerate=fs, blocksize=block_size,
                           dtype='float32', channels=1,
                           callback=audio_callback):
                while running:
                    time.sleep(0.1)
        except KeyboardInterrupt:
            running = False
            print("\n已停止。")
        except Exception as e2:
            print(f"\n再次发生错误: {e2}")

if __name__ == "__main__":
    main()
