from openai import AsyncOpenAI
import os
import json
from typing import Optional
from datetime import datetime

class AIService:
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.client = None
        if self.api_key:
            self.client = AsyncOpenAI(api_key=self.api_key)

    async def transcribe_voice(self, file_path: str) -> str:
        """Transcribes an audio file using OpenAI Whisper."""
        if not self.client:
            return "OpenAI client not initialized."
            
        with open(file_path, "rb") as audio_file:
            transcript = await self.client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file
            )
            return transcript.text

    async def extract_intent(self, text: str) -> dict:
        """Uses GPT-4o to extract intent and entities from text."""
        if not self.client:
            return {"error": "API key missing"}

        # Get current date dynamically
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        system_prompt = f"""
        Jsi inteligentní osobní asistent "Vlastikův druhý mozek". Analyzuj text a extrahuj záměr.
        
        Vrať odpověď POUZE jako JSON v tomto formátu:
        {{
            "intent": "TODO" | "EVENT" | "NOTE" | "QUERY_CALENDAR" | "QUERY_TASKS" | "UPDATE_EVENT" | "DELETE_EVENT" | "COMPLETE_TASK" | "SUMMARY" | "UNKNOWN",
            "title": "Stručný název (pro vytváření)",
            "description": "Detailní popis",
            "date": "YYYY-MM-DD" | null,
            "time": "HH:MM" | null,
            "priority": "HIGH" | "MEDIUM" | "LOW",
            "category": "work" | "personal",
            "query_type": "today" | "tomorrow" | "week" | "overdue" | "specific" | null,
            "target_event": "název události k úpravě/smazání" | null,
            "new_date": "YYYY-MM-DD pro přesun" | null,
            "new_time": "HH:MM pro změnu času" | null,
            "target_calendar": "work" | "personal" | null
        }}
        
        INTENTY:
        - TODO = vytvořit úkol ("připomeň mi", "musím", "nezapomenout")
        - EVENT = vytvořit událost v kalendáři ("schůzka", "meeting", "v kolik hodin")
        - NOTE = poznámka bez data/času
        - QUERY_CALENDAR = dotaz na kalendář ("co mám na dnešek?", "co mám zítra?", "jaký mám program?")
        - QUERY_TASKS = dotaz na úkoly ("co jsem nesplnil?", "jaké mám úkoly?", "co mám udělat?")
        - UPDATE_EVENT = změna existující události ("přesuň schůzku", "změň čas", "přehoď do pracovního")
        - DELETE_EVENT = zrušení události ("zruš schůzku", "odvolej meeting")
        - COMPLETE_TASK = označení úkolu jako hotového ("hotovo", "splněno", "úkol dokončen")
        - SUMMARY = shrnutí dne ("jaký mám dnešek?", "co mě čeká?", "přehled dne")
        
        PRAVIDLA PRO QUERY_TYPE:
        - "today" = dnešní události/úkoly
        - "tomorrow" = zítřejší  
        - "week" = tento týden
        - "overdue" = prošlé/nesplněné úkoly
        - "specific" = konkrétní datum
        
        KALENDÁŘE (target_calendar):
        - "work" = pracovní kalendář (Práce)
        - "personal" = osobní kalendář (Osobní)
        
        PŘÍKLADY:
        - "Co mám na dnešek?" → intent: QUERY_CALENDAR, query_type: today
        - "Co jsem nesplnil?" → intent: QUERY_TASKS, query_type: overdue
        - "Přesuň schůzku s Janíkem na zítra" → intent: UPDATE_EVENT, target_event: "Janík", new_date: (zítřejší datum)
        - "Přesuň schůzku s Janíkem do pracovního" → intent: UPDATE_EVENT, target_event: "Janík", target_calendar: "work"
        - "Přehoď Janíka do osobního kalendáře" → intent: UPDATE_EVENT, target_event: "Janík", target_calendar: "personal"
        - "Zruš meeting s klientem" → intent: DELETE_EVENT, target_event: "meeting s klientem"
        - "Schůzka s Janíkem zítra v 10" → intent: EVENT, category: work
        - "Narozeniny tchýně v sobotu" → intent: EVENT, category: personal
        
        Dnešní datum je {current_date}.
        """

        response = await self.client.chat.completions.create(
            model="gpt-5.1-chat-latest",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            response_format={"type": "json_object"}
        )

        return json.loads(response.choices[0].message.content)

ai_service = AIService()
