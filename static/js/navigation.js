const navigationDrawer = document.getElementById('navigation-drawer');
const openNavigation = document.getElementById('open-navigation');
const closeNavigation = document.getElementById('close-navigation');

if (navigationDrawer && openNavigation && closeNavigation) {
  const supportsModalDialog = typeof navigationDrawer.showModal === 'function';
  const isMenuOpen = () => navigationDrawer.hasAttribute('open');

  const resetNavigation = () => {
    openNavigation.setAttribute('aria-expanded', 'false');
    document.body.classList.remove('navigation-open');
    if (openNavigation.offsetParent !== null) openNavigation.focus();
  };

  const closeMenu = () => {
    if (supportsModalDialog) {
      navigationDrawer.close();
    } else {
      navigationDrawer.removeAttribute('open');
      resetNavigation();
    }
  };

  openNavigation.addEventListener('click', () => {
    if (supportsModalDialog) navigationDrawer.showModal();
    else navigationDrawer.setAttribute('open', '');
    openNavigation.setAttribute('aria-expanded', 'true');
    document.body.classList.add('navigation-open');
    closeNavigation.focus();
  });
  closeNavigation.addEventListener('click', closeMenu);
  navigationDrawer.addEventListener('click', (event) => {
    // Only a click outside the drawer closes the backdrop.
    const bounds = navigationDrawer.getBoundingClientRect();
    if (event.target === navigationDrawer && (event.clientX > bounds.right || event.clientX < bounds.left)) closeMenu();
  });
  navigationDrawer.addEventListener('close', resetNavigation);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !supportsModalDialog && isMenuOpen()) closeMenu();
  });
  // Close the mobile modal when a tablet rotates to desktop width.
  window.matchMedia('(min-width: 1024px)').addEventListener('change', (event) => {
    if (event.matches && isMenuOpen()) closeMenu();
  });
}
