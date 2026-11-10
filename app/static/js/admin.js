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

// Mobile: open grouped sidebar sections when drawer is open
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

// 6. Mobile Navigation Drawer Controller
(function () {
  var drawer = document.getElementById("admin-sidebar");
  var backdrop = document.getElementById("drawer-backdrop");
  var toggleBtn = document.getElementById("drawer-toggle");
  var moreBtn = document.getElementById("bottom-more-btn");
  var closeBtn = document.getElementById("drawer-close");

  function openDrawer() {
    if (drawer) drawer.classList.add("open");
    if (backdrop) backdrop.classList.add("active");
    document.body.style.overflow = "hidden";
  }

  function closeDrawer() {
    if (drawer) drawer.classList.remove("open");
    if (backdrop) backdrop.classList.remove("active");
    document.body.style.overflow = "";
  }

  if (toggleBtn) toggleBtn.addEventListener("click", openDrawer);
  if (moreBtn) moreBtn.addEventListener("click", openDrawer);
  if (closeBtn) closeBtn.addEventListener("click", closeDrawer);
  if (backdrop) backdrop.addEventListener("click", closeDrawer);

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeDrawer();
  });
})();

// 7. Modals: Add Lead & Add Patient Controller
(function () {
  function openModal(id) {
    var modal = document.getElementById(id);
    if (modal) {
      modal.style.display = "flex";
      var first = modal.querySelector("input[name='name']");
      if (first) {
        setTimeout(function () { first.focus(); }, 60);
      }
    }
  }

  function closeModal(id) {
    var modal = document.getElementById(id);
    if (modal) {
      modal.style.display = "none";
    }
  }

  window.openAddLeadModal = function () { openModal("add-lead-modal"); };
  window.closeAddLeadModal = function () { closeModal("add-lead-modal"); };
  window.openAddPatientModal = function () { openModal("add-patient-modal"); };
  window.closeAddPatientModal = function () { closeModal("add-patient-modal"); };

  document.addEventListener("click", function (e) {
    var openBtn = e.target.closest("[data-open-modal]");
    if (openBtn) {
      e.preventDefault();
      openModal(openBtn.getAttribute("data-open-modal"));
      return;
    }

    var closeBtn = e.target.closest("[data-close-modal]");
    if (closeBtn) {
      e.preventDefault();
      closeModal(closeBtn.getAttribute("data-close-modal"));
      return;
    }

    if (e.target && (e.target.id === "add-lead-modal" || e.target.id === "add-patient-modal")) {
      e.target.style.display = "none";
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      closeModal("add-lead-modal");
      closeModal("add-patient-modal");
    }
  });

  // Automatically open modal if ?add=1 or ?add=true is in the query params
  document.addEventListener("DOMContentLoaded", function () {
    if (window.location.search.indexOf("add=1") !== -1 || window.location.search.indexOf("add=true") !== -1) {
      if (document.getElementById("add-lead-modal")) openModal("add-lead-modal");
      if (document.getElementById("add-patient-modal")) openModal("add-patient-modal");
    }
  });
  if (document.readyState !== "loading") {
    if (window.location.search.indexOf("add=1") !== -1 || window.location.search.indexOf("add=true") !== -1) {
      if (document.getElementById("add-lead-modal")) openModal("add-lead-modal");
      if (document.getElementById("add-patient-modal")) openModal("add-patient-modal");
    }
  }
})();


