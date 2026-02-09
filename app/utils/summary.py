"""Shared summary builder for morning briefings and on-demand summaries."""
from app.utils.messages import MSG


def build_summary(events: list, tasks: list) -> tuple[list[str], list[str]]:
    """Build summary message and voice parts from events and tasks.
    Returns (msg_parts, voice_parts) tuple.
    """
    msg_parts = [MSG.SUMMARY_HEADER]
    voice_parts = [MSG.SUMMARY_VOICE_INTRO]

    if events:
        msg_parts.append(MSG.SUMMARY_EVENTS)
        voice_parts.append(MSG.SUMMARY_VOICE_EVENTS)
        for e in events:
            time_str = e["start"].split("T")[1][:5] if "T" in e["start"] else MSG.ALL_DAY
            msg_parts.append(f"  {e['emoji']} {time_str} - {e['title']}")
            voice_parts.append(f"{time_str} {e['title']}")
    else:
        msg_parts.append(MSG.NO_EVENTS_TODAY)
        voice_parts.append(MSG.SUMMARY_VOICE_NO_EVENTS)

    if tasks:
        msg_parts.append(MSG.SUMMARY_TASKS)
        voice_parts.append(MSG.SUMMARY_VOICE_TASKS)
        for t in tasks[:5]:
            prefix = "⚠️" if t["is_overdue"] else "☐"
            msg_parts.append(f"  {prefix} {t['title']}")
            voice_parts.append(t['title'])
    else:
        msg_parts.append(MSG.NO_TASKS_TODAY)
        voice_parts.append(MSG.SUMMARY_VOICE_NO_TASKS)

    return msg_parts, voice_parts
