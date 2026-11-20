// Live preview for the Computer System Performance Lab.
// The matching Python engine recalculates and validates every saved run.
(() => {
  const form = document.querySelector("[data-performance-form]");
  if (!form) return;

  const inputs = Object.fromEntries(
    [...form.querySelectorAll("[data-simulation-input]")].map((input) => [input.dataset.simulationInput, input]),
  );
  const outputs = Object.fromEntries(
    [...document.querySelectorAll("[data-live-value]")].map((output) => [output.dataset.liveValue, output]),
  );

  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const calculate = () => {
    const cpuWorkload = Number(inputs.cpu_workload.value);
    const processCount = Number(inputs.process_count.value);
    const ramGb = Number(inputs.ram_gb.value);
    const backgroundWorkload = Number(inputs.background_workload.value);
    const processOverhead = Math.max(0, processCount - 4) * 1.6;
    const cpuDemand = cpuWorkload + backgroundWorkload * 0.35 + processOverhead;
    const cpuUtilization = Math.min(100, Math.round(cpuDemand));
    const memoryDemand = processCount * (0.25 + (cpuWorkload / 100) * 0.2) + (backgroundWorkload / 100) * 2.5;
    const memoryUtilization = Math.min(100, Math.round((memoryDemand / ramGb) * 100));
    const cpuPressure = clamp(((cpuDemand - 65) / 35) * 100, 0, 100);
    const memoryPressure = clamp(((memoryUtilization - 70) / 30) * 100, 0, 100);
    const processPressure = clamp(((processCount - 8) / 12) * 100, 0, 100);
    const performanceScore = clamp(Math.round(100 - cpuPressure * 0.45 - memoryPressure * 0.35 - processPressure * 0.2), 0, 100);
    const responseMs = Math.round(120 * (1 + (cpuPressure / 100) * 1.8 + (memoryPressure / 100) * 1.8 + (processPressure / 100) * 0.6));

    let systemCondition = "Critical load";
    if (performanceScore >= 85) systemCondition = "Healthy";
    else if (performanceScore >= 65) systemCondition = "Moderate load";
    else if (performanceScore >= 40) systemCondition = "Under pressure";

    const pressures = [
      ["CPU saturation", cpuPressure],
      ["Memory pressure", memoryPressure],
      ["Process contention", processPressure],
    ].sort((left, right) => right[1] - left[1]);
    let bottleneck = pressures[0][0];
    let insight = "Process contention is the main constraint. More simultaneous processes add scheduling overhead even when each task is small.";
    if (pressures[0][1] < 10) {
      bottleneck = "No significant bottleneck";
      insight = "The modeled resources have headroom. Increase one workload at a time and observe which metric moves first.";
    } else if (bottleneck === "CPU saturation") {
      insight = "CPU demand is the main constraint. Reduce foreground or background workload, or run fewer concurrent processes.";
    } else if (bottleneck === "Memory pressure") {
      insight = "RAM is the main constraint. Increase the allocation or reduce the memory demand from processes and background work.";
    }

    const results = {
      cpu_utilization_percent: `${cpuUtilization}%`,
      memory_utilization_percent: `${memoryUtilization}%`,
      memory_demand_gb: `${memoryDemand.toFixed(1)} GB`,
      system_load: `${(cpuDemand / 100).toFixed(2)}×`,
      performance_score: String(performanceScore),
      system_condition: systemCondition,
      estimated_response_ms: `${responseMs} ms`,
      bottleneck,
      insight,
    };
    Object.entries(results).forEach(([key, value]) => {
      if (outputs[key]) outputs[key].textContent = value;
    });

    document.querySelectorAll("[data-live-meter]").forEach((meter) => {
      const rawValue = meter.dataset.liveMeter === "cpu_utilization_percent" ? cpuUtilization : memoryUtilization;
      meter.style.width = `${rawValue}%`;
      meter.setAttribute("aria-valuenow", String(rawValue));
    });
    const scoreRing = document.querySelector("[data-live-score-ring]");
    if (scoreRing) scoreRing.style.setProperty("--score", `${performanceScore}%`);
  };

  Object.values(inputs).forEach((input) => {
    const output = document.querySelector(`[data-value-for="${input.dataset.simulationInput}"]`);
    const update = () => {
      if (output) output.textContent = `${input.value}${input.dataset.unit || ""}`;
      calculate();
    };
    input.addEventListener("input", update);
    input.addEventListener("change", update);
    update();
  });
})();
