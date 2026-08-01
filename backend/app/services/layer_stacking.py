from __future__ import annotations

from collections.abc import Iterable
from typing import Any


PIN_TOP = "pin_layer_top"
PIN_BOTTOM = "pin_layer_bottom"
FORBID_TOP = "forbid_layer_top"
ABOVE_ROLE = "above_role"
BELOW_ROLE = "below_role"


def compile_layer_stack(layers: list[dict[str, Any]]) -> list[str]:
    """Compile layer constraints into one unique bottom-to-top order.

    Layers are mutated only after the hard ordering graph is known to be
    acyclic. A successful stack uses contiguous ``z_order`` values starting at
    one; this resolved order is the only one an executor should receive.
    """

    if not layers:
        return []

    node_keys = [_node_key(layer, index) for index, layer in enumerate(layers)]
    layer_by_key = dict(zip(node_keys, layers, strict=True))
    rules_by_key = {
        key: [rule for rule in layer.get("constraint_rules") or [] if isinstance(rule, dict)]
        for key, layer in layer_by_key.items()
    }
    role_keys: dict[str, list[str]] = {}
    for key, layer in layer_by_key.items():
        roles: list[str] = []
        raw_roles = layer.get("material_roles")
        if isinstance(raw_roles, list):
            roles.extend(str(role).strip() for role in raw_roles if str(role).strip())
        scalar_role = str(layer.get("role") or layer.get("material_role") or "").strip()
        if scalar_role:
            roles.append(scalar_role)
        for role in dict.fromkeys(roles):
            role_keys.setdefault(role, []).append(key)

    hard_top: set[str] = set()
    hard_bottom: set[str] = set()
    soft_top: set[str] = set()
    soft_bottom: set[str] = set()
    hard_forbid_top: set[str] = set()
    failures: list[str] = []
    deviations: dict[str, list[dict[str, Any]]] = {key: [] for key in node_keys}
    conditional_not_applicable: dict[str, list[dict[str, Any]]] = {
        key: [] for key in node_keys
    }

    for key, rules in rules_by_key.items():
        for rule in rules:
            kind = str(rule.get("kind") or "")
            hard = bool(rule.get("hard", True))
            if kind == PIN_TOP:
                if not hard:
                    failures.append(f"constraint_layer_pin_must_be_hard:{_asset_code(layer_by_key[key])}")
                (hard_top if hard else soft_top).add(key)
            elif kind == PIN_BOTTOM:
                if not hard:
                    failures.append(f"constraint_layer_pin_must_be_hard:{_asset_code(layer_by_key[key])}")
                (hard_bottom if hard else soft_bottom).add(key)
            elif kind == FORBID_TOP:
                if not hard:
                    failures.append(f"constraint_forbid_top_must_be_hard:{_asset_code(layer_by_key[key])}")
                else:
                    hard_forbid_top.add(key)
        if key in hard_top and key in hard_bottom:
            failures.append(f"constraint_layer_pin_conflict:{_asset_code(layer_by_key[key])}")
        if key in hard_top and key in hard_forbid_top:
            failures.append(f"constraint_layer_top_forbidden_conflict:{_asset_code(layer_by_key[key])}")

    adjacency = {key: set() for key in node_keys}
    edge_hardness: dict[tuple[str, str], bool] = {}

    def add_edge(lower: str, upper: str, *, hard: bool) -> None:
        if lower == upper:
            if hard:
                failures.append(f"constraint_layer_self_relation:{_asset_code(layer_by_key[lower])}")
            return
        adjacency[lower].add(upper)
        edge_hardness[(lower, upper)] = edge_hardness.get((lower, upper), False) or hard

    # A hard pin defines a band: every bottom-pinned layer is below every
    # non-bottom layer, and every top-pinned layer is above every non-top layer.
    for bottom in hard_bottom:
        for other in node_keys:
            if other not in hard_bottom:
                add_edge(bottom, other, hard=True)
    for top in hard_top:
        for other in node_keys:
            if other not in hard_top:
                add_edge(other, top, hard=True)

    soft_edges: list[tuple[str, str, str, dict[str, Any]]] = []
    for key, rules in rules_by_key.items():
        for rule in rules:
            kind = str(rule.get("kind") or "")
            if kind not in {ABOVE_ROLE, BELOW_ROLE}:
                continue
            parameters = rule.get("parameters") if isinstance(rule.get("parameters"), dict) else {}
            target_role = str(parameters.get("role") or parameters.get("target_role") or "").strip()
            targets = [target for target in role_keys.get(target_role, []) if target != key]
            hard = bool(rule.get("hard", True))
            if not targets:
                if hard and bool(parameters.get("when_present", False)):
                    conditional_not_applicable[key].append(
                        {"kind": kind, "role": target_role}
                    )
                elif hard:
                    failures.append(
                        f"constraint_related_role_missing:{target_role or _asset_code(layer_by_key[key])}"
                    )
                else:
                    deviations[key].append(
                        {
                            "kind": kind,
                            "reason": "related_role_missing",
                            "role": target_role,
                        }
                    )
                continue
            for target in targets:
                lower, upper = (target, key) if kind == ABOVE_ROLE else (key, target)
                if hard:
                    add_edge(lower, upper, hard=True)
                else:
                    soft_edges.append((lower, upper, key, rule))

    pin_top = hard_top | soft_top
    pin_bottom = hard_bottom | soft_bottom
    if _topological_order(node_keys, adjacency, layer_by_key, pin_top, pin_bottom, hard_forbid_top) is None:
        failures.append(
            "constraint_layer_order_cycle:"
            + ",".join(sorted({_asset_code(layer_by_key[key]) for key in node_keys}))
        )
        return list(dict.fromkeys(failures))

    # Soft relations are accepted only while the hard graph stays feasible.
    for lower, upper, owner, rule in soft_edges:
        if upper in adjacency[lower]:
            continue
        adjacency[lower].add(upper)
        if _topological_order(node_keys, adjacency, layer_by_key, pin_top, pin_bottom, hard_forbid_top) is None:
            adjacency[lower].remove(upper)
            deviations[owner].append(
                {
                    "kind": str(rule.get("kind") or ""),
                    "reason": "conflicts_with_hard_layer_order",
                    "parameters": rule.get("parameters") or {},
                }
            )

    resolved = _topological_order(node_keys, adjacency, layer_by_key, pin_top, pin_bottom, hard_forbid_top)
    if resolved is None:  # pragma: no cover - guarded while adding soft edges
        return [*failures, "constraint_layer_order_internal_error"]
    if resolved[-1] in hard_forbid_top:
        failures.append(f"constraint_layer_top_forbidden:{_asset_code(layer_by_key[resolved[-1]])}")
        return list(dict.fromkeys(failures))

    for position, key in enumerate(resolved, start=1):
        layer = layer_by_key[key]
        layer["z_order"] = position
        # The blueprint pipeline uses ``z_order`` while the legacy
        # script-layout/Browser-use contract uses ``z_index``. Keep an
        # existing executor field synchronized with the authoritative order.
        if "z_index" in layer:
            layer["z_index"] = position
        evidence = layer.get("constraint_evidence")
        evidence = dict(evidence) if isinstance(evidence, dict) else {}
        evidence["stacking"] = {
            "schema_version": "layer-stacking.v1",
            "policy": "bottom_band_then_relative_dag_then_top_band",
            "stack_position": position,
            "resolved_z_order": position,
            "pin_band": (
                "top"
                if key in pin_top
                else "bottom"
                if key in pin_bottom
                else "normal"
            ),
            "forbid_layer_top": key in hard_forbid_top,
            "hard_predecessors": sorted(
                _asset_code(layer_by_key[lower])
                for lower, uppers in adjacency.items()
                if key in uppers and edge_hardness.get((lower, key), False)
            ),
            "conditional_relations_not_applicable": conditional_not_applicable[key],
            "soft_rule_deviations": deviations[key],
        }
        layer["constraint_evidence"] = evidence

    layers[:] = [layer_by_key[key] for key in resolved]
    return list(dict.fromkeys(failures))


