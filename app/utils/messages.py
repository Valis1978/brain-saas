"""
Centralized Czech message strings for Brain SaaS.

Usage:
    from app.utils.messages import MSG
    
    response = MSG.EVENT_CREATED.format(category="Práce", title="Meeting")
"""


class Messages:
    """All user-facing Czech messages."""
    
    # ==================== CREATE SUCCESS ====================
    EVENT_CREATED = "{emoji} Přidáno do kalendáře **{category}**!\n\n**{title}**\n🔗 {link}"
    TASK_CREATED = "✅ Úkol přidán do Google Tasks!\n\n**{title}**"
    NOTE_SAVED = "📝 Poznámka uložena!\n\n**{title}**"
    NOTE_SAVED_LOCAL = "📝 Poznámka zachycena: **{title}**\n(Nebyla synchronizována do dashboardu)"
    NOTE_FALLBACK = "📝 Poznámka zachycena: **{title}**"
    
    # ==================== QUERY LABELS ====================
    CALENDAR_TODAY = "📅 Dnešek"
    CALENDAR_TOMORROW = "📅 Zítřek"
    CALENDAR_WEEK = "📅 Tento týden"
    CALENDAR_EVENTS = "📅 Události"
    NO_EVENTS = "📅 Nemáš žádné nadcházející události."
    NO_EVENTS_TODAY = "📅 Žádné události na dnešek"
    
    # ==================== TASKS ====================
    TASKS_HEADER = "📋 Úkoly ({count}"
    TASKS_OVERDUE = ", ⚠️ {count} prošlých"
    NO_TASKS = "✅ Nemáš žádné nesplněné úkoly!"
    NO_TASKS_TODAY = "\n✅ Žádné nesplněné úkoly"
    
    # ==================== SUMMARY ====================
    SUMMARY_HEADER = "📊 **Přehled dne:**\n"
    SUMMARY_EVENTS = "📅 **Události:**"
    SUMMARY_TASKS = "\n📋 **Úkoly:**"
    SUMMARY_VOICE_INTRO = "Přehled tvého dne:"
    SUMMARY_VOICE_EVENTS = "Události:"
    SUMMARY_VOICE_TASKS = "Úkoly:"
    SUMMARY_VOICE_NO_EVENTS = "Nemáš žádné události na dnešek."
    SUMMARY_VOICE_NO_TASKS = "Nemáš žádné nesplněné úkoly."
    
    # ==================== UPDATE SUCCESS ====================
    EVENT_MOVED_CALENDAR = "{emoji} Událost **{title}** přesunuta do kalendáře **{calendar}**!"
    EVENT_UPDATED = "✅ Událost **{title}** přesunuta!"
    EVENT_NEW_DATE = "\n📅 Nové datum: {date}"
    EVENT_NEW_TIME = "\n⏰ Nový čas: {time}"
    
    # ==================== DELETE SUCCESS ====================
    EVENT_DELETED = "🗑️ Událost **{title}** zrušena!"
    
    # ==================== SEARCH RESULTS ====================
    MULTIPLE_EVENTS_FOUND = "🔍 Nalezeno {count} událostí:\n{list}\n\nUpřesni prosím kterou myslíš."
    MULTIPLE_EVENTS_DELETE = "🔍 Nalezeno {count} událostí:\n{list}\n\nUpřesni prosím kterou zrušit."
    EVENT_NOT_FOUND = "❌ Nenašel jsem událost obsahující '{query}'"
    
    # ==================== PROCESSING FEEDBACK ====================
    VOICE_TRANSCRIBED = "🎤 Přepsáno: {text}\n\n🤖 Zpracováno jako: {intent}"
    TEXT_SAVED = "✅ Zapsáno: {title}"
    
    # ==================== CATEGORY LABELS ====================
    CATEGORY_WORK = "Práce"
    CATEGORY_PERSONAL = "Osobní"
    
    # ==================== TIME LABELS ====================
    ALL_DAY = "Celý den"


# Singleton instance for easy import
MSG = Messages()
