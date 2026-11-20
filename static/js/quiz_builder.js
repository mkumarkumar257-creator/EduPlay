(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    const list = document.getElementById("question-editor-list");
    const template = document.getElementById("question-row-template");
    const totalForms = document.querySelector("input[name$='-TOTAL_FORMS']");
    const addButton = document.getElementById("add-question-row");
    if (!list || !template || !totalForms || !addButton) return;

    function activeRows() {
      return Array.from(list.querySelectorAll("[data-question-row]")).filter((row) => !row.hidden);
    }

    function hasQuestionContent(row) {
      return ["prompt", "option_a", "option_b", "option_c", "option_d"].some((suffix) => {
        const field = row.querySelector(`textarea[name$='-${suffix}'],input[name$='-${suffix}']`);
        return field && field.value.trim();
      });
    }

    function updateRows() {
      let order = 0;
      activeRows().forEach((row, index) => {
        const number = row.querySelector("[data-question-number]");
        if (number) number.textContent = String(index + 1);
        if (hasQuestionContent(row)) {
          order += 1;
          const orderField = row.querySelector("input[name$='-order']");
          if (orderField) orderField.value = String(order);
        } else {
          const orderField = row.querySelector("input[name$='-order']");
          if (orderField) orderField.value = "1";
        }
      });
      addButton.disabled = Number(totalForms.value) >= 50;
      addButton.textContent = addButton.disabled ? "Question limit reached" : "＋ Add question";
    }

    addButton.addEventListener("click", function () {
      const index = Number(totalForms.value);
      if (index >= 50) return;
      const html = template.innerHTML.replace(/__prefix__/g, String(index));
      const wrapper = document.createElement("div");
      wrapper.innerHTML = html.trim();
      list.appendChild(wrapper.firstElementChild);
      totalForms.value = String(index + 1);
      updateRows();
    });

    list.addEventListener("click", function (event) {
      const removeButton = event.target.closest("[data-remove-question]");
      if (!removeButton) return;
      const row = removeButton.closest("[data-question-row]");
      const deleteField = row && row.querySelector("input[name$='-DELETE']");
      if (!row || !deleteField) return;
      deleteField.value = "on";
      row.hidden = true;
      updateRows();
    });

    list.addEventListener("input", function (event) {
      if (event.target.matches("textarea,input")) updateRows();
    });

    updateRows();
  });
})();
