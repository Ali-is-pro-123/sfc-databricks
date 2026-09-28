# DineIQ UI design-system mapping

The visual reference lives in `updated_ui_design_system/`. The Django application uses its palette, typography, imagery, and surface language while keeping Django's server-rendered routes, permissions, forms, and analytical disclosures intact. The reference HTML and JavaScript are a standalone prototype and are not application templates.

| Reference element | Production mapping | Notes |
| --- | --- | --- |
| Forest rail `#263c32` | Desktop sidebar and mobile navigation dialog | The application retains a 250px labeled sidebar rather than an 88px icon-only rail, because 13 destinations need readable names. |
| Paper `#f7f8f5`, ink `#272e29` | Workspace background and primary text | Defined as CSS tokens in `static/css/theme.css`. |
| Orange `#e95f2b` | Brand accent and active navigation marker | Interactive orange is darkened to `#c94e21` so small white button text meets AA contrast. |
| Forest `#263c32`, ink `#272e29`, line `#eaede6` | Navigation, content headings, borders, tables | Forest remains in navigation; content headings use ink, while eyebrows and links use orange. Forecast blue and warning amber retain their distinct analytical meaning. |
| Kitchen / Editorial fonts | Local Geometric Book, Geometric Demi, Editorial Roman | Fonts and the original license notice are copied to `static/assets/`; fonts have system fallbacks. |
| Rounded white cards | Existing dashboard sections, forms, and tables | Scoped CSS updates the shared surface treatment. |
| Restaurant photograph | Welcome and sign-in panels | Labeled representative photography; it is not evidence about a location or menu item. |
| Brand bowl | Shared desktop, drawer, and public header | Decorative SVG alongside a readable wordmark. |

## Implementation boundaries

- `templates/base.html` loads Tailwind CDN, then the scoped theme and navigation stylesheets. The design system does not replace Tailwind utility-based layouts.
- `templates/includes/navigation.html` retains every route and role gate. The drawer still uses the existing accessible dialog JavaScript.
- `templates/accounts/login.html` retains CSRF, Django form errors, and the `next` redirect field.
- Content templates use semantic `text-accent`, `theme-action`, and `interactive-card` classes rather than old Tailwind emerald utilities. This prevents green hover/focus states from returning when Tailwind CDN styles load.
- The sign-in photograph keeps its heading, eyebrow, and disclosure above the image overlay with light text for contrast.
- Account form focus and standalone downloadable reports also use the orange/neutral palette. Offline reports keep inline styles so they render without the web app or a CDN.
- The prototype's search, simulated data, JavaScript views, and login behavior are not imported, since they do not use the Django application APIs or permissions.
- Original files in `updated_ui_design_system/` remain untouched for comparison. The application copies only the assets it uses.

## Validation checklist

1. `uv run python dine_iq/manage.py check`: no issues.
2. `uv run python dine_iq/manage.py test apps.accounts apps.restaurants`: 89 passed after the palette cleanup. The full repository discovery additionally finds Spark tests that require PySpark in Docker; this Windows Python environment does not have it.
3. `node --test tests/test_navigation.js`: three drawer behavior tests passed, including native dialog, fallback, Escape, resize, and focus restoration.
4. In-app browser visual review: anonymous sign-in plus authenticated welcome, executive dashboard, and reports rendered at a 920px viewport. Sign-in photo heading resolved to white; content eyebrows, report links, and report-card hover border resolved to orange; content headings resolved to ink. No `emerald` classes remained on those pages. Browser click control did not reliably execute ordinary link navigation, so direct click-through in that browser remains unverified.
5. Brand SVG, photograph, and all three font files returned HTTP 200 from the running Django development server.

Before release, manually inspect a desktop width of at least 1024px and a narrow phone width, including long navigation labels, focus visibility, and wide tables.
