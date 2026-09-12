"""Profile-table sanity: measured lookups return the published numbers, the
roofline fallback engages only where no measurement exists, and the physical
invariant holds (measured latency >= ideal roofline latency, since the roofline
is an upper bound on throughput). This last check is the anti-fabrication
calibration: it must hold for every (variant, device) pair with a measurement,
and its per-pair ratio quantifies how far napkin math was from reality.
"""

import math

from lab import constants as C
from lab import profiles as P


def _ladder():
    return {v.name: v for v in P.load_ladder("yolo_coco")}


def test_measured_lookup_matches_published_hailo_fps():
    # Hailo Model Zoo HAILO8 table: yolov8x batch-1 24.6 FPS -> 40.65 ms/image.
    v = _ladder()["YOLOv8x"]
    ms, source = P.exec_ms_per_image(v, "iX10", C.device("iX10"))
    assert source == P.MEASURED
    assert math.isclose(ms, 1e3 / 24.6, rel_tol=1e-9)


def test_measured_lookup_matches_published_a100_ms():
    # Ultralytics table: yolov8n 0.99 ms on A100 TensorRT (H100 stand-in).
    v = _ladder()["YOLOv8n"]
    ms, source = P.exec_ms_per_image(v, "H100", C.device("H100"))
    assert source == P.MEASURED
    assert math.isclose(ms, 0.99, rel_tol=1e-9)


def test_unprofiled_device_falls_back_to_roofline():
    # RAD5545 has no published detector benchmark; the fallback must engage and
    # must exclude it by orders of magnitude (its role in the fleet).
    v = _ladder()["YOLOv8n"]
    dev = C.device("RAD5545")
    ms, source = P.exec_ms_per_image(v, "RAD5545", dev)
    assert source == P.ROOFLINE
    assert math.isclose(ms, 8.7e9 / (dev.peak_flops * C.duty_cycle()) * 1e3,
                        rel_tol=1e-9)
    assert ms > 1e3  # one crop alone costs seconds on a space-grade CPU


def test_roofline_lower_bounds_every_measurement():
    # Physics check: no measured (variant, device) time may beat the ideal
    # roofline for that device. Catches transcription errors in the tables.
    for v in P.load_ladder("yolo_coco"):
        for dev_name in v.latency:
            dev = C.device(dev_name)
            ideal = P.roofline_ms(v.gflops_per_image * 1e9, dev)
            assert v.latency[dev_name].ms_per_image >= ideal, (v.name, dev_name)


def test_accuracy_is_device_aware():
    # The Hailo-8 delivers quantized mAP; the GPU delivers float mAP.
    v = _ladder()["YOLOv8x"]
    assert P.accuracy_on(v, "iX10") == 52.9
    assert P.accuracy_on(v, "H100") == 53.9
    assert P.accuracy_on(v, "RAD5545") == 53.9  # no profile -> float mAP
