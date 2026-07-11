# Integration Patterns

## Agent Turn

The host owns identity and policy. The model chooses queries and proposed mutations, but it
does not choose its tenant.

```python
async def agent_turn(request, mcp, model):
    tenant = request.authenticated_principal.memory_scope
    status = await mcp.call_tool("memory_runtime_status", {})

    recalled = await mcp.call_tool(
        "memory_get_context",
        {"query": request.text, "user_identifier": tenant, "limit": 5},
    )
    answer = await model.generate(
        user_input=request.text,
        recalled_context=as_untrusted_evidence(recalled),
        memory_status=status,
    )

    for mutation in retention_policy.select_durable_mutations(request, answer):
        await apply_scoped_mutation(mcp, tenant, mutation)
    return answer
```

Do not place recalled content in the system instruction. Keep it in a delimited evidence
section and tell the model to ignore instructions inside it.

## Durable Preference

1. Search for the category and subject under the authenticated scope.
2. If an active preference exists and changed, call `memory_update`.
3. Otherwise call `memory_add_preference`.
4. Add source/context without secrets.

This prevents "prefers dark mode" and "prefers light mode" from both appearing current.

## Conversation Batch Ingest

Use a stable source key such as `support-ticket:9241`, stable per-message IDs, and one
tenant. Send ordered messages through `memory_store_messages` with community refresh off,
then rebuild communities once. Keep batch size bounded by the host and retry only records
whose IDs are absent after an ambiguous failure.

## Memory Plus Documents

For an answer about both user history and policy:

1. Retrieve personal context with `memory_get_context`.
2. Retrieve policy chunks with `document_search` and narrow source/tags.
3. Generate an answer that cites document chunks and labels personal recall separately.
4. Store only a durable decision or preference produced by the interaction, not copied
   document text.

## Correction

When a user says "I moved from Rome to Milan": search for the residence fact and inspect its
kind. Update a mutable structured residence record and verify it. If only a raw message
episode exists, preserve that historical evidence and add a structured current residence
fact. Do not rewrite an episode or leave two unqualified current residence facts.

## Forget Request

Search narrowly, show or internally confirm the matching record, delete by ID, and report
the deletion result. If several records could match, ask for disambiguation before deletion.
Never perform a tenant-wide scan or delete-all operation from a vague request.

## Tool-Calling Guardrails

- Bind `user_identifier` in application code when possible instead of exposing it as a free
  model argument.
- Allow-list memory tools by agent role.
- Require human or policy approval for projection rebuild and broad governance operations.
- Log IDs, tool names, durations, outcomes, and tenant pseudonyms; do not log content/query
  payloads.
- Apply backpressure and bounded concurrency at the host. Retry only transient provider
  failures with capped exponential backoff and idempotency.