def _topological_order(
    node_keys: list[str],
    adjacency: dict[str, set[str]],
    layer_by_key: dict[str, dict[str, Any]],
    top_keys: set[str],
    bottom_keys: set[str],
    forbid_top_keys: set[str],
) -> list[str] | None:
    indegree = {key: 0 for key in node_keys}
    for uppers in adjacency.values():
        for upper in uppers:
            indegree[upper] += 1
    available = [key for key in node_keys if indegree[key] == 0]
    result: list[str] = []
    while available:
        available.sort(
            key=lambda key: _stable_sort_key(
                key,
                layer_by_key,
                top_keys,
                bottom_keys,
                forbid_top_keys,
            )
        )
        key = available.pop(0)
        result.append(key)
        for upper in sorted(adjacency[key]):
            indegree[upper] -= 1
            if indegree[upper] == 0:
                available.append(upper)
    return result if len(result) == len(node_keys) else None


def _stable_sort_key(
    key: str,
    layer_by_key: dict[str, dict[str, Any]],
    top_keys: set[str],
    bottom_keys: set[str],
    forbid_top_keys: set[str],
) -> tuple[int, int, float, str]:
    layer = layer_by_key[key]
    band = 0 if key in bottom_keys else 2 if key in top_keys else 1
    requested_value = layer.get("z_order")
    if requested_value is None:
        requested_value = layer.get("z_index", 0)
    try:
        requested = float(requested_value)
    except (TypeError, ValueError):
        requested = 0.0
    # Within a legal band, consume non-top-capable layers first. This finds a
    # valid deterministic order whenever another unconstrained layer can be
    # placed above them; a final explicit check rejects genuinely impossible
    # stacks such as a scene containing only forbidden-top layers.
    forbid_priority = 0 if key in forbid_top_keys else 1
    return band, forbid_priority, requested, key


def _node_key(layer: dict[str, Any], index: int) -> str:
    stable = str(
        layer.get("layer_blueprint_code")
        or layer.get("layer_id")
        or layer.get("asset_code")
        or f"layer-{index + 1}"
    )
    return f"{stable}#{index}"


def _asset_code(layer: dict[str, Any]) -> str:
    return str(layer.get("asset_code") or layer.get("layer_id") or "unknown-layer")


def stack_is_contiguous(layers: Iterable[dict[str, Any]]) -> bool:
    values = [layer.get("z_order", layer.get("z_index")) for layer in layers]
    return values == list(range(1, len(values) + 1))
