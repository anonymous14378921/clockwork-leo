# Jetson Orin Nano Super YOLOv8 benchmark (ours), 2026-08-25

- Device: NVIDIA Jetson Orin Nano Engineering Reference Developer Kit Super
  (measurement cluster, /proc/device-tree/model verified).
- Method: pod ultralytics/ultralytics:latest-jetson-jetpack6 (torch 2.10.0,
  CUDA true), batch-1 FP16 PyTorch predict, imgsz 640, random image, 5
  warmup + 30 timed iters, Ultralytics per-image inference ms, median.
- Co-tenancy: node shared with an idle ray-testbed worker; GR3D_FREQ 0%
  before and after; a MemAvailable guard skipped models that could pressure
  the co-tenant (yolov8x skipped at 2.7 GB available).
- Results (median / mean / p95 ms per image):
  yolov8n 25.80 / 24.88 / 26.37
  yolov8s 26.63 / 27.38 / 35.46
  yolov8m 35.35 / 37.64 / 47.46
  yolov8l 49.61 / 50.73 / 54.47
  yolov8x skipped (RAM guard)
- Calibration: roofline (67 TOPS x 0.7) underestimates these by 14x (l) to
  139x (n): batch-1 is launch-overhead-bound. Runtime is PyTorch, not
  TensorRT; entries are conservative (TensorRT would be faster).
- tegrastats before: RAM 3777/7620MB GR3D 0% | after: RAM 4053/7620MB GR3D 0%
