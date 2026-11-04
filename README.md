# KineSight

Sensorless visual telemetry and SOP compliance engine. It turns overhead camera footage into automated manufacturing QA using SAM 3.1, OpenCV kinematics, and Muse Spark 1.3.

KineSight was built for the Meta Global AI Developer Hackathon. It does not need IoT sensors, and it does not pass raw video straight into an LLM. The pipeline has four stages:

1. **SOP compiler**: Muse Spark 1.3 turns a plain-text or PDF Standard Operating Procedure into SAM 3.1 text prompts and ordered contact rules (which actor touches which target, for how long, how many times).
2. **Segmentation and tracking**: SAM 3.1 segments the sampled video frames and keeps object IDs persistent across frames.
3. **Kinematic engine**: OpenCV and NumPy compute mask centroids, velocities, and dilated-mask contact events, then check them against the compiled rules.
4. **Audit and fix**: when a rule fails, Muse Spark 1.3 reviews three keyframes plus the telemetry and gives a root-cause verdict. Muse Image then draws a corrective workstation diagram.

## Status

Work in progress. Setup instructions will follow.
