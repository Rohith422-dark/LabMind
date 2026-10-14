"""Persistent memory, stored in Postgres (never in the browser, never "remembered" by the model itself).

Three layers, each re-read from the database on every turn:
  conversation  recent turns verbatim + a rolling summary of older turns (conversations.summary)
  project       memories(scope='project'): terminology, established findings, notes - shared by project members
  user          memories(scope='user'): personal preferences (answer format/style) - visible to that user only

Safety rules enforced here and in the routers:
  * memory is CONTEXT, never EVIDENCE: the prompt says so and citations can only come from retrieved passages;
  * AI-written text (summaries, 'ai_suggested' memories) is labelled unverified everywhere it is shown;
  * project memory is only read after the caller's project membership was checked, and a revoked member loses it;
  * memories whose source experiment/document changed or vanished are flagged stale and left out of prompts.
"""
import logging
import re
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import ChatHistory, Conversation, Memory
from app.services import llm
from app.services.evidence import tokens

log = logging.getLogger("sla.memory")
RECENT_TURNS = 4            # verbatim turns kept in the prompt
SUMMARISE_AFTER = 6         # fold older turns into the summary once a conversation is longer than this
MAX_MEMORIES_IN_PROMPT = 6
PREFERENCE_WORDS = re.compile(r"\b(prefer|always|never|concise|brief|short|bullet|table|format|style|detailed|"
                              r"step[- ]by[- ]step|explain|units?)\b", re.I)
REMEMBER = re.compile(r"^\s*(?:please\s+)?remember(?:\s+that|:)?\s+(.{4,800})$", re.I | re.S)


def parse_remember(question: str) -> str | None:
    m = REMEMBER.match(question)
    return m.group(1).strip() if m else None


def memory_scope_for(content: str) -> tuple[str, str]:
    """('user','preference') for style requests, else ('project','note')."""
    return ("user", "preference") if PREFERENCE_WORDS.search(content) else ("project", "note")


async def relevant_memories(session: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID, question: str,
                            limit: int = MAX_MEMORIES_IN_PROMPT) -> list[Memory]:
    """Non-stale project memories (any member's) + this user's own preferences, ranked by word overlap with the question."""
    rows = (await session.execute(select(Memory).where(
        Memory.stale.is_(False),
        ((Memory.scope == "project") & (Memory.project_id == project_id))
        | ((Memory.scope == "user") & (Memory.user_id == user_id))))).scalars().all()
    q = tokens(question)
    scored = sorted(rows, key=lambda m: (m.scope == "user" and m.kind == "preference", len(q & tokens(m.content))), reverse=True)
    return [m for m in scored if m.kind == "preference" or q & tokens(m.content)][:limit]


async def conversation_context(session: AsyncSession, conv: Conversation) -> tuple[str | None, list[dict]]:
    """(summary or None, recent turns oldest-first). A stale summary is ignored until it is rebuilt."""
    rows = (await session.execute(select(ChatHistory).where(
        ChatHistory.conversation_id == conv.id, ChatHistory.user_id == conv.user_id, ChatHistory.source_type == "internal",
        ChatHistory.answer.is_not(None)).order_by(ChatHistory.created_at.desc()).limit(RECENT_TURNS))).scalars().all()
    turns: list[dict] = []
    for r in reversed(rows):
        turns += [{"role": "user", "content": r.question}, {"role": "assistant", "content": (r.answer or "")[:900]}]
    summary = None if conv.summary_stale else conv.summary
    return summary, turns


async def refresh_summary(session: AsyncSession, conv: Conversation) -> None:
    """Fold turns older than the recent window into conv.summary. Best effort: failure never breaks a chat."""
    rows = (await session.execute(select(ChatHistory).where(
        ChatHistory.conversation_id == conv.id, ChatHistory.user_id == conv.user_id, ChatHistory.source_type == "internal",
        ChatHistory.answer.is_not(None)).order_by(ChatHistory.created_at))).scalars().all()
    total = len(rows)
    old = rows[: max(0, total - RECENT_TURNS)]
    if total <= SUMMARISE_AFTER or (len(old) == conv.summary_through and not conv.summary_stale):
        return
    transcript = "\n".join(f"User: {r.question}\nAssistant: {(r.answer or '')[:500]}" for r in old)
    prompt = ("Summarise this earlier part of a lab-assistant conversation in at most 120 words. Keep terminology, "
              "decisions and open questions. Do not add facts that are not in the transcript.\n\n" + transcript)
    try:
        text = await llm.generate(prompt, tier="fast", mock=lambda: " | ".join(
            f"Q: {r.question[:80]}" for r in old[-6:]))
    except llm.LLMError as e:
        log.warning("summary skipped: %s", e)
        return
    conv.summary, conv.summary_through, conv.summary_stale = text.strip()[:2000], len(old), False


async def purge_user_project_state(session: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID) -> None:
    """Called when a member loses access: their derived summaries for the project are wiped (messages stay hidden
    behind the membership check and come back only if access is re-granted)."""
    await session.execute(update(Conversation).where(Conversation.user_id == user_id, Conversation.project_id == project_id)
                          .values(summary=None, summary_through=0, summary_stale=False, external_allowed=False))


def prompt_block(summary: str | None, memories: list[Memory]) -> str:
    parts = []
    if summary:
        parts.append("Conversation summary (AI-generated, UNVERIFIED context - never evidence):\n" + summary)
    if memories:
        parts.append("Saved memory (context only - NOT evidence, may be outdated; never cite it):\n" + "\n".join(
            f"- [{m.scope}/{m.kind}{', ai-suggested' if m.origin == 'ai_suggested' else ''}] {m.content}" for m in memories))
    return "\n\n".join(parts)
