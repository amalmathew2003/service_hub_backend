# 🛠️ ServiceHub AI — Backend Engine

<p align="center">
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Python_3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/Firebase_Admin-FFCA28?style=for-the-badge&logo=firebase&logoColor=black" alt="Firebase Admin" />
  <img src="https://img.shields.io/badge/Firebase_FCM-FFA000?style=for-the-badge&logo=firebase&logoColor=white" alt="FCM" />
  <img src="https://img.shields.io/badge/Groq_Cloud-FF4F00?style=for-the-badge&logo=openai&logoColor=white" alt="Groq AI" />
  <img src="https://img.shields.io/badge/Pydantic_v2-E92063?style=for-the-badge&logo=pydantic&logoColor=white" alt="Pydantic v2" />
</p>

<p align="center">
  <strong>Production-grade, AI-driven microservice backend powering the on-demand local services ecosystem.</strong><br />
  Coordinates real-time geospatial discovery, conversational intent extraction with Groq LLMs, idempotent customer bookings, and instant cross-platform push notifications via Firebase Cloud Messaging (FCM).
</p>

---

## 📑 Table of Contents

- [Overview](#-overview)
- [System Architecture](#-system-architecture)
- [Key Features](#-key-features)
- [API Reference](#-api-reference)
  - [Authentication & Security](#authentication--security)
  - [AI & Natural Language Processing](#1-ai--natural-language-processing)
  - [Geospatial Staff Search](#2-geospatial-staff-search)
  - [Staff Catalog Suggestions](#3-staff-catalog-suggestions)
  - [Customer Bookings & Push Dispatch](#4-customer-bookings--push-dispatch)
  - [FCM Testing & Diagnostics](#5-fcm-testing--diagnostics)
  - [Custom Service Requests](#6-custom-service-requests)
  - [Health & Connectivity](#7-health--connectivity)
- [Database Architecture & Firestore Schemas](#-database-architecture--firestore-schemas)
- [Project Structure](#-project-structure)
- [Installation & Quickstart](#-installation--quickstart)
- [Environment Variables](#-environment-variables)
- [Related Repositories](#-related-repositories)
- [License](#-license)

---

## 🌟 Overview

**ServiceHub** bridges customers seeking immediate on-demand assistance (plumbers, electricians, cleaners, mechanics, etc.) with verified local service professionals.

This backend serves as the intelligent orchestration layer between the **Flutter Mobile Client** (`service_hub_ai`), **Firebase Cloud Firestore**, **Firebase Authentication**, **Firebase Cloud Messaging (FCM)**, and ultra-low-latency **Groq LPU Inference**.

### Why This Backend Exists
1. **Intelligent Intent Recognition:** Converts ambiguous user prompts (e.g., *"water is leaking from my ceiling"*) into exact, verified service catalog entries stored in Firestore.
2. **Geospatial Discovery:** Computes precise Haversine distance vectors across active, online providers within custom radius constraints.
3. **Secure Transaction Lifecycle:** Validates Firebase ID tokens, prevents role escalation (staff booking staff), and creates bookings atomically with built-in idempotency keys.
4. **Instant Event Dispatch:** Dispatches high-priority push notifications to staff mobile devices via FCM with custom payloads for immediate interaction.

---

## 🏗️ System Architecture

```
                  ┌──────────────────────────────────────────────┐
                  │          Flutter Client Application          │
                  │        (Customer & Provider Interfaces)      │
                  └───────┬──────────────────────────────▲───────┘
                          │                              │
             HTTPS REST   │ Bearer ID Token              │ High-Priority
             Requests     │                              │ Push (FCM)
                          ▼                              │
             ┌───────────────────────────────────────────┴──────────┐
             │            FastAPI Backend Microservice             │
             │                                                      │
             │  • Auth Token Verification   • Haversine Geo Search  │
             │  • Request Sanitization      • Idempotency Engine    │
             │  • Pydantic v2 Models        • Prompt Engineering    │
             └──────┬──────────────────────┬─────────────────┬──────┘
                    │                      │                 │
       Fast LPU     │         Admin SDK    │      Admin SDK  │
       Inference    │         Transactions │      Push API   │
                    ▼                      ▼                 ▼
          ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
          │   Groq Cloud     │   │ Firebase Cloud   │   │ Firebase Cloud   │
          │   (LLM Engine)   │   │    Firestore     │   │ Messaging (FCM)  │
          └──────────────────┘   └──────────────────┘   └──────────────────┘
```

---

## ✨ Key Features

- **Conversational AI Assistant (`/chat`):** Provides contextual customer support to guide users toward the right category of service.
- **Service Intent Matching (`/identify-service`):** Matches natural language descriptions against real-time Firestore service collections using Groq with algorithmic fallback logic.
- **Provider Suggestion Engine (`/staff/service-suggestions`):** Dynamically suggests relevant service offerings (e.g., HVAC/AC maintenance packages) to staff during onboarding.
- **Haversine Geo-Filtering (`/staff/search`):** Real-time spatial query returning distance in kilometers, provider ratings, availability (`isOnline: true`), and offered services.
- **Secure Idempotent Booking Flow (`/bookings`):** Verifies customer identity via Firebase Auth, confirms provider service validity, locks booking against double-submission, and triggers staff notifications.
- **FCM Device Notification Delivery (`/notifications/test`):** End-to-end device token validation with support for Android high-priority channels and Apple APNS sound payloads.
- **Unregistered Service Registry (`/service-requests`):** Captures unmet service demands to help expand platform offerings.

---

## 📡 API Reference

Interactive documentation is automatically generated by FastAPI:
- **Swagger UI:** `http://127.0.0.1:8000/docs`
- **ReDoc:** `http://127.0.0.1:8000/redoc`

### Authentication & Security

Protected endpoints require a Firebase ID token passed in the `Authorization` header:

```http
Authorization: Bearer <FIREBASE_ID_TOKEN>
```

The server decodes and cryptographically verifies the token using `firebase_admin.auth.verify_id_token(token, check_revoked=True)`.

---

### 1. AI & Natural Language Processing

#### `POST /chat`
General conversational endpoint to answer user questions and recommend local services.

- **Request Body:**
  ```json
  {
    "message": "My kitchen tap is dripping continuously. Who can fix it?"
  }
  ```
- **Response (`200 OK`):**
  ```json
  {
    "reply": "It looks like you have a plumbing leak. I recommend booking a certified Plumber to replace the washer or repair the pipe valve."
  }
  ```

---

#### `POST /identify-service`
Maps unstructured natural language to an exact service name currently registered in Firestore.

- **Request Body:**
  ```json
  {
    "message": "I need my split air conditioner cleaned and serviced before summer."
  }
  ```
- **Response (`200 OK`):**
  ```json
  {
    "reply": "I found a matching service: AC Cleaning. Would you like to proceed?",
    "service_name": "AC Cleaning",
    "requires_confirmation": false
  }
  ```

---

### 2. Geospatial Staff Search

#### `GET /staff/search`
Queries online service providers within a geographic radius who offer the requested service.

- **Query Parameters:**
  | Parameter | Type | Required | Description |
  |-----------|------|----------|-------------|
  | `latitude` | `float` | Yes | Customer's latitude (e.g. `9.9312`) |
  | `longitude` | `float` | Yes | Customer's longitude (e.g. `76.2673`) |
  | `service_name`| `string` | No | Target service filter (e.g. `Plumbing`) |
  | `radius_km` | `float` | No | Search radius in kilometers (Default: `15.0`) |

- **Sample Request:**
  ```http
  GET /staff/search?latitude=9.9816&longitude=76.2999&service_name=AC%20Cleaning&radius_km=10
  ```

- **Response (`200 OK`):**
  ```json
  {
    "count": 1,
    "service_name": "AC Cleaning",
    "radius_km": 10.0,
    "staff": [
      {
        "staff_id": "u4JkL992aP",
        "name": "Alex Thomas",
        "location_name": "Kaloor, Kochi",
        "profile_image": "https://storage.googleapis.com/...",
        "latitude": 9.9890,
        "longitude": 76.3050,
        "distance_km": 0.98,
        "services": [
          {
            "service_id": "srv_ac_01",
            "name": "AC Cleaning",
            "description": "Deep chemical foam washing and coil cleaning"
          }
        ]
      }
    ]
  }
  ```

---

### 3. Staff Catalog Suggestions

#### `POST /staff/service-suggestions`
Assists service providers during onboarding by generating standardized service catalog recommendations based on keyword input.

- **Request Body:**
  ```json
  {
    "service_text": "air conditioner"
  }
  ```
- **Response (`200 OK`):**
  ```json
  {
    "query": "air conditioner",
    "source": "groq",
    "suggestions": [
      "AC Mechanic",
      "AC Cleaning",
      "AC Installation",
      "AC Gas Refilling",
      "AC Water Leakage Repair"
    ]
  }
  ```

---

### 4. Customer Bookings & Push Dispatch

#### `POST /bookings`
Creates an atomic booking record in Firestore and immediately dispatches a push notification to the assigned staff member.

- **Headers:** `Authorization: Bearer <CUSTOMER_FIREBASE_ID_TOKEN>`
- **Request Body:**
  ```json
  {
    "id": "book_981240182",
    "staffId": "staff_uid_456",
    "serviceId": "srv_plumb_01",
    "scheduledDate": "2026-10-25T10:30:00Z",
    "staffLatitude": 9.9890,
    "staffLongitude": 76.3050
  }
  ```

- **Response (`201 Created`):**
  ```json
  {
    "success": true,
    "bookingId": "book_981240182",
    "notificationSent": true,
    "alreadyCreated": false,
    "message": "Booking created successfully."
  }
  ```

- **Idempotency Guarantee:** If the network disconnects and the mobile client retries with the same `id`, the backend recognizes the existing record, avoids duplicate booking creation, and returns `alreadyCreated: true`.

---

### 5. FCM Testing & Diagnostics

#### `POST /notifications/test`
Validates FCM push delivery to the authenticated staff member's registered device.

- **Headers:** `Authorization: Bearer <STAFF_FIREBASE_ID_TOKEN>`
- **Response (`200 OK`):**
  ```json
  {
    "success": true,
    "messageId": "projects/servicehub/messages/0:1697...",
    "message": "Firebase accepted the test notification for delivery."
  }
  ```

---

### 6. Custom Service Requests

#### `POST /service-requests`
Enables customers to request services that are not yet listed on the platform.

- **Request Body:**
  ```json
  {
    "requested_service": "Solar Panel Pressure Washing",
    "description": "Need rooftop solar panels cleaned of moss and dust"
  }
  ```
- **Response (`201 Created`):**
  ```json
  {
    "success": true,
    "request_id": "req_88a9df21",
    "requested_service": "Solar Panel Pressure Washing",
    "status": "pending",
    "message": "Thank you for your suggestion! We've recorded your request for future review."
  }
  ```

---

### 7. Health & Connectivity

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Root status message |
| `GET` | `/health` | Liveness probe returning `{"status": "healthy"}` |
| `GET` | `/firebase-test` | Verifies Firestore connectivity and lists root collections |
| `GET` | `/firebase-users-test` | Diagnostic inspection of the first 5 records in `users` |

---

## 🗄️ Database Architecture & Firestore Schemas

```
Firestore Root
├── users/ (Collection)
│   └── {userId} (Document)
│       ├── role: "customer" | "staff"
│       ├── name: string
│       ├── email: string
│       ├── fcmToken: string
│       ├── isOnline: boolean (staff only)
│       ├── latitude: number
│       ├── longitude: number
│       ├── locationName: string
│       └── services/ (Sub-collection - staff only)
│           └── {serviceId} (Document)
│               ├── id: string
│               ├── name: string
│               └── description: string
│
├── bookings/ (Collection)
│   └── {bookingId} (Document)
│       ├── id: string
│       ├── customerId: string
│       ├── staffId: string
│       ├── serviceId: string
│       ├── serviceName: string
│       ├── customerName: string
│       ├── staffName: string
│       ├── status: "pending" | "accepted" | "in_progress" | "completed" | "cancelled"
│       ├── scheduledDate: timestamp | null
│       ├── customerLatitude: number
│       ├── customerLongitude: number
│       ├── staffLatitude: number
│       ├── staffLongitude: number
│       ├── notificationSent: boolean
│       ├── createdAt: server_timestamp
│       └── updatedAt: server_timestamp
│
└── service_requests/ (Collection)
    └── {requestId} (Document)
        ├── requested_service: string
        ├── description: string
        ├── status: "pending"
        └── created_at: server_timestamp
```

---

## 📁 Project Structure

```
servicehub_backend/
├── main_updated.py          # Complete production FastAPI application
├── main.py                  # Core backend routes
├── serviceAccountKey.json   # Firebase Admin credentials (⚠️ NEVER commit)
├── .env                     # Secrets & environment config (⚠️ NEVER commit)
├── .gitignore               # Ignored files, virtual environments, and keys
└── README.md                # Project documentation & integration guide
```

---

## 🚀 Installation & Quickstart

### Prerequisites
- **Python 3.10 or higher**
- A **Firebase Project** with Cloud Firestore, Firebase Authentication, and Cloud Messaging enabled.
- A **Groq Cloud API Key** from [console.groq.com](https://console.groq.com/).

### 1. Clone & Navigate
```bash
git clone https://github.com/amalmathew2003/service_hub_backend.git
cd service_hub_backend
```

### 2. Create Virtual Environment
```bash
# Windows (PowerShell)
python -m venv venv
.\venv\Scripts\Activate.ps1

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install fastapi "uvicorn[standard]" firebase-admin groq python-dotenv pydantic
```

### 4. Setup Credentials
1. **Firebase Admin Key:**
   - Download the service account private key from **Firebase Console > Project Settings > Service Accounts**.
   - Save it as `serviceAccountKey.json` in the project root directory.

2. **Environment Variables:**
   - Create a `.env` file in the root directory:
   ```env
   GROQ_API_KEY=gsk_your_groq_api_key_here
   GROQ_MODEL=openai/gpt-oss-20b
   ```

### 5. Launch the Server

Run the production application with auto-reloading:

```bash
uvicorn main_updated:app --reload --host 0.0.0.0 --port 8000
```

> **Note:** If testing with physical mobile devices or emulators on the local network, use your local machine's LAN IP address (e.g. `http://192.168.1.X:8000`).

---

## 🔐 Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | **Yes** | — | Secret API key for Groq LLM inference |
| `GROQ_MODEL` | No | `openai/gpt-oss-20b` | Model identifier on Groq Cloud |

---

## 📱 Related Repositories

| Repository | Tech Stack | Role |
|---|---|---|
| [**service_hub_ai**](https://github.com/amalmathew2003/service_hub_ai) | Flutter (Dart), Firebase | Cross-platform mobile app for customers and providers |

---

## 🛡️ Security Best Practices

- **Token Auditing:** Always verify Firebase tokens server-side; never rely on user IDs passed in the request body.
- **Role Verification:** Staff users are prevented from creating customer bookings to prevent malicious state manipulation.
- **Fail-Safe FCM:** FCM delivery failures are logged and recorded on the booking document (`notificationSent: false`), preventing client retries from duplicating bookings.
- **Secret Protection:** `serviceAccountKey.json` and `.env` are strictly excluded via `.gitignore`.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).

<p align="center">
  Built with ❤️ by <a href="https://github.com/amalmathew2003">Amal Mathew</a>
</p>
