document.getElementById('search').addEventListener('input', function () { /* autocomplete */ });// Mobile menu toggle
(function () {
  const toggle = document.querySelector('.menu-toggle');
  const menu = document.getElementById('primary-menu');
  if (!toggle || !menu) return;

  toggle.addEventListener('click', () => {
    const isOpen = menu.classList.toggle('open');
    toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    // Optional: lock body scroll when menu open
    document.body.style.overflow = isOpen ? 'hidden' : '';
  });

  // Close the menu if a link is tapped (nice for mobile)
  menu.addEventListener('click', (e) => {
    if (e.target.tagName.toLowerCase() === 'a') {
      menu.classList.remove('open');
      toggle.setAttribute('aria-expanded', 'false');
      document.body.style.overflow = '';
    }
  });
})();
