# Temporal resolution validation

This experiment replays fixed schedules from the approximately one minute
planning grid at finer times. It does not change their provisioning states.
At each replay time it recomputes orbital positions, visibility, ISL
propagation, and the best visible ingress and egress within the scheduled
active planes.

Run with `just run pP_temporal_validation`. The pinned source schedule and its
hashes are copied into every result directory. Outputs separate released
resources, lack of visible access, lack of an ISL route, and latency above the
SLO. The reported longest failure run is a sampled duration and does not prove
continuous behavior between replay samples.

