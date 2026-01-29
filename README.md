# Green Microbenchmark Framework

Green Microbenchmark Framework is a framework for analyzing the energy consumption of microservices architectures, designed for edge/low-power environments (e.g., Raspberry Pi).

The framework allows you to:
- run controlled workloads on microservices applications
- collect CPU and power metrics from multiple sources
- attribute power consumption to individual services
- compare software estimates (PowerJoular) with actual hardware measurements (Shelly)

The framework generates an HTML report that compares:

- **Estimated power** (PowerJoular)
- **Measured power** (Shelly)
- **Integrated energy per microservice**
- **Peak behavior**
- **Ranking of the most impactful services**

<img width="1886" height="847" alt="image" src="https://github.com/user-attachments/assets/90f0cb03-a4b6-4c20-b64a-8a1e4adc34b6" />


### Report Example

Below is a screenshot of a report generated during a 30-minute experiment with steady-state load:

![Shelly vs PowerJoular report]
<img width="1478" height="1761" alt="image" src="https://github.com/user-attachments/assets/71a8636a-fcbc-42e2-8ba5-fad9f28aa687" />
