(function () {
  "use strict";

  function readData(id) {
    const node = document.getElementById(id);
    if (!node) return null;
    try {
      return JSON.parse(node.textContent);
    } catch (error) {
      return null;
    }
  }

  function themeOptions(extra) {
    const defaults = {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { intersect: false, mode: "index" },
      plugins: {
        legend: {
          labels: {
            color: "#C6C6CE",
            usePointStyle: true,
            boxWidth: 8,
            padding: 16,
            font: { family: "Inter, sans-serif", size: 10 }
          }
        },
        tooltip: {
          enabled: true,
          backgroundColor: "#0A0A0C",
          borderColor: "#373740",
          borderWidth: 1,
          titleColor: "#F5F5F7",
          bodyColor: "#D0D0D6",
          padding: 10,
          displayColors: true,
          titleFont: { family: "Inter, sans-serif", size: 11, weight: "600" },
          bodyFont: { family: "Inter, sans-serif", size: 10 }
        }
      },
      scales: {
        x: {
          ticks: { color: "#8D8D97", maxRotation: 0, autoSkip: true, maxTicksLimit: 8, font: { size: 9 } },
          grid: { color: "rgba(255,255,255,.035)", drawBorder: false }
        },
        y: {
          beginAtZero: true,
          ticks: { color: "#8D8D97", precision: 0, font: { size: 9 } },
          grid: { color: "rgba(255,255,255,.065)", drawBorder: false }
        }
      }
    };
    const merged = Object.assign({}, defaults, extra || {});
    const supplied = extra || {};

    // Preserve the dark palette, tooltip styling, and axis colors when a chart
    // adds callbacks or chart-specific scale limits.
    merged.plugins = Object.assign({}, defaults.plugins, supplied.plugins || {});
    merged.plugins.legend = Object.assign({}, defaults.plugins.legend, (supplied.plugins || {}).legend || {});
    merged.plugins.legend.labels = Object.assign(
      {}, defaults.plugins.legend.labels, ((supplied.plugins || {}).legend || {}).labels || {}
    );
    merged.plugins.tooltip = Object.assign({}, defaults.plugins.tooltip, (supplied.plugins || {}).tooltip || {});
    merged.plugins.tooltip.callbacks = Object.assign(
      {}, defaults.plugins.tooltip.callbacks || {}, ((supplied.plugins || {}).tooltip || {}).callbacks || {}
    );

    if (Object.prototype.hasOwnProperty.call(supplied, "scales")) {
      if (Object.keys(supplied.scales || {}).length === 0) {
        merged.scales = {};
      } else {
        merged.scales = Object.assign({}, defaults.scales, supplied.scales);
        ["x", "y"].forEach(function (axis) {
          if (!supplied.scales[axis]) return;
          merged.scales[axis] = Object.assign({}, defaults.scales[axis], supplied.scales[axis]);
          merged.scales[axis].ticks = Object.assign(
            {}, defaults.scales[axis].ticks, supplied.scales[axis].ticks || {}
          );
          merged.scales[axis].grid = Object.assign(
            {}, defaults.scales[axis].grid, supplied.scales[axis].grid || {}
          );
        });
      }
    }
    return merged;
  }

  function createChart(canvasId, dataId, config) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const data = readData(dataId);
    if (!data || !window.Chart) {
      const fallback = document.createElement("p");
      fallback.className = "analytics-chart-runtime-note";
      fallback.textContent = "Interactive chart unavailable. The report values are still shown in the page summaries.";
      canvas.parentElement.replaceChildren(fallback);
      return;
    }
    const context = canvas.getContext("2d");
    new window.Chart(context, config(data));
  }

  document.addEventListener("DOMContentLoaded", function () {
    createChart("xp-chart", "analytics-xp-data", function (data) {
      return {
        type: "line",
        data: {
          labels: data.labels,
          datasets: [{
            label: "Cumulative XP",
            data: data.values,
            borderColor: "#00A6E8",
            backgroundColor: "rgba(0,166,232,.12)",
            pointBackgroundColor: "#00A6E8",
            pointBorderColor: "#111115",
            pointRadius: data.values.length > 30 ? 0 : 3,
            pointHoverRadius: 5,
            borderWidth: 2,
            fill: true,
            tension: .32
          }]
        },
        options: themeOptions({ plugins: { tooltip: { callbacks: { label: (item) => ` ${item.parsed.y} XP` } } } })
      };
    });

    createChart("activity-chart", "analytics-activity-data", function (data) {
      return {
        type: "bar",
        data: {
          labels: data.labels,
          datasets: [{
            label: "Recorded activity",
            data: data.values,
            backgroundColor: "rgba(0,166,232,.48)",
            hoverBackgroundColor: "#00A6E8",
            borderColor: "#00A6E8",
            borderWidth: 1,
            borderRadius: 4,
            maxBarThickness: 26
          }]
        },
        options: themeOptions({ plugins: { tooltip: { callbacks: { label: (item) => ` ${item.parsed.y} recorded events` } } } })
      };
    });

    createChart("quiz-chart", "analytics-quiz-data", function (data) {
      return {
        type: "line",
        data: {
          labels: data.labels,
          datasets: [{
            label: "Observed quiz accuracy",
            data: data.values,
            borderColor: "#FF2E7A",
            backgroundColor: "rgba(255,46,122,.10)",
            pointBackgroundColor: "#FF2E7A",
            pointBorderColor: "#111115",
            pointRadius: 3,
            pointHoverRadius: 5,
            borderWidth: 2,
            fill: true,
            tension: .28
          }]
        },
        options: themeOptions({
          scales: {
            x: { ticks: { color: "#8D8D97", maxRotation: 0, autoSkip: true, maxTicksLimit: 7 }, grid: { color: "rgba(255,255,255,.035)" } },
            y: { min: 0, max: 100, ticks: { color: "#8D8D97", callback: (value) => `${value}%` }, grid: { color: "rgba(255,255,255,.065)" } }
          },
          plugins: { tooltip: { callbacks: { label: (item) => ` ${item.parsed.y}% accuracy` } } }
        })
      };
    });

    createChart("topic-chart", "analytics-topics-data", function (data) {
      return {
        type: "bar",
        data: {
          labels: data.labels,
          datasets: [{
            label: "Observed accuracy",
            data: data.values,
            backgroundColor: data.values.map((value) => value < 55 ? "rgba(255,46,122,.58)" : "rgba(0,166,232,.56)"),
            hoverBackgroundColor: data.values.map((value) => value < 55 ? "#FF2E7A" : "#00A6E8"),
            borderRadius: 4,
            maxBarThickness: 22
          }]
        },
        options: themeOptions({
          indexAxis: "y",
          plugins: { legend: { display: false }, tooltip: { callbacks: { label: (item) => ` ${item.parsed.x}% observed accuracy` } } },
          scales: {
            x: { min: 0, max: 100, ticks: { color: "#8D8D97", callback: (value) => `${value}%` }, grid: { color: "rgba(255,255,255,.065)" } },
            y: { ticks: { color: "#B9B9C1", font: { size: 9 } }, grid: { display: false } }
          }
        })
      };
    });

    createChart("distribution-chart", "analytics-distribution-data", function (data) {
      return {
        type: "doughnut",
        data: {
          labels: data.labels,
          datasets: [{
            label: "Recorded activity",
            data: data.values,
            backgroundColor: ["#00A6E8", "#FF2E7A", "#6A73F7", "#47C988", "#FFC857", "#A78BFA"],
            borderColor: "#18181D",
            borderWidth: 3,
            hoverOffset: 6
          }]
        },
        options: themeOptions({
          cutout: "68%",
          interaction: { intersect: true, mode: "nearest" },
          scales: {},
          plugins: { legend: { position: "bottom" }, tooltip: { callbacks: { label: (item) => ` ${item.label}: ${item.parsed}` } } }
        })
      };
    });
  });
})();
