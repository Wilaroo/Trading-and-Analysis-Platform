"""Quick GPU status check for startup scripts."""
try:
    import torch
    if torch.cuda.is_available():
        name = torch.cuda.get_device_name(0)
        props = torch.cuda.get_device_properties(0)
        gb = props.total_mem // 1073741824
        print(f"        GPU: {name} ({gb}GB)")
    else:
        print("        GPU: CPU mode (no CUDA)")
except Exception as e:
    print(f"        GPU: Not configured ({e})")
