# 🏗️ Architecture: Brain SaaS (My Second Brain)

> **Goal:** A hybrid AI Assistant leveraging Telegram for input and a Web App for management, synced with Google Workspace.
> **Cíl:** Hybridní AI asistent využívající Telegram pro vstup a webovou aplikaci pro správu, synchronizovaný s Google Workspace.

---

## 🇬🇧 English: System Overview

### 1. Layers
*   **Capture Layer:** Telegram Bot API. Handles text, voice, and images.
*   **Orchestration Layer (n8n):** Acts as the "Glue". Routes Telegram webhooks to the Python Brain and interfaces with Google APIs for standard operations.
*   **Logic Layer (Python/FastAPI):** The "Brain". Orchestrates complex intent classification, long-term memory (RAG), and OAuth2 token management.
*   **Presentation Layer (Next.js):** The "Dashboard". Provides a visual overview of tasks, calendar, and AI memories.

### 2. Data Strategy
*   **Relational (Postgres):** User profiles, subscription status, structured tasks.
*   **Vector (Qdrant):** Embeddings of all conversations and notes for context-aware assistance.
*   **Third-Party (Google):** Single source of truth for Calendar and Tasks to ensure native sync with iOS.

---

## 🇨🇿 Čeština: Přehled Systému

### 1. Vrstvy
*   **Sběrná vrstva:** Telegram Bot API. Zpracovává text, hlas a obrázky.
*   **Orchestrace (n8n):** Slouží jako "lepidlo". Směruje webhooky z Telegramu do Python "mozku" a propojuje standardní operace s Google API.
*   **Logická vrstva (Python/FastAPI):** "Mozek" systému. Řeší klasifikaci záměrů, dlouhodobou paměť (RAG) a správu OAuth2 tokenů.
*   **Prezentační vrstva (Next.js):** "Dashboard". Poskytuje vizuální přehled úkolů, kalendáře a AI vzpomínek.

### 2. Datová Strategie
*   **Relační (Postgres):** Uživatelské profily, stavy předplatného, strukturované úkoly.
*   **Vektorová (Qdrant):** Embeddingy všech konverzací a poznámek pro kontextově citlivou asistenci.
*   **Externí (Google):** Jeden zdroj pravdy pro kalendář a úkoly, čímž je zajištěna nativní synchronizace s iOS.
