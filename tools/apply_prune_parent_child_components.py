from pathlib import Path


path = Path("src/tracker/derived.py")
text = path.read_text(encoding="utf-8")
old = '''    has_value = any(item["status"] == "ok" for item in components) or any(
        item.get("status") == "ok" for item in aggregate.values()
    )
    return {
        "status": "ok" if has_value else "not_available",
        "method": "USD million × 1,000,000 divided by normalized TradeStat MEIDB quantity; verified mass units are canonicalized to KGS",
        "quantity_scale_note": "MEIDB quantity values are used directly in each displayed HS8 source unit; verified equivalent mass units are normalized before aggregation, with raw source units retained for provenance.",
        "aggregate": aggregate,
        "by_hs_code": components,
    }
'''
new = '''    has_value = any(item["status"] == "ok" for item in components) or any(
        item.get("status") == "ok" for item in aggregate.values()
    )

    # Separate parent-heading/child-HS8 mappings intentionally have no directly
    # comparable component rows. When the aggregate already carries the complete
    # validated rollup/availability provenance, serializing one synthetic
    # missing-parent row plus one missing-value row per child only duplicates
    # information and materially inflates dashboard/intelligence history payloads.
    # Keep component diagnostics for direct-HS8 mappings and for any mapping that
    # fails to produce the specialized aggregate provenance.
    commodity = (quantity_observation or {}).get("commodity", {})
    omit_parent_child_components = False
    if commodity.get("quantity_mapping_mode") == "separate" and components:
        mismatch_statuses = {"missing_usd_report", "missing_quantity_report"}
        if all(item.get("status") in mismatch_statuses for item in components):
            trade_types = {str(item.get("trade_type") or "") for item in components}
            omit_parent_child_components = bool(trade_types) and all(
                aggregate.get(trade_type, {}).get("rollup_method")
                == "parent_value_child_hs8_quantity"
                or aggregate.get(trade_type, {}).get("mapping_method")
                == "parent_value_child_hs8_separate"
                for trade_type in trade_types
            )

    return {
        "status": "ok" if has_value else "not_available",
        "method": "USD million × 1,000,000 divided by normalized TradeStat MEIDB quantity; verified mass units are canonicalized to KGS",
        "quantity_scale_note": "MEIDB quantity values are used directly in each displayed HS8 source unit; verified equivalent mass units are normalized before aggregation, with raw source units retained for provenance.",
        "aggregate": aggregate,
        "by_hs_code": [] if omit_parent_child_components else components,
    }
'''
if old not in text:
    raise SystemExit("target return block not found; derived.py changed")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
