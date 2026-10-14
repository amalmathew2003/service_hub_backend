# 🛠️ ServiceHub AI — Backend

<p align="center">
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Firebase-FFCA28?style=for-the-badge&logo=firebase&logoColor=black" />
  <img src="https://img.shields.io/badge/Groq_AI-FF4F00?style=for-the-badge&logo=openai&logoColor=white" />
</p>

<p align="center">
  The AI-powered backend for <strong>ServiceHub</strong> — a local services marketplace that connects users with nearby on-demand service providers using real-time location and conversational AI.
</p>

---

## 📖 About

**ServiceHub** is a Flutter-based mobile application that allows users to discover and book local service professionals (plumbers, electricians, cleaners, etc.) nearby. This repository contains the **Python/FastAPI backend** that powers the AI features and serves as the bridge between the Flutter frontend and Firebase Firestore.

### What this backend does:
- 🤖 **AI Chat** — Conversational AI assistant (via Groq) that helps users describe what service they need
- 🧠 **Service Identification** — AI identifies the exact service from the user's natural language input and matches it against real services registered in Firestore
- 📍 **Geo-based Staff Search** — Finds nearby online staff using the Haversine formula, filtered by service type and radius
- 🔥 **Firebase Integration** — Reads real-time user/staff data from Cloud Firestore

---

## 🏗️ Architecture

```
Flutter App (service_hub_ai)
        │
        ▼
FastAPI Backend (this repo)
        │
        ├──► Groq AI API  (LLM for chat & service identification)
        │
        └──► Firebase Firestore  (user, staff & services data)
```

---

## 🚀 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Health check — confirms the server is running |
| `GET` | `/health` | Returns `{ "status": "healthy" }` |
| `GET` | `/firebase-test` | Tests Firestore connectivity & lists collections |
| `GET` | `/firebase-users-test` | Inspects the first 5 user documents |
| `POST` | `/chat` | Sends a message to the AI assistant |
| `POST` | `/identify-service` | AI identifies a service from natural language |
| `GET` | `/staff/search` | Finds nearby online staff by service & location |

### `POST /chat`
Send a free-text message and get a helpful AI response.
```json
// Request
{ "message": "I need someone to fix my sink" }

// Response
{ "reply": "I can help! Are you looking for a plumber?" }
```

### `POST /identify-service`
AI maps the user's message to an exact registered service name from Firestore.
```json
// Request
{ "message": "my pipe is leaking badly" }

// Response
{
  "reply": "It sounds like you may need Plumbing Repair.",
  "service_name": "Plumbing Repair",
  "requires_confirmation": true
}
```

### `GET /staff/search`
Finds online staff within a radius who offer the requested service.
```
/staff/search?latitude=10.0&longitude=76.3&service_name=Plumbing&radius_km=10
```
```json
{
  "count": 2,
  "service_name": "Plumbing",
  "radius_km": 10,
  "staff": [
    {
      "staff_id": "uid_abc",
      "name": "Raju Kumar",
      "location_name": "Ernakulam",
      "profile_image": "https://...",
      "latitude": 10.01,
      "longitude": 76.31,
      "distance_km": 1.43,
      "services": [
        { "service_id": "s1", "name": "Plumbing Repair", "description": "Pipe fixes" }
      ]
    }
  ]
}
```

---

## ⚙️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | [FastAPI](https://fastapi.tiangolo.com/) |
| Language | Python 3.10+ |
| AI / LLM | [Groq API](https://groq.com/) |
| Database | [Firebase Firestore](https://firebase.google.com/docs/firestore) |
| Auth / Admin | Firebase Admin SDK |
| Env Config | `python-dotenv` |

---

## 🗂️ Project Structure

```
servicehub_backend/
├── main.py                  # All FastAPI routes and business logic
├── serviceAccountKey.json   # Firebase service account (⚠️ keep secret)
├── .env                     # Environment variables (⚠️ keep secret)
├── .gitignore
└── venv/                    # Python virtual environment
```

---

## 🛠️ Local Setup

### Prerequisites
- Python 3.10+
- A Firebase project with Firestore enabled
- A [Groq API key](https://console.groq.com/)

### 1. Clone the repository
```bash
git clone https://github.com/amalmathew2003/service_hub_backend.git
cd service_hub_backend
```

### 2. Create and activate a virtual environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python -m venv venv
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install fastapi uvicorn firebase-admin groq python-dotenv
```

### 4. Configure environment variables
Create a `.env` file in the project root:
```env
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=openai/gpt-oss-20b
```

### 5. Add Firebase credentials
Place your Firebase service account JSON file as `serviceAccountKey.json` in the project root.
> Download it from: Firebase Console → Project Settings → Service Accounts → Generate New Private Key

### 6. Run the server
```bash
uvicorn main:app --reload
```

The API will be available at `http://127.0.0.1:8000`

### 7. Explore the interactive docs
FastAPI provides automatic interactive documentation:
- **Swagger UI** → http://127.0.0.1:8000/docs
- **ReDoc** → http://127.0.0.1:8000/redoc

---

## 🔐 Firestore Data Schema

The backend expects users to be stored in the `users` collection with the following fields:

### Staff Document (`users/{uid}`)
| Field | Type | Description |
|-------|------|-------------|
| `role` | `string` | Must be `"staff"` |
| `name` | `string` | Display name |
| `isOnline` | `boolean` | Whether the staff is currently active |
| `latitude` | `number` | Current latitude |
| `longitude` | `number` | Current longitude |
| `locationName` | `string` | Human-readable location (e.g. "Ernakulam") |
| `profileImage` | `string` | URL of the profile photo |

### Services Sub-collection (`users/{uid}/services/{serviceId}`)
| Field | Type | Description |
|-------|------|-------------|
| `id` | `string` | Service ID |
| `name` | `string` | Service name (e.g. "Plumbing Repair") |
| `description` | `string` | Short description |

---

## 🌐 Related Repository

| Repository | Description |
|------------|-------------|
| [`service_hub_ai`](https://github.com/amalmathew2003/service_hub_ai) | Flutter frontend — mobile app for users and staff |

---

## 🔒 Security Notes

> **⚠️ Important:** Never commit `serviceAccountKey.json` or `.env` to version control. Both files are already included in `.gitignore`.

- All sensitive credentials are loaded from environment variables via `python-dotenv`
- The Firebase Admin SDK is initialized once at startup to avoid re-authentication overhead
- AI responses are validated against live Firestore data before being returned to the client — the AI cannot fabricate service names or staff

---

## 📄 License

This project is open-source and available under the [MIT License](LICENSE).

---

<p align="center">Built with ❤️ by <a href="https://github.com/amalmathew2003">Amal Mathew</a></p>
