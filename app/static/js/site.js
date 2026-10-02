// Public site: mobile nav toggle (kept external so CSP can use script-src 'self').
(function () {
  var btn = document.getElementById("menu-burger");
  var menu = document.getElementById("menu");
  if (btn && menu) {
    btn.addEventListener("click", function () {
      menu.classList.toggle("open");
    });
  }
})();
