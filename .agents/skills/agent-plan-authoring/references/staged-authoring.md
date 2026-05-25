# Staged Authoring

Read this reference when creating or repairing a managed authoring bundle.

## Required Order

1. Edit `entity-inventory.yaml`, then run `--validate-entity-inventory`.
2. Edit `operation-inventory.yaml`, then run `--validate-operation-inventory`.
3. Run `--sync-authoring-plan`.
4. Edit authored cases in `authoring-plan.yaml`, then run `--validate-authoring-plan`.
5. Run `--validate-authoring-bundle`.

Each gate needs explicit `Status: PASS` or JSON `status=PASS`. Empty stdout is unknown readiness, not success.

## Entity Inventory

Record entities, id fields, key fields, normalized fields, states, allowed transitions, and shared auth/header contracts.

Keep real entity identities. If an entity is naturally keyed, keep the real `id_field` and model the natural identity with `key_fields`; do not replace `id_field` with a convenient fixture variable.

## Operation Inventory

Record reusable setup operations, executable routes or SQL, request data, expected status, captures, route contracts, lifecycle semantics, and DB verification templates.

Important fields:

- `captures` in the form `response.json.<field> -> <variable>`
- `method_evidence` for action-like routes
- `runtime_path_evidence` for final external paths after `API_BASE_URL`
- `target_state`, `precondition_state`, and same-state lifecycle contracts when relevant
- DB verification `sql`, `params`, `scoped_by`, `expected_outcomes`, and `column_types`

If a later case needs a DB check, define the reusable verification here instead of improvising in the case.

## Sync And Case Authoring

After inventories validate, sync the authoring plan. The sync step hydrates scope, entities, reusable operations, routes, and DB verification templates; it does not invent final cases.

If sync output has `route: null`, empty SQL, empty expected outcomes, or inferred capture placeholders, the previous inventory is incomplete. Fix the inventory and sync again.

Do not manually patch synced route/setup/DB template sections in `authoring-plan.yaml`. Fix the source inventory first, then rerun sync.

## Repair Loop

When an earlier inventory changes after sync:

1. Validate that inventory.
2. Rerun `--sync-authoring-plan`.
3. Revalidate `authoring-plan.yaml`.
4. Revalidate the full bundle.

Do not edit all three staged files in one pass. Move forward one gate at a time.
