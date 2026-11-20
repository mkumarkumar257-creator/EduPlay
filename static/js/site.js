// Bootstrap handles the responsive navigation menu; this adds accessible
// password visibility controls to the account forms.
document.querySelectorAll("[data-password-toggle]").forEach((button) => {
  button.addEventListener("click", () => {
    const input = document.getElementById(button.dataset.passwordToggle);
    if (!input) return;

    const isVisible = input.type === "text";
    input.type = isVisible ? "password" : "text";
    button.textContent = isVisible ? "Show" : "Hide";
    button.setAttribute("aria-label", isVisible ? "Show password" : "Hide password");
    button.setAttribute("aria-pressed", String(!isVisible));
  });
});

document.querySelectorAll("[data-quiz-timer]").forEach((timer) => {
  let secondsRemaining = Math.max(0, Number.parseInt(timer.dataset.seconds || "0", 10));
  const timeoutForm = document.getElementById("quiz-timeout-form");
  let timerInterval = null;

  const updateTimer = () => {
    const minutes = Math.floor(secondsRemaining / 60).toString().padStart(2, "0");
    const seconds = (secondsRemaining % 60).toString().padStart(2, "0");
    timer.textContent = `${minutes}:${seconds}`;
    timer.classList.toggle("timer-warning", secondsRemaining <= 20);

    if (secondsRemaining <= 0) {
      window.clearInterval(timerInterval);
      if (timeoutForm && !timeoutForm.dataset.submitting) {
        timeoutForm.dataset.submitting = "true";
        timeoutForm.requestSubmit();
      }
    }
    secondsRemaining -= 1;
  };

  const shouldStartTimer = secondsRemaining > 0;
  updateTimer();
  if (shouldStartTimer) timerInterval = window.setInterval(updateTimer, 1000);
});

document.querySelectorAll("[data-quiz-answer-form]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (form.dataset.submitting) {
      event.preventDefault();
      return;
    }
    form.dataset.submitting = "true";
    form.setAttribute("aria-busy", "true");
    form.querySelectorAll(".quiz-option").forEach((button) => {
      if (button !== event.submitter) button.disabled = true;
    });
  });
});

