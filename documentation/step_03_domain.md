# Step 3: Restaurant domain foundation

## Plan

1. Model the eleven SRS entities and ordering channels, keeping customers separate
   from application users and representing money with decimal fields.
2. Preserve order-line price and cost snapshots. Keep location-specific price
   history as dated events, unique per item/location/effective timestamp.
3. Reject invalid clean data with model validation and database constraints.
4. Add explicit user/location grants for both manager roles; administrators and
   analysts may read all locations. Missing grants mean no access.
5. Provide scoped location pages and an administrator-only domain management
   panel. Use migrations and PostgreSQL-backed tests before considering the step done.

## Decisions

- One deployment uses one currency (PKR initially); no currency conversion.
- Menu categories and items are shared across locations. Price events vary by location.
- A price event applies until the next event; no overlapping date intervals exist.
- Orders retain cancelled status for auditing; future analytics must exclude them
   from completed-sales KPIs. Customers can be null for anonymous orders.
- One promotion per order; campaign items are explicit many-to-many assignments.
- Order-line discounts are total currency amounts, not percentages. Line revenue
   is quantity times unit price minus discount; contribution is revenue minus cost.
- Rating is linked to a purchased order line, supporting item/location/customer joins.
- Inventory is a daily item/location snapshot in portions; consumed quantity includes
   waste. Closing stock is opening plus replenished minus consumed.
- Wastage records track prepared and wasted portions per batch with date and reason;
   cost is a historical unit-cost snapshot. Raw invalid records belong in quarantine.
- Restaurant/Regional Managers get explicit location assignments. A region entity
   and region inheritance are deferred until needed; no assignment grants global access.
- Referenced business records use protected deletion. Archiving locations/menu items
   uses availability flags. Transaction editing is limited to trusted administrators.
- `save()` validates clean records. Bulk ingestion bypasses model validation and must
   implement quality checks before bulk writes; database constraints still apply.

## Delivery boundary

The `/locations/` directory and detail pages enforce read scoping. `/management/`
provides administrator-only Django admin creation, viewing, and editing for domain
records. Historical record deletion is disabled; location grants can be revoked.
Managers have read access to their assigned locations; write workflows and dashboards
will be added with the later modules. `/admin/` remains the superuser account console.
No synthetic production dataset is generated in this step.

## Verification

- 32 PostgreSQL-backed tests passed (19 domain and 13 account tests).
- Coverage includes location access and revocation, direct management login,
  historical price selection, loss-making sales, invalid data, protected deletion,
  administrator creation, and management form rendering.
- Initial restaurant migration applied successfully; Django system checks pass.
- Template rendering is HTTP-tested. Visual browser verification is still pending.
