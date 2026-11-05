"use strict";

// 행을 추가·삭제해도 다른 행의 입력은 유지한다. 입력 검증은 서버에서 처리한다.
document.querySelectorAll(".lab-result-form").forEach((form) => {
  const rows = form.querySelector("[data-lab-result-rows]");
  const addButton = form.querySelector("[data-add-row]");
  const status = form.querySelector("[data-row-status]");
  const rowTemplate = rows.firstElementChild.cloneNode(true);
  let nextId = 1;

  rows.querySelector("[data-remove-row]").hidden = false;
  addButton.hidden = false;

  addButton.addEventListener("click", () => {
    const row = rowTemplate.cloneNode(true);
    nextId += 1;
    row.querySelectorAll("input, select").forEach((field) => {
      const label = row.querySelector(`label[for="${field.id}"]`);
      field.id = `${field.name}_${nextId}`;
      field.value = "";
      label.htmlFor = field.id;
      label.textContent = `${label.textContent.replace(/\s+\d+$/, "")} ${nextId}`;
    });
    const removeButton = row.querySelector("[data-remove-row]");
    removeButton.hidden = false;
    removeButton.setAttribute("aria-label", `H/L 항목 ${nextId} 삭제`);
    rows.append(row);
    row.querySelector("select").focus();
    status.textContent = `H/L 입력란 ${rows.children.length}줄`;
  });

  rows.addEventListener("click", (event) => {
    const removeButton = event.target.closest("[data-remove-row]");
    if (!removeButton) return;
    const row = removeButton.closest(".lab-row");
    if (rows.children.length === 1) {
      row.querySelectorAll("input, select").forEach((field) => { field.value = ""; });
      row.querySelector("select").focus();
      status.textContent = "마지막 입력란의 내용을 비웠습니다.";
      return;
    }
    const nextRow = row.nextElementSibling || row.previousElementSibling;
    row.remove();
    nextRow.querySelector("select").focus();
    status.textContent = `H/L 입력란 ${rows.children.length}줄`;
  });
});
