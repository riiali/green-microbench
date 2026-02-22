# GreenMicrobench 🟢⚡

**A Green Microservices Benchmark Framework for Energy-Aware
Evaluation**

GreenMicrobench is a framework for repeatable, workload-driven energy
benchmarking of containerized microservice systems.

It is designed to run on a dedicated Raspberry Pi testbed and combines:

-   🔌 Hardware-level power measurements via Shelly
-   📊 Container-level observability via Prometheus + cAdvisor
-   🚦 Workload generation via Locust
-   📈 Normalized multi-source analysis and reporting

The goal is to provide structured, comparable, and actionable energy
feedback for developers.

------------------------------------------------------------------------

# 📂 Repository Structure

    green-microbench/
    │
    ├── GreenMicrobenchFramework/   # Core framework (runner, collectors, analyzers)
    ├── SUT/                        # Systems Under Test (example microservices)
    └── README.md

------------------------------------------------------------------------

# 🧠 Core Concepts

## System Under Test (SUT)

A containerized microservice application executed via Docker Compose.

## Scenario

A configuration describing: - Deployment configuration - Workload
parameters - Observation window - Energy source (Shelly) - Repetitions

## Experiment Run

One full execution of: 1. SUT deployment 2. Shelly measurement 3.
Metrics collection 4. Workload execution 5. Data normalization 6. Report
generation

Multiple runs improve statistical reliability.

------------------------------------------------------------------------

# ⚙️ Prerequisites

## Hardware

-   Raspberry Pi 4 (recommended)
-   Dedicated power supply
-   Active cooling (to avoid thermal throttling)
-   Shelly smart plug or energy meter (System validated with Shelly Plug S)

## Software

-   Raspberry Pi OS (or Linux)
-   Docker + Docker Compose plugin
-   Python 3.x
-   Prometheus
-   cAdvisor
-   Locust

------------------------------------------------------------------------

# 🔌 Energy Measurement with Shelly

GreenMicrobench uses Shelly smart devices to collect hardware-grounded
power measurements.

## Hardware Setup

1.  Connect Raspberry Pi power supply through the Shelly plug.
2.  Ensure Shelly is connected to the same network.
3.  Verify Shelly is reachable via browser
    (http://`<shelly-ip>`{=html}).

Shelly must measure only the Raspberry Pi testbed power line.

------------------------------------------------------------------------


# 📡 Observability Stack

## cAdvisor

Collects per-container metrics: - CPU usage - Memory usage - Network
I/O - Filesystem I/O

## Prometheus

Scrapes cAdvisor metrics and stores time series data.

Typical ports: - cAdvisor → 8080 - Prometheus → 9090

------------------------------------------------------------------------

# 🚦 Workload Generation (Locust)

Locust generates repeatable HTTP workloads.

Recommended configuration: - Fixed number of users - Fixed spawn rate -
Fixed duration

Example: - Users: 50 - Spawn rate: 10 - Duration: 300s

------------------------------------------------------------------------

# 🔄 Experiment Lifecycle

1.  Deploy SUT (Docker Compose)
2.  Start Prometheus + cAdvisor
3.  Warm-up phase (optional)
4.  Start Shelly collection
5.  Start workload (Locust)
6.  Stop workload
7.  Stop Shelly collection
8.  Export Prometheus metrics
9.  Normalize datasets
10. Generate report

------------------------------------------------------------------------

# 📊 Outputs

Each experiment produces:

## Raw Data

-   Shelly power samples (CSV/JSON)
-   Prometheus exports
-   Workload logs

## Normalized Dataset

Aligned timestamps across: - Power - CPU/memory - Request rate

## HTML Report

Includes: - Total energy consumption - Mean power - Per-service impact
ranking - Correlation graphs - Experiment metadata

------------------------------------------------------------------------

# 🔁 Repeatability Best Practices

## Dedicated Testbed

-   No desktop environment
-   No background workloads
-   Reserved exclusively for experiments

## CPU Governor

For regression testing:

    performance

For realistic behavior:

    ondemand

## Thermal Control

-   Use cooling
-   Monitor CPU frequency
-   Avoid thermal throttling

------------------------------------------------------------------------

# 🔬 CI/CD Integration (Energy Regression Testing)

GreenMicrobench can be integrated into CI/CD pipelines.

Pipeline example: 1. Build new Docker images 2. Deploy on Raspberry Pi
via SSH 3. Execute benchmark scenario 4. Compare with baseline 5. Fail
pipeline if threshold exceeded

Example thresholds: - Total Energy +5% - p95 Latency +10%

------------------------------------------------------------------------

# 🎯 Design Goals

GreenMicrobench provides feedback that is:

-   Action-oriented
-   Comparable
-   Attributable
-   CI/CD-ready

------------------------------------------------------------------------
