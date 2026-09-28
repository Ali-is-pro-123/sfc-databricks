# DineIQ UI design system

The application uses one shared Django shell (`templates/base.html`) and one role-aware navigation partial (`templates/includes/navigation.html`). Page content stays in individual templates. Visual tokens and shared surfaces live in `static/css/theme.css`; responsive navigation lives in `static/css/navigation.css`.

## Visual foundations

| Purpose | Token / treatment |
| --- | --- |
| Forest brand and primary text | `--forest: #173e34`; `--ink: #19352e` |
| Business accent and active navigation | `--orange: #e78121` with a pale amber background |
| Warm canvas | `--paper: #f8f7f3` |
| Card and table separators | `--line: #e9e7df` |
| Forecast evidence | Soft blue, visually separate from historical actuals |
| Positive evidence | Muted green; warning evidence uses amber |

Use Kitchen for readable UI text and Editorial for large headings. Keep cards white with subtle borders, restrained shadows and medium corner radii. Icons come from the line-icon sprite at `static/assets/icons.svg`.

The supplied full-color logo is stored at `static/assets/dineiq-logo.png` and rendered through `templates/includes/brand_logo.html`. Its transparent source canvas includes generous padding, so `.brand-logo` in `navigation.css` crops it visually without altering the original image. The small square SVG remains the favicon.

## Behavior and integrity

- Keep the sidebar and header consistent across roles; only show Administration links to users allowed to manage accounts.
- The header search submits the existing `item` filter on Analytics search. The header location link opens the scoped location list.
- The historical date in the header is an evidence label, not an editable date selector. Do not style it as a functioning control until a genuinely filterable data flow exists.
- Dashboard trends, rankings and insights must be derived from verified, access-scoped data. Do not use example numbers, invented percentage changes or simulated live updates.
- Compact KPI values should retain exact values in a title or nearby detail; tables and exports retain full precision.
- Forecast estimates need an explicit estimate label and must not be styled as observed results.

## Responsive and accessible usage

At desktop widths the sidebar stays fixed; narrower layouts use the existing keyboard-accessible navigation dialog. Keep visible focus outlines, semantic headings, descriptive chart labels, and horizontal overflow on data tables rather than the whole page. Honor reduced-motion preferences.

## Not yet implemented

The reference concept also proposes notifications, account settings, editable date/location filters, upload-processing status and password recovery. These require product workflows and backend state that this visual pass does not invent. Add each only alongside its real behavior and role-specific tests.
