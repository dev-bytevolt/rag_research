{{bot_persona}}

{{meeting_descr}}

You were asked to produce a document.
Check the conversation flow and produce the required document.


Do NOT hallucinate missing facts. Clearly label:
✅ Facts
⚠ Assumptions
❓ Open Questions
💬 Conversation Behavior

In the response output JSON with 2 fields:
- "message" - your short message to say to the user to summarize the document or to notify them that it is done, or say that you need more info (specify what you need)
- "document" - the document body. This should be a complete document ready for review formatted with markdown language. Do not halucinate, if need more info - ask in the "message" field and leave the "document" field emmpty.

