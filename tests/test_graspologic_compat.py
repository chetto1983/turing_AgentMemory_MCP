from __future__ import annotations

from importlib.metadata import version


def test_graspologic_compat_version_is_pinned() -> None:
    assert version("graspologic-native") == "1.3.1"


def test_graspologic_compat_hierarchical_leiden_smoke() -> None:
    from graspologic_native import hierarchical_leiden

    edges = [("a", "b", 1.0), ("b", "c", 1.0)]
    records = hierarchical_leiden(
        edges,
        resolution=1.0,
        randomness=0.001,
        iterations=2,
        max_cluster_size=100,
        seed=42,
    )

    finals = [record for record in records if bool(record.is_final_cluster)]
    assert finals, "hierarchical_leiden returned no final-cluster records"

    assigned_nodes = {str(record.node) for record in finals}
    assert assigned_nodes == {"a", "b", "c"}