// ==============================================================================
// 8. Excel-Style Spreadsheet Table Controller (Leads & Patients)
// ==============================================================================
(function () {
  function getCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    var inp = document.querySelector('input[name="csrf_token"]');
    if (inp && inp.value) return inp.value;
    return "";
  }

  function showToast(msg, isError) {
    var existing = document.getElementById("excel-toast-msg");
    if (existing) existing.remove();
    var toast = document.createElement("div");
    toast.id = "excel-toast-msg";
    toast.className = "excel-toast " + (isError ? "excel-toast-error" : "excel-toast-success");
    toast.innerHTML = (isError ? "⚠️ " : "✓ ") + msg;
    document.body.appendChild(toast);
    setTimeout(function () { toast.classList.add("show"); }, 20);
    setTimeout(function () {
      toast.classList.remove("show");
      setTimeout(function () { toast.remove(); }, 300);
    }, 2800);
  }

  // --- Column Visibility Controller ---
  function initColumnVisibility(tableEl, storageKey) {
    if (!tableEl) return;
    var dropdown = document.getElementById("col-toggle-dropdown");
    var menu = document.getElementById("col-toggle-menu");
    if (!dropdown || !menu) return;

    var saved = {};
    try {
      saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
    } catch (e) { saved = {}; }

    function applyVisibility(colName, visible) {
      var cells = tableEl.querySelectorAll('[data-col="' + colName + '"]');
      cells.forEach(function (c) {
        c.style.display = visible ? "" : "none";
      });
    }

    // Initialize checkboxes
    menu.querySelectorAll('input[type="checkbox"]').forEach(function (chk) {
      var colName = chk.getAttribute("data-col-toggle");
      if (saved[colName] === false) {
        chk.checked = false;
        applyVisibility(colName, false);
      }
      chk.addEventListener("change", function () {
        var visible = chk.checked;
        applyVisibility(colName, visible);
        saved[colName] = visible;
        try { localStorage.setItem(storageKey, JSON.stringify(saved)); } catch (e) {}
      });
    });

    var btn = document.getElementById("col-toggle-btn");
    if (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        menu.classList.toggle("show");
      });
    }
    document.addEventListener("click", function (e) {
      if (!dropdown.contains(e.target)) {
        menu.classList.remove("show");
      }
    });
  }

  // --- Inline Cell Editing Controller ---
  function initExcelGrid(gridEl, endpointPrefix) {
    if (!gridEl) return;

    var currentCell = null;
    var currentInput = null;
    var originalVal = "";
    var isSaving = false;

    function getNextEditableCell(cell, forward) {
      var allCells = Array.from(gridEl.querySelectorAll(".excel-cell-editable"));
      allCells = allCells.filter(function (c) { return c.offsetParent !== null; });
      var idx = allCells.indexOf(cell);
      if (idx === -1) return null;
      var nextIdx = forward ? idx + 1 : idx - 1;
      if (nextIdx >= 0 && nextIdx < allCells.length) {
        return allCells[nextIdx];
      }
      return null;
    }

    function cancelEditing() {
      if (!currentCell) return;
      currentCell.classList.remove("is-editing");
      currentCell.textContent = currentCell.getAttribute("data-display") || originalVal;
      currentCell = null;
      currentInput = null;
    }

    function commitEditing(andJump, isShift) {
      if (!currentCell || !currentInput || isSaving) return;
      var cell = currentCell;
      var input = currentInput;
      var field = cell.getAttribute("data-field");
      var recordId = cell.getAttribute("data-id");
      var newVal = input.value.trim();

      if (newVal === originalVal) {
        cell.classList.remove("is-editing");
        cell.textContent = cell.getAttribute("data-display") || originalVal;
        currentCell = null;
        currentInput = null;
        if (andJump) {
          var next = getNextEditableCell(cell, !isShift);
          if (next) activateCell(next);
        }
        return;
      }

      isSaving = true;
      cell.classList.remove("is-editing");
      cell.textContent = newVal || "...";

      var payload = { field: field, value: newVal };
      fetch(endpointPrefix + "/" + recordId + "/inline", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrfToken()
        },
        body: JSON.stringify(payload)
      })
        .then(function (res) { return res.json(); })
        .then(function (data) {
          isSaving = false;
          if (data.ok) {
            cell.setAttribute("data-value", data.value);
            cell.setAttribute("data-display", data.display_value || data.value);
            cell.textContent = data.display_value || data.value;
            cell.classList.add("excel-flash-saved");
            setTimeout(function () { cell.classList.remove("excel-flash-saved"); }, 1200);
            showToast("Saved: " + field.replace("_", " "), false);

            currentCell = null;
            currentInput = null;
            if (andJump) {
              var next = getNextEditableCell(cell, !isShift);
              if (next) activateCell(next);
            }
          } else {
            cell.classList.add("excel-flash-error");
            cell.textContent = cell.getAttribute("data-display") || originalVal;
            setTimeout(function () { cell.classList.remove("excel-flash-error"); }, 1500);
            showToast(data.error || "Save failed", true);
            currentCell = null;
            currentInput = null;
          }
        })
        .catch(function (err) {
          isSaving = false;
          cell.classList.add("excel-flash-error");
          cell.textContent = cell.getAttribute("data-display") || originalVal;
          setTimeout(function () { cell.classList.remove("excel-flash-error"); }, 1500);
          showToast("Network error saving cell", true);
          currentCell = null;
          currentInput = null;
        });
    }

    function activateCell(cell) {
      if (currentCell === cell) return;
      if (currentCell) commitEditing(false, false);

      currentCell = cell;
      originalVal = (cell.getAttribute("data-value") || cell.textContent || "").trim();
      var fieldType = cell.getAttribute("data-type") || "text";

      cell.classList.add("is-editing");
      cell.textContent = "";

      var input;
      if (fieldType === "select") {
        input = document.createElement("select");
        input.className = "excel-inline-select";
        var optionsRaw = cell.getAttribute("data-options");
        var options = [];
        try { options = JSON.parse(optionsRaw || "[]"); } catch (e) { options = []; }
        options.forEach(function (opt) {
          var o = document.createElement("option");
          if (typeof opt === "object") {
            o.value = opt.id !== undefined ? opt.id : opt.value;
            o.textContent = opt.name || opt.label || opt.value;
          } else {
            o.value = opt;
            o.textContent = opt.charAt(0).toUpperCase() + opt.slice(1);
          }
          if (String(o.value) === String(originalVal) || String(o.textContent).toLowerCase() === String(originalVal).toLowerCase()) {
            o.selected = true;
          }
          input.appendChild(o);
        });
      } else if (fieldType === "date") {
        input = document.createElement("input");
        input.type = "date";
        input.className = "excel-inline-input";
        input.value = originalVal;
      } else {
        input = document.createElement("input");
        input.type = "text";
        input.className = "excel-inline-input";
        input.value = originalVal;
      }

      cell.appendChild(input);
      currentInput = input;
      input.focus();
      if (fieldType === "text") {
        input.select();
      } else if (fieldType === "select") {
        input.addEventListener("change", function () {
          commitEditing(false, false);
        });
        try {
          if (typeof input.showPicker === "function") input.showPicker();
        } catch (err) {}
      }

      input.addEventListener("keydown", function (e) {
        if (e.key === "Enter") {
          e.preventDefault();
          commitEditing(true, false);
        } else if (e.key === "Tab") {
          e.preventDefault();
          commitEditing(true, e.shiftKey);
        } else if (e.key === "Escape") {
          e.preventDefault();
          cancelEditing();
        }
      });

      input.addEventListener("blur", function () {
        setTimeout(function () {
          if (currentCell === cell) {
            commitEditing(false, false);
          }
        }, 120);
      });
    }

    gridEl.addEventListener("click", function (e) {
      var cell = e.target.closest(".excel-cell-editable");
      if (cell && !cell.classList.contains("is-editing")) {
        activateCell(cell);
      }
    });

    // Row selection and select all
    var selectAll = gridEl.querySelector(".excel-select-all-chk");
    var rowChks = gridEl.querySelectorAll(".excel-row-chk");
    var bulkBar = document.getElementById("excel-bulk-bar");
    var countEl = document.getElementById("excel-selected-count");

    function updateSelection() {
      var checked = gridEl.querySelectorAll(".excel-row-chk:checked");
      if (countEl) countEl.textContent = checked.length;
      if (bulkBar) bulkBar.style.display = checked.length > 0 ? "flex" : "none";
      if (selectAll) {
        selectAll.checked = rowChks.length > 0 && checked.length === rowChks.length;
        selectAll.indeterminate = checked.length > 0 && checked.length < rowChks.length;
      }
      gridEl.querySelectorAll(".excel-row").forEach(function (tr) {
        var chk = tr.querySelector(".excel-row-chk");
        if (chk && chk.checked) tr.classList.add("is-selected");
        else tr.classList.remove("is-selected");
      });
    }

    if (selectAll) {
      selectAll.addEventListener("change", function () {
        rowChks.forEach(function (c) { c.checked = selectAll.checked; });
        updateSelection();
      });
    }

    rowChks.forEach(function (c) {
      c.addEventListener("change", updateSelection);
    });

    var clearBtn = document.getElementById("excel-clear-selection");
    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        rowChks.forEach(function (c) { c.checked = false; });
        updateSelection();
      });
    }
  }

  // --- Quick History & Follow-up Modals ---
  function initHistoryAndFollowup() {
    var histModal = document.getElementById("excel-history-modal");
    var histTitle = document.getElementById("excel-hist-title");
    var histContent = document.getElementById("excel-hist-content");
    var histClose = document.getElementById("excel-hist-close");

    if (histClose && histModal) {
      histClose.addEventListener("click", function () { histModal.style.display = "none"; });
    }

    document.addEventListener("click", function (e) {
      var btnHist = e.target.closest("[data-view-history]");
      if (btnHist && histModal) {
        e.preventDefault();
        var type = btnHist.getAttribute("data-view-history");
        var id = btnHist.getAttribute("data-id");
        var name = btnHist.getAttribute("data-name") || ("#" + id);

        if (histTitle) histTitle.textContent = "📜 History — " + name;
        if (histContent) histContent.innerHTML = "<div style='text-align:center;padding:24px;color:#64748b'>Loading history…</div>";
        histModal.style.display = "flex";

        var url = type === "lead" ? ("/admin/leads/" + id + "/history-json") : ("/admin/patients/" + id + "/history-json");
        fetch(url)
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (!data.ok) {
              if (histContent) histContent.innerHTML = "<div style='color:#dc2626;padding:16px'>Error loading history</div>";
              return;
            }
            var list = data.history || data.followups || [];
            if (list.length === 0) {
              if (histContent) histContent.innerHTML = "<div style='color:#64748b;padding:24px;text-align:center'>No previous interactions recorded yet.</div>";
              return;
            }
            var html = '<div style="display:flex;flex-direction:column;gap:10px">';
            list.forEach(function (item) {
              html += '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px">';
              html += '  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;font-size:0.8rem;color:#64748b">';
              html += '    <span><b>' + (item.interaction_type || item.status || "Note").toUpperCase() + '</b> ' + (item.outcome ? ' · <span class="tag tag-pen" style="font-size:0.7rem">' + item.outcome + '</span>' : '') + '</span>';
              html += '    <span>' + (item.date || "") + '</span>';
              html += '  </div>';
              html += '  <div style="font-size:0.88rem;color:#1e293b;margin:4px 0">' + (item.summary || item.note || "") + '</div>';
              if (item.staff) html += '  <div style="font-size:0.78rem;color:#0e7490">Logged by: ' + item.staff + '</div>';
              if (item.due_date) html += '  <div style="font-size:0.78rem;color:#ea580c">📅 Scheduled follow-up: ' + item.due_date + '</div>';
              html += '</div>';
            });
            html += '</div>';
            if (histContent) histContent.innerHTML = html;
          })
          .catch(function () {
            if (histContent) histContent.innerHTML = "<div style='color:#dc2626;padding:16px'>Failed to load history entries</div>";
          });
      }

      // Convert lead button
      var btnConvert = e.target.closest("[data-convert-lead]");
      if (btnConvert) {
        e.preventDefault();
        var lid = btnConvert.getAttribute("data-convert-lead");
        var lname = btnConvert.getAttribute("data-name") || ("Lead #" + lid);
        if (confirm("Convert Lead #" + lid + " (" + lname + ") to Confirmed Patient?\n\nThis will promote the prospect to the Master Patient List and preserve all follow-up history.")) {
          var form = document.createElement("form");
          form.method = "POST";
          form.action = "/admin/leads/" + lid + "/convert";
          var tokenInp = document.createElement("input");
          tokenInp.type = "hidden";
          tokenInp.name = "csrf_token";
          tokenInp.value = getCsrfToken();
          form.appendChild(tokenInp);
          document.body.appendChild(form);
          form.submit();
        }
      }
    });

    if (histModal) {
      histModal.addEventListener("click", function (e) {
        if (e.target === histModal) histModal.style.display = "none";
      });
    }
  }

  // Auto-init on page load
  document.addEventListener("DOMContentLoaded", function () {
    var leadsGrid = document.getElementById("leads-excel-grid");
    if (leadsGrid) {
      initExcelGrid(leadsGrid, "/admin/leads");
      initColumnVisibility(leadsGrid, "orthopro_cols_leads");
    }

    var patientsGrid = document.getElementById("patients-excel-grid");
    if (patientsGrid) {
      initExcelGrid(patientsGrid, "/admin/patients");
      initColumnVisibility(patientsGrid, "orthopro_cols_patients");
    }

    initHistoryAndFollowup();
  });

  if (document.readyState !== "loading") {
    var leadsGrid = document.getElementById("leads-excel-grid");
    if (leadsGrid) {
      initExcelGrid(leadsGrid, "/admin/leads");
      initColumnVisibility(leadsGrid, "orthopro_cols_leads");
    }
    var patientsGrid = document.getElementById("patients-excel-grid");
    if (patientsGrid) {
      initExcelGrid(patientsGrid, "/admin/patients");
      initColumnVisibility(patientsGrid, "orthopro_cols_patients");
    }
    initHistoryAndFollowup();
  }
})();
