// Admin panel behaviour, kept external so CSP can use script-src 'self'.
//  1. Confirmation dialogs for destructive forms      -> <form data-confirm="...">
//  2. Copy-to-clipboard buttons                       -> <button data-copy="/uploads/x.jpg">
//  3. Media-library pickers filling a URL input       -> <select data-fill="#target-id">
(function () {
  // 1. Confirm before submitting destructive forms.
  document.addEventListener("submit", function (e) {
    var form = e.target.closest("form[data-confirm]");
    if (form && !window.confirm(form.getAttribute("data-confirm"))) {
      e.preventDefault();
    }
  });

  // 2. Copy-to-clipboard.
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("button[data-copy]");
    if (!btn) return;
    var url = window.location.origin + btn.getAttribute("data-copy");
    var done = function () {
      btn.textContent = "Copied!";
      btn.disabled = true;
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(done).catch(function () {
        window.prompt("Copy this URL:", url);
      });
    } else {
      window.prompt("Copy this URL:", url);
    }
  });

  // 3. Media picker -> fill URL input.
  document.addEventListener("change", function (e) {
    var sel = e.target.closest("select[data-fill]");
    if (!sel || !sel.value) return;
    var target = document.querySelector(sel.getAttribute("data-fill"));
    if (target) target.value = sel.value;
  });

  // 4. Progressive disclosure: a radio with data-toggle="#id" shows that block
  //    only when it is selected; any required input inside is enabled/disabled.
  function applyToggle(input) {
    var sel = input.getAttribute("data-toggle");
    if (!sel) return;
    var block = document.querySelector(sel);
    if (!block) return;
    var show = input.checked && input.value === (input.getAttribute("data-toggle-value") || "yes");
    block.style.display = show ? "block" : "none";
    block.querySelectorAll("input[required], select[required]").forEach(function (el) {
      el.required = show ? true : false;
    });
    var btn = document.querySelector("[data-toggle-label]");
    if (btn) {
      btn.textContent = show
        ? btn.getAttribute("data-toggle-label")
        : btn.getAttribute("data-toggle-label-off") || btn.getAttribute("data-toggle-label");
    }
  }
  document.addEventListener("change", function (e) {
    var input = e.target.closest("input[data-toggle]");
    if (!input) return;
    var name = input.getAttribute("name");
    document.querySelectorAll('input[name="' + name + '"][data-toggle]').forEach(applyToggle);
  });
  // Apply initial state on load.
  document.querySelectorAll("input[data-toggle]:checked").forEach(applyToggle);
})();

// Mobile: open grouped sidebar sections so their links join the pill strip.
(function () {
  if (!window.matchMedia || !window.matchMedia("(max-width: 860px)").matches) return;
  document.querySelectorAll("details.subnav").forEach(function (d) { d.open = true; });
})();

// 5. Bulk selection toolbar for Leads
(function () {
  function updateBulkBar() {
    var checked = document.querySelectorAll(".lead-chk:checked");
    var bulkBar = document.getElementById("bulk-bar");
    var countEl = document.getElementById("selected-count");
    var selectAll = document.getElementById("select-all-leads");
    if (countEl) countEl.textContent = checked.length;
    if (bulkBar) {
      bulkBar.style.display = checked.length > 0 ? "flex" : "none";
    }
    if (selectAll) {
      var all = document.querySelectorAll(".lead-chk");
      selectAll.checked = all.length > 0 && checked.length === all.length;
      selectAll.indeterminate = checked.length > 0 && checked.length < all.length;
    }
  }

  function handleSelectAll(checkedState) {
    var all = document.querySelectorAll(".lead-chk");
    for (var i = 0; i < all.length; i++) {
      all[i].checked = checkedState;
    }
    updateBulkBar();
  }

  document.addEventListener("change", function (e) {
    if (e.target && e.target.id === "select-all-leads") {
      handleSelectAll(e.target.checked);
    } else if (e.target && e.target.classList.contains("lead-chk")) {
      updateBulkBar();
    }
  });

  document.addEventListener("click", function (e) {
    if (e.target && e.target.id === "clear-selection-btn") {
      handleSelectAll(false);
      var selectAll = document.getElementById("select-all-leads");
      if (selectAll) {
        selectAll.checked = false;
        selectAll.indeterminate = false;
      }
    }
  });

  document.addEventListener("DOMContentLoaded", updateBulkBar);
  if (document.readyState !== "loading") updateBulkBar();
})();
