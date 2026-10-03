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

// 7. General Modal Controller (Add Lead, Add Patient, etc.)
(function () {
  function openModal(modal) {
    if (typeof modal === "string") modal = document.querySelector(modal);
    if (!modal) return;
    modal.style.display = "flex";
    var first = modal.querySelector("input:not([type=hidden]), select, textarea");
    if (first) setTimeout(function () { first.focus(); }, 80);
  }

  function closeModal(modal) {
    if (typeof modal === "string") modal = document.querySelector(modal);
    if (!modal) return;
    modal.style.display = "none";
  }

  // Open triggers via delegation
  document.addEventListener("click", function (e) {
    var openBtn = e.target.closest("[data-modal-open]");
    if (openBtn) {
      e.preventDefault();
      var target = openBtn.getAttribute("data-modal-open");
      openModal(target);
      return;
    }
    // Specific IDs and button text fallbacks
    var btn = e.target.closest("button, a");
    if (btn) {
      var txt = (btn.textContent || "").trim();
      if (btn.id === "btn-open-add-lead" || txt.indexOf("Add Lead") !== -1) {
        var ml = document.getElementById("add-lead-modal");
        if (ml) { e.preventDefault(); openModal(ml); return; }
      }
      if (btn.id === "btn-open-add-patient" || txt.indexOf("Add Patient") !== -1 || txt.indexOf("Register Patient") !== -1) {
        var mp = document.getElementById("add-patient-modal");
        if (mp) { e.preventDefault(); openModal(mp); return; }
      }
    }

    // Close triggers
    var closeBtn = e.target.closest("[data-modal-close]");
    if (closeBtn) {
      e.preventDefault();
      var target = closeBtn.getAttribute("data-modal-close");
      if (target) closeModal(target);
      else {
        var parentModal = closeBtn.closest("#add-lead-modal, #add-patient-modal");
        if (parentModal) closeModal(parentModal);
      }
      return;
    }

    // Backdrop click
    if (e.target && (e.target.id === "add-lead-modal" || e.target.id === "add-patient-modal")) {
      closeModal(e.target);
    }
  });

  // Escape key closes modals
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      document.querySelectorAll("#add-lead-modal, #add-patient-modal").forEach(function (m) {
        m.style.display = "none";
      });
    }
  });

  // Global functions for window scope
  window.openAddLeadModal = function () { openModal("#add-lead-modal"); };
  window.closeAddLeadModal = function () { closeModal("#add-lead-modal"); };
  window.openAddPatientModal = function () { openModal("#add-patient-modal"); };
  window.closeAddPatientModal = function () { closeModal("#add-patient-modal"); };

  // URL query parameter trigger (?add=1 or ?add=true)
  if (window.location.search.indexOf("add=1") !== -1 || window.location.search.indexOf("add=true") !== -1) {
    if (document.getElementById("add-lead-modal")) openModal("#add-lead-modal");
    if (document.getElementById("add-patient-modal")) openModal("#add-patient-modal");
  }
})();

