"""Transparent estimates for the Computer System Performance Lab.

This is an educational model, not a hardware benchmark. Keep its equations in
one place so HTML previews, saved attempts, and future tests share the same
server-verified result.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SimulationBounds:
    minimum: int
    maximum: int


PARAMETER_BOUNDS = {
    "cpu_workload": SimulationBounds(10, 100),
    "process_count": SimulationBounds(1, 20),
    "ram_gb": SimulationBounds(1, 32),
    "background_workload": SimulationBounds(0, 100),
}


def calculate_computer_performance(parameters):
    """Return estimated utilization, load, performance, and an explanation."""
    values = {}
    for name, bounds in PARAMETER_BOUNDS.items():
        value = parameters.get(name)
        if type(value) is not int or not bounds.minimum <= value <= bounds.maximum:
            raise ValueError(f"{name} must be an integer from {bounds.minimum} to {bounds.maximum}.")
        values[name] = value

    cpu_workload = values["cpu_workload"]
    process_count = values["process_count"]
    ram_gb = values["ram_gb"]
    background_workload = values["background_workload"]

    process_overhead = max(0, process_count - 4) * 1.6
    cpu_demand = cpu_workload + background_workload * 0.35 + process_overhead
    cpu_utilization = min(100, round(cpu_demand))

    # Each process reserves a small baseline plus a workload-linked amount;
    # background tasks add their own memory demand.
    memory_demand = process_count * (0.25 + cpu_workload / 100 * 0.20)
    memory_demand += background_workload / 100 * 2.5
    memory_utilization = min(100, round(memory_demand / ram_gb * 100))

    cpu_pressure = min(100, max(0, (cpu_demand - 65) / 35 * 100))
    memory_pressure = min(100, max(0, (memory_utilization - 70) / 30 * 100))
    process_pressure = min(100, max(0, (process_count - 8) / 12 * 100))
    performance_score = max(
        0,
        min(100, round(100 - cpu_pressure * 0.45 - memory_pressure * 0.35 - process_pressure * 0.20)),
    )
    system_load = round(cpu_demand / 100, 2)
    estimated_response_ms = round(
        120 * (1 + cpu_pressure / 100 * 1.8 + memory_pressure / 100 * 1.8 + process_pressure / 100 * 0.6)
    )

    if performance_score >= 85:
        system_condition = "Healthy"
    elif performance_score >= 65:
        system_condition = "Moderate load"
    elif performance_score >= 40:
        system_condition = "Under pressure"
    else:
        system_condition = "Critical load"

    pressures = {
        "CPU saturation": cpu_pressure,
        "Memory pressure": memory_pressure,
        "Process contention": process_pressure,
    }
    bottleneck, strongest_pressure = max(pressures.items(), key=lambda item: item[1])
    if strongest_pressure < 10:
        bottleneck = "No significant bottleneck"
        insight = "The modeled resources have headroom. Increase one workload at a time and observe which metric moves first."
    elif bottleneck == "CPU saturation":
        insight = "CPU demand is the main constraint. Reduce foreground or background workload, or run fewer concurrent processes."
    elif bottleneck == "Memory pressure":
        insight = "RAM is the main constraint. Increase the allocation or reduce the memory demand from processes and background work."
    else:
        insight = "Process contention is the main constraint. More simultaneous processes add scheduling overhead even when each task is small."

    return {
        **values,
        "cpu_utilization_percent": cpu_utilization,
        "memory_demand_gb": round(memory_demand, 1),
        "memory_utilization_percent": memory_utilization,
        "system_load": system_load,
        "performance_score": performance_score,
        "system_condition": system_condition,
        "estimated_response_ms": estimated_response_ms,
        "bottleneck": bottleneck,
        "insight": insight,
        "model_note": "Illustrative estimates using a simplified 4-core desktop profile; actual hardware results vary.",
    }


SIMULATION_ENGINES = {
    "computer-system-performance-lab": calculate_computer_performance,
}


def get_simulation_engine(slug):
    """Look up an implemented simulation engine without dynamic evaluation."""
    return SIMULATION_ENGINES.get(slug)
