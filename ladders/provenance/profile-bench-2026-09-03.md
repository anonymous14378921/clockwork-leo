# Latency profile benchmark on the measurement cluster cluster, 2026-09-03

Batch-1 per-request latency of the three chain components on real devices,
to replace the estimated rows of `data/profiles/workflow_mvp.csv`. Raw JSON
and logs: `bench/results/2026-09-03/`. Tooling: `bench/profile_bench.py`
(PyTorch), `bench/ollama_bench.py` (Ollama, llama.cpp server), pods in
`bench/pods*.yaml`, launched with `just bench` / `just bench-ollama` on measurement cluster.

## Devices

| pod | node | device | runtime |
|---|---|---|---|
| bench-pi5 | pi50 | Raspberry Pi 5, 4x Cortex-A76, 8 GB | torch 2.14 cpu, 4 threads |
| bench-orin (cpu) | jetson-50 | Orin Nano Super ARM cores, 6x Cortex-A78AE | torch 2.10, 6 threads |
| bench-4090 (cpu) | ai2 | AMD Ryzen 9 7950X | torch 2.11, 8 threads |
| bench-orin | jetson-50 | NVIDIA Jetson Orin Nano Super, JetPack 6, CUDA 12.6 | torch 2.10, FP16 |
| bench-4090 | ai2 | NVIDIA GeForce RTX 4090 24 GB, driver 535 | torch 2.11 cu128, FP16 |
| ollama-orin | jetson-50 | same Orin, GPU (cuda_jetpacmeasurement cluster runner) | Ollama 0.33.3, fp16 GGUF |
| ollama-4090 | ai2 | same 4090, GPU (CUDA 11 runner) | Ollama 0.5.13, fp16 GGUF |

Protocol: 5 warmup + 30 timed runs (LLM: 3 + 10), median of wall time per
request with cuda synchronized. Detector: YOLOv8m, imgsz 640, Ultralytics
predict, random image; wall = preprocess + inference + postprocess, and the
Ultralytics inference-only figure is kept (the 2026-08-25 row used it).
Classifier: torchvision ResNet-50, 224x224. LLM: Qwen2.5-0.5B-Instruct and
1.5B-Instruct, fixed 85-token chat prompt, greedy, 32 new tokens.

## Results (median ms per request)

| component | Pi 5 cpu | Orin ARM cpu | Ryzen cpu (8 thr) | Orin Nano GPU | RTX 4090 |
|---|---|---|---|---|---|
| detector, wall | 1327 | 2997 | 90 | 96.6 | 9.0 |
| detector, inference only | 1321 | 2959 | 87 | 35.3 | 2.5 |
| classifier | 249 | 558 | 18.7 | 24.6 | 2.1 |
| llm 0.5B, PyTorch eager | | | | 3847 (120 ms/tok) | 438 (13.7 ms/tok) |
| llm 1.5B, PyTorch eager | | | | skipped, RAM guard | 515 (16.1 ms/tok) |
| llm 0.5B, Ollama | | | | 715 for 25 tok (36.9 tok/s decode) | 117 for 32 tok (337 tok/s) |
| llm 1.5B, Ollama | | | | server died on load (4.2 GB free) | 257 for 32 tok (146 tok/s) |

Orin Ollama 0.5B stopped at 25 tokens (EOS); at its measured 27 ms per
decoded token a 32-token answer is about 900 ms.

Existing table rows for comparison: detector cpu 210 / gpu_small 35.3 /
gpu_large 1.8; classifier 95 / 8 / 0.9; llm gpu_small 420 / gpu_large 105.

## Reading

- The Orin detector inference-only number reproduces the 2026-08-25 row
  exactly (35.3 ms). End to end it is 96.6 ms: pre and post processing on
  the ARM cores cost more than the GPU pass.
- PyTorch eager is the wrong LLM runtime on small GPUs: 120 ms per token on
  the Orin, 14 ms on the 4090, both launch-overhead bound. Ollama (llama.cpp)
  gives 27 and 3 ms per token. The Ollama rows are the ones to use.
- The cpu class depends on which CPU one means. An embedded ARM board (Pi 5,
  Orin cores) is 15 to 30 times slower than the table's cpu estimates; a
  server x86 core matches them (90 / 18.7 vs 210 / 95).
- gpu_large measured on a 4090 (consumer, 24 GB) not an A100. Detector
  and classifier are within 2x of the A100 spec rows; the LLM row (117 ms)
  matches the 105 ms estimate.

## Co-tenancy and caveats

- GPU pods ran without a `nvidia.com/gpu` claim (claims held by idle
  ray-testbed workers), through the nvidia runtime class. GPU utilization
  0 percent before each run on the 4090; the Orin shares RAM with the idle
  worker (3.4 to 4.2 GB available), which is why the 1.5B models failed.
- Ollama 0.5.13 on ai2 because newer images need driver >= 550 and silently
  fall back to CPU (first attempt did; discarded). Ollama latest on the Orin
  because 0.5.13 is glibc 2.31 and the JetPack 6 libraries need 2.34.
- Two port-forwards on one local port made a first Orin Ollama run measure
  the 4090 pod; discarded, the script now uses per-pod ports.
- jetson-50 ran out of ephemeral storage once (7.7 GB image + model
  caches); the evicted pod was recreated. The node's kubelet stopped
  answering after the 1.5B load attempt; pods were deleted afterwards.
