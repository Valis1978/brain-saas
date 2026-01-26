from openai import AsyncOpenAI
import os
import json
from typing import Optional

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

        system_prompt = """
        Jsi inteligentní asistent. Analyzuj text a extrahuj z něj záměr a strukturovaná data.
        Vrať odpověď POUZE jako JSON v tomto formátu:
        {
            "intent": "TODO" | "EVENT" | "NOTE" | "UNKNOWN",
            "title": "Stručný název",
            "description": "Detailní popis",
            "date": "YYYY-MM-DD" | null,
            "time": "HH:MM" | null,
            "priority": "HIGH" | "MEDIUM" | "LOW"
        }
        Dnešní datum je 2026-01-26.
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
