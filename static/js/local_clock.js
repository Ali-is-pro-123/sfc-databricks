const localClock = document.getElementById('current-local-datetime');

if (localClock) {
  const dateText = document.getElementById('current-local-date');
  const timeText = document.getElementById('current-local-time');
  const dateFormat = new Intl.DateTimeFormat('en-PK', {
    day: '2-digit', month: 'short', year: 'numeric',
  });
  const timeFormat = new Intl.DateTimeFormat('en-PK', {
    hour: 'numeric', minute: '2-digit', hour12: true,
  });

  function updateLocalClock() {
    // The browser clock reflects the visitor's timezone; it is not the analytics data period.
    const now = new Date();
    localClock.dateTime = now.toISOString();
    dateText.textContent = dateFormat.format(now);
    timeText.textContent = timeFormat.format(now);
  }

  updateLocalClock();
  window.setInterval(updateLocalClock, 30000);
  window.addEventListener('pageshow', updateLocalClock);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) updateLocalClock();
  });
}
