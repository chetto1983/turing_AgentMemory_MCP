from __future__ import annotations

from dataclasses import replace

from turing_agentmemory_mcp.memory_extraction import (
    Classification,
    EntityMention,
    MemoryExtraction,
    RelationMention,
)
from turing_agentmemory_mcp.temporal_graph import (
    EpisodeContext,
    normalize_date_expression,
    plan_temporal_projection,
)


def extraction_with_relations() -> MemoryExtraction:
    caroline = EntityMention("Caroline", "person", 0.99, 0, 8)
    group = EntityMention("LGBTQ support group", "organization", 0.96, 20, 39)
    date = EntityMention("7 May 2023", "date", 0.94, 43, 53)
    return MemoryExtraction(
        entities=(caroline, group, date),
        relations=(
            RelationMention("participated_in", caroline, group, 0.93),
            RelationMention("occurred_on", group, date, 0.91),
        ),
        memory_kind=Classification("episodic_event", 0.88),
        model="lion-ai/gliner2-base-v1-onnx",
        device="cuda",
        schema_version="memory-v1",
    )


def episode(**overrides: object) -> EpisodeContext:
    values: dict[str, object] = {
        "user_identifier": "alice",
        "memory_id": "mem-1",
        "content": "Caroline joined the LGBTQ support group on 7 May 2023.",
        "session_id": "session-1",
        "role": "user",
        "observed_at": "2026-07-10T10:15:30Z",
        "source": "locomo",
        "tags": ("benchmark",),
        "metadata": {"conversation_id": "conv-1"},
        "expires_at": "2027-01-01T00:00:00Z",
    }
    values.update(overrides)
    return EpisodeContext(**values)  # type: ignore[arg-type]


def test_projection_is_deterministic_and_preserves_fact_provenance() -> None:
    context = episode()
    extraction = extraction_with_relations()

    first = plan_temporal_projection(context, extraction)
    second = plan_temporal_projection(context, extraction)

    assert first == second
    assert len(first.entities) == 3
    assert len(first.facts) == 2
    assert len(first.mentions) == 3
    participated = next(fact for fact in first.facts if fact.predicate == "participated_in")
    assert participated.source_memory_id == "mem-1"
    assert participated.user_identifier == "alice"
    assert participated.session_id == "session-1"
    assert participated.speaker == "user"
    assert participated.source == "locomo"
    assert participated.tags == ("benchmark",)
    assert participated.metadata == {"conversation_id": "conv-1"}
    assert participated.observed_at == "2026-07-10T10:15:30Z"
    assert participated.schema_version == "memory-v1"
    assert participated.model == "lion-ai/gliner2-base-v1-onnx"
    assert participated.confidence == 0.93
    assert participated.expires_at == "2027-01-01T00:00:00Z"
    assert participated.valid_from == ""
    assert participated.valid_to == ""


def test_projection_normalizes_explicit_relation_date_without_inventing_validity() -> None:
    projection = plan_temporal_projection(episode(), extraction_with_relations())

    dated = next(fact for fact in projection.facts if fact.predicate == "occurred_on")
    undated = next(fact for fact in projection.facts if fact.predicate == "participated_in")

    assert dated.valid_from == "2023-05-07"
    assert dated.valid_time_precision == "day"
    assert dated.valid_to == ""
    assert undated.valid_from == ""
    assert undated.valid_time_precision == ""


def test_entity_canonicalization_merges_mentions_but_preserves_each_span() -> None:
    upper = EntityMention("Caroline", "person", 0.91, 0, 8)
    lower = EntityMention("caroline", "person", 0.83, 13, 21)
    extraction = replace(extraction_with_relations(), entities=(upper, lower), relations=())
    context = episode(content="Caroline met caroline.")

    projection = plan_temporal_projection(context, extraction)

    assert len(projection.entities) == 1
    assert projection.entities[0].canonical_name == "caroline"
    assert projection.entities[0].display_name == "Caroline"
    assert projection.entities[0].confidence == 0.91
    assert [(mention.start, mention.end) for mention in projection.mentions] == [(0, 8), (13, 21)]
    assert {mention.entity_id for mention in projection.mentions} == {projection.entities[0].id}


