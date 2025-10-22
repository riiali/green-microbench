#  How to Port Your Service to GreenMicrobenchFramework

The goal of **GreenMicrobenchFramework** is to analyze and monitor the performance and energy impact of microservice-based applications — **without changing their code**.  
You only need to modify your **Dockerfiles** and **docker-compose.yml**.

---

## Components Added by the Framework

To enable observability and measurement, we introduce the following components:

| Component | Purpose | Role |
|------------|----------|------|
| **OpenTelemetry (OTEL)** | Framework for collecting traces, metrics, and logs. | Automatically instruments your microservices without modifying their code. |
| **OTEL Collector** | Central component that receives, processes, and exports telemetry data. | Gathers traces and metrics from all services and forwards them to visualization tools. |
| **Jaeger** | Distributed tracing visualization system. | Displays how each request propagates through your microservices and highlights bottlenecks. |
| **Prometheus** | Time-series database for collecting metrics. | Stores and exposes performance metrics (e.g., latency, request rate). |
| **Grafana** | Visualization and dashboard platform. | Displays Prometheus metrics in clear dashboards and graphs. |
| **cAdvisor** | Monitors resource usage of Docker containers. | Tracks CPU, memory, and I/O usage per service for energy estimation. |

The data collected through these tools will later be combined with **Shelly Plug** measurements to correlate software performance with **real energy consumption**.

---

## 1. Modify Your Microservices Dockerfile

The first step is to add the **OpenTelemetry libraries** to your microservices’ Dockerfiles, right after installing your normal dependencies.

```dockerfile
RUN pip install --no-cache-dir \
    opentelemetry-distro==0.47b0 \
    opentelemetry-exporter-otlp==1.26.0 \
    opentelemetry-instrumentation-flask==0.47b0 \
    opentelemetry-instrumentation-requests==0.47b0
```

Also make sure your Flask configuration is correct:

```dockerfile
ENV FLASK_APP=app.py
ENV FLASK_RUN_HOST=0.0.0.0
EXPOSE 5000
```
### Example of minimal dockerfile: 
```dockerfile
FROM python:3.9-alpine
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Add OpenTelemetry instrumentation
RUN pip install --no-cache-dir \
    opentelemetry-distro==0.47b0 \
    opentelemetry-exporter-otlp==1.26.0 \
    opentelemetry-instrumentation-flask==0.47b0 \
    opentelemetry-instrumentation-requests==0.47b0

COPY . .
CMD ["flask", "run"]
```
## 2. Modify Your docker-compose.yml
Update your docker-compose to enable auto-instrumentation and connect to the OTEL Collector from the framework.
Each service must:
- Have OTEL_* environment variables.
- Start with the command opentelemetry-instrument ...
- Be connected to the same Docker network as the framework (e.g., sutnet).

### Example: 
```dockerfile
services:
  rabbitmq:
    image: rabbitmq:3-management
    ports: ["5672:5672", "15672:15672"]
    networks: [sutnet]

  booking:
    build:
      context: ./booking
      dockerfile: Dockerfile.booking
    environment:
      OTEL_SERVICE_NAME: booking
      OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4317
      OTEL_TRACES_EXPORTER: otlp
      OTEL_METRICS_EXPORTER: otlp
      OTEL_LOGS_EXPORTER: none
    command: ["opentelemetry-instrument", "flask", "run", "--host", "0.0.0.0", "--port", "5000"]
    depends_on: [rabbitmq, otel-collector]
    networks: [sutnet]

  api-gateway:
    build:
      context: ./api-gateway
      dockerfile: Dockerfile.api-gateway
    environment:
      OTEL_SERVICE_NAME: api-gateway
      OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4317
      OTEL_TRACES_EXPORTER: otlp
      OTEL_METRICS_EXPORTER: otlp
      OTEL_LOGS_EXPORTER: none
    command: ["opentelemetry-instrument", "flask", "run", "--host", "0.0.0.0", "--port", "5000"]
    depends_on: [booking, otel-collector]
    ports: ["5000:5000"]
    networks: [sutnet]

networks:
  sutnet:
    external: true
```