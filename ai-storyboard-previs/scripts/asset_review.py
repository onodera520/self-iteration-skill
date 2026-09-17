"""Validate imported-video asset evidence, not the truth of visual descriptions."""


ASPECT_CHECK = {"wardrobe": "identity", "appearance": "identity", "prop": "props", "scene": "scene"}


def validate_asset_evidence(p, project_path, review, context):
    from previs import require, resolve

    def strings(value):
        return isinstance(value, list) and all(isinstance(x, str) and x.strip() for x in value)

    def text(value):
        return isinstance(value, str) and bool(value.strip())

    assets = {a["id"]: a for a in context["assets"]}
    shots = {s["id"]: s for s in p["shots"] if s["id"] in review["coverage"]["shot_ids"]}
    rows = {s["shot_id"]: s for s in review["shot_reviews"]}
    evidence = review["evidence"]
    for e in evidence:
        require(strings(e.get("visible_facts")) and e["visible_facts"] and text(e.get("interpretation")),
                "frame needs neutral visible_facts and separate interpretation; observation alone is insufficient")

    comparisons = review.get("asset_comparisons")
    require(isinstance(comparisons, list), "group asset_comparisons required")
    by_id, by_key = {}, {}
    for c in comparisons:
        cid, sid, aid, aspect = (c.get(k) for k in ("id", "shot_id", "asset_id", "aspect"))
        require(text(cid) and cid not in by_id, "unique asset comparison id required")
        require(sid in shots and aid in shots[sid]["asset_ids"] and aid in assets,
                "comparison must reference a current asset assigned to this shot")
        require(aspect in ASPECT_CHECK, "unknown comparison aspect")
        expected_kind = "character" if aspect in ("wardrobe", "appearance") else aspect
        require(assets[aid]["kind"] == expected_kind, "comparison aspect must match asset kind")
        require((sid, aid, aspect) not in by_key, "one comparison per shot/asset/aspect")
        require(rows[sid]["verdict"] != "absent", "absent shot cannot claim an asset comparison")
        decision = c.get("decision")
        require(decision in ("PASS", "FAIL", "uncertain"), "invalid asset decision")
        if aspect in ("wardrobe", "appearance"):
            require(text(c.get("story_requirement")), "character comparison needs a concrete story_requirement or explicit strict requirement")
            if decision != "PASS":
                require(text(c.get("story_impact")), "character FAIL/uncertain needs concrete story_impact")
        require(c.get("asset_sha256") == assets[aid]["sha256"], "asset comparison hash mismatch")
        refs = c.get("evidence_refs")
        require(isinstance(refs, list), "asset evidence_refs required")
        for ref in refs:
            require(isinstance(ref, dict) and any(e["shot_id"] == sid and
                resolve(project_path, e["path"]) == resolve(project_path, ref.get("path", "")) and
                e["sha256"] == ref.get("sha256") and e["time"] == ref.get("time") and
                e["time"] in rows[sid].get("evidence_times", []) for e in evidence),
                "asset evidence must bind same-shot frame, hash and exact time")
        for field in ("condition_factors", "stable_matches", "unobservable_features", "basis_shot_ids"):
            require(strings(c.get(field)), "asset comparison needs " + field)
        conflicts = c.get("stable_conflicts")
        require(isinstance(conflicts, list) and all(isinstance(x, dict) and
            all(text(x.get(k)) for k in ("feature", "expected", "observed", "environment_exclusion")) for x in conflicts),
            "structural conflicts need feature, expected, observed and environment_exclusion")
        require(isinstance(c.get("followup"), str), "asset followup field required")
        if decision in ("PASS", "FAIL"):
            require(refs and assets[aid]["sha256"] != "MISSING", "asset PASS/FAIL needs current asset and local timed evidence")
        if decision == "PASS":
            require(c["stable_matches"] and not conflicts and not c["unobservable_features"],
                    "asset PASS needs stable matches without conflicts or necessary invisible features")
        elif decision == "FAIL":
            require(conflicts, "asset FAIL needs stable_conflicts; environmental appearance alone cannot fail")
        else:
            require(c["unobservable_features"] and text(c["followup"]) and not conflicts,
                    "asset uncertain needs invisible necessary features and concrete followup, without confirmed conflict")
        by_id[cid], by_key[sid, aid, aspect] = c, c

    for sid, row in rows.items():
        require(text(row.get("identity_reason")), "per-shot identity_reason required")
        if row["verdict"] == "absent":
            continue
        decisions = [c["decision"] for c in comparisons if c["shot_id"] == sid and
                     ASPECT_CHECK[c["aspect"]] == "identity"]
        expected = "FAIL" if "FAIL" in decisions else "uncertain" if "uncertain" in decisions else "PASS"
        require(row["checks"]["identity"] == expected, "identity check contradicts per-aspect asset comparisons")
        if expected == "PASS":
            characters = [assets[aid] for aid in shots[sid]["asset_ids"] if assets[aid]["kind"] == "character"]
            require(all(a["sha256"] != "MISSING" for a in characters), "identity PASS needs current asset")
            require(not characters or any(e["shot_id"] == sid and e["time"] in row.get("evidence_times", []) for e in evidence),
                    "identity PASS needs same-shot visible facts and timed evidence")
        # Other asset aspects cannot hide a conflict under a different check.
        for check in ("props", "scene"):
            ds = [c["decision"] for c in comparisons if c["shot_id"] == sid and ASPECT_CHECK[c["aspect"]] == check]
            if "FAIL" in ds:
                require(row["checks"][check] == "FAIL", "asset conflict must fail its applicable check")
            elif "uncertain" in ds:
                require(row["checks"][check] != "PASS", "uncertain asset cannot pass its applicable check")

    for c in comparisons:
        for basis in c["basis_shot_ids"]:
            require(basis != c["shot_id"] and basis in rows and any(other["shot_id"] == basis and
                other["asset_id"] == c["asset_id"] and other["aspect"] == c["aspect"] and
                other["decision"] == "PASS" and not other["basis_shot_ids"] for other in comparisons),
                "interpretation basis needs independently visible matching asset structure; no circular or borrowed FAIL")

    for issue in review["issues"]:
        aids, refs = issue.get("asset_ids"), issue.get("asset_comparison_ids")
        require(strings(aids) and strings(refs), "issue must declare asset_ids and asset_comparison_ids, even when empty")
        require(all(cid in by_id for cid in refs), "unknown issue asset comparison")
        linked = [by_id[cid] for cid in refs]
        require(all(c["shot_id"] in issue["shot_ids"] and c["asset_id"] in aids and c["decision"] == "FAIL" for c in linked),
                "issue comparison must be a localized asset FAIL")
        for sid in issue["shot_ids"]:
            for aid in aids:
                require(any(c["shot_id"] == sid and c["asset_id"] == aid for c in linked),
                        "multi-shot asset issue needs comparison evidence for every shot and asset")
        require(all(issue["time_range"][0] <= ref["time"] <= issue["time_range"][1] for c in linked for ref in c["evidence_refs"]),
                "asset issue time range must cover its comparison evidence")
    for c in comparisons:
        if c["decision"] == "FAIL":
            require(any(c["id"] in issue["asset_comparison_ids"] for issue in review["issues"]),
                    "asset FAIL needs corresponding localized issue")