def test_entity_canonicalization_keeps_highest_confidence_display_evidence() -> None:
    upper = EntityMention("CAROLINE", "person", 0.71, 0, 8)
    title = EntityMention("Caroline", "person", 0.94, 13, 21)
    extraction = replace(extraction_with_relations(), entities=(upper, title), relations=())

    projection = plan_temporal_projection(
        episode(content="CAROLINE met Caroline."),
        extraction,
    )

    assert projection.entities[0].display_name == "Caroline"
    assert projection.entities[0].content == "Caroline (person)"
    assert projection.entities[0].confidence == 0.94


def test_entity_and_fact_ids_are_tenant_and_source_scoped() -> None:
    extraction = extraction_with_relations()
    alice = plan_temporal_projection(episode(), extraction)
    alice_second_source = plan_temporal_projection(episode(memory_id="mem-2"), extraction)
    bob = plan_temporal_projection(episode(user_identifier="bob"), extraction)

    assert [entity.id for entity in alice.entities] == [
        entity.id for entity in alice_second_source.entities
    ]
    assert {fact.id for fact in alice.facts}.isdisjoint(
        {fact.id for fact in alice_second_source.facts}
    )
    assert {entity.id for entity in alice.entities}.isdisjoint(
        {entity.id for entity in bob.entities}
    )
    assert {fact.id for fact in alice.facts}.isdisjoint({fact.id for fact in bob.facts})


def test_projection_edges_link_episode_entities_facts_and_typed_relation() -> None:
    projection = plan_temporal_projection(episode(), extraction_with_relations())
    relation_fact = next(fact for fact in projection.facts if fact.predicate == "participated_in")

    edge_kinds = [edge.kind for edge in projection.edges]
    assert edge_kinds.count("MENTIONS") == 3
    assert edge_kinds.count("SUPPORTED_BY") == 2
    assert edge_kinds.count("SUBJECT_OF") == 2
    assert edge_kinds.count("OBJECT_OF") == 2
    assert "PARTICIPATED_IN" in edge_kinds
    assert any(
        edge.source_id == relation_fact.id
        and edge.target_id == "mem-1"
        and edge.kind == "SUPPORTED_BY"
        for edge in projection.edges
    )


def test_projection_with_entities_only_does_not_fabricate_facts() -> None:
    extraction = replace(extraction_with_relations(), relations=())

    projection = plan_temporal_projection(episode(), extraction)

    assert projection.facts == ()
    assert all(edge.kind == "MENTIONS" for edge in projection.edges)


def test_projection_deduplicates_semantic_relations_at_highest_confidence() -> None:
    extraction = extraction_with_relations()
    relation = extraction.relations[0]
    duplicate = RelationMention(
        relation.relation,
        relation.subject,
        relation.object,
        0.99,
    )
    extraction = replace(
        extraction,
        relations=(relation, duplicate, extraction.relations[1]),
    )

    projection = plan_temporal_projection(episode(), extraction)

    participated = [fact for fact in projection.facts if fact.predicate == "participated_in"]
    assert len(participated) == 1
    assert participated[0].confidence == 0.99
    related_edges = [
        edge for edge in projection.edges if edge.properties.get("fact_id") == participated[0].id
    ]
    assert len(related_edges) == 4
    assert {edge.properties["confidence"] for edge in related_edges} == {0.99}


def test_normalize_date_expression_reports_precision_and_rejects_relative_dates() -> None:
    assert normalize_date_expression("2023-05-07") == ("2023-05-07", "day")
    assert normalize_date_expression("May 7, 2023") == ("2023-05-07", "day")
    assert normalize_date_expression("May 2023") == ("2023-05", "month")
    assert normalize_date_expression("2023") == ("2023", "year")
    assert normalize_date_expression("yesterday") == ("", "")
