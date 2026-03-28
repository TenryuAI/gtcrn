import os
import sys
import torch
import onnx
from onnxsim import simplify

# 添加 stream 目录到系统路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'stream'))

from gtcrn import GTCRN
from stream.modules.convert import convert_to_stream
from stream.gtcrn_stream import StreamGTCRN

def main():
    device = torch.device("cpu")
    print("Loading PyTorch model...")
    
    model = GTCRN().to(device).eval()
    ckpt = torch.load(os.path.join('checkpoints', 'model_trained_on_dns3.tar'), map_location=device)
    model.load_state_dict(ckpt['model'])
    
    stream_model = StreamGTCRN().to(device).eval()
    convert_to_stream(stream_model, model)
    
    # Fuse BatchNorm to avoid ONNX export bug
    from fuse_bn import fuse_model
    fuse_model(stream_model)
    
    print("Model converted to stream model and fused!")

    # 准备输入张量
    # spec: (B, F, T, 2) = (1, 257, 1, 2)
    spec = torch.randn(1, 257, 1, 2, device=device)
    # conv_cache: [en_cache, de_cache], (2, B, C, 8(kT-1), F) = (2, 1, 16, 16, 33)
    conv_cache = torch.zeros(2, 1, 16, 16, 33, device=device)
    # tra_cache: [en_cache, de_cache], (2, 3, 1, B, C) = (2, 3, 1, 1, 16)
    tra_cache = torch.zeros(2, 3, 1, 1, 16, device=device)
    # inter_cache: [cache1, cache2], (2, 1, BF, C) = (2, 1, 33, 16)
    inter_cache = torch.zeros(2, 1, 33, 16, device=device)

    os.makedirs('onnx_models', exist_ok=True)
    onnx_path = 'onnx_models/gtcrn.onnx'
    onnx_sim_path = 'onnx_models/gtcrn_simple.onnx'

    print(f"Exporting ONNX model to {onnx_path}...")
    torch.onnx.export(
        stream_model,
        (spec, conv_cache, tra_cache, inter_cache),
        onnx_path,
        input_names=['mix', 'conv_cache', 'tra_cache', 'inter_cache'],
        output_names=['enh', 'conv_cache_out', 'tra_cache_out', 'inter_cache_out'],
        opset_version=17,
        dynamo=False,   # Use legacy JIT-based exporter - correctly handles GRU weights
        verbose=False
    )

    print("Checking ONNX model...")
    onnx_model = onnx.load(onnx_path)
    onnx.checker.check_model(onnx_model)

    print(f"Simplifying ONNX model to {onnx_sim_path}...")
    model_simp, check = simplify(onnx_model)
    assert check, "Simplified ONNX model could not be validated"
    onnx.save(model_simp, onnx_sim_path)
    
    print("ONNX model exported and simplified successfully!")

if __name__ == "__main__":
    main()
