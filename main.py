
import os

import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from groq import Groq
import math
from fastapi import Query
import json


# ==========================================
# 1. LOAD ENVIRONMENT VARIABLES
# ==========================================

load_dotenv()

app = FastAPI(title="ServiceHub AI Backend")


# ==========================================
# 2. FIREBASE INITIALIZATION
# ==========================================

SERVICE_ACCOUNT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "serviceAccountKey.json",
)

try:
    if not firebase_admin._apps:
        firebase_cred = credentials.Certificate(
            SERVICE_ACCOUNT_FILE
        )

        firebase_admin.initialize_app(firebase_cred)

    db = firestore.client()

except Exception as error:
    print(f"Firebase initialization failed: {error}")
    raise


# ==========================================
# 3. GROQ INITIALIZATION
# ==========================================

api_key = os.getenv("GROQ_API_KEY")
model_name = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-20b",
)

client = Groq(api_key=api_key) if api_key else None


# ==========================================
# 4. REQUEST MODEL
# ==========================================

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)

class IdentifyServiceRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


# ==========================================
# 5. HOME ENDPOINT
# ==========================================

@app.get("/")
def home():
    return {
        "message": "ServiceHub AI Backend is running!"
    }


# ==========================================
# 6. HEALTH CHECK
# ==========================================

@app.get("/health")
def health_check():
    return {
        "status": "healthy"
    }


# ==========================================
# 7. FIREBASE CONNECTION TEST
# ==========================================

@app.get("/firebase-test")
def firebase_test():
    try:
        collections = list(db.collections())

        return {
            "firebase_connected": True,
            "project_id": "service-hub-26d86",
            "collections": [
                collection.id for collection in collections
            ],
        }

    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Firebase connection failed. Check Firestore setup."
        )


# ==========================================
# 8. INSPECT USER DOCUMENT FIELDS
# ==========================================

@app.get("/firebase-users-test")
def firebase_users_test():
    try:
        docs = db.collection("users").limit(5).stream()

        users = []

        for doc in docs:
            data = doc.to_dict() or {}

            users.append({
                "document_id": doc.id,
                "fields": list(data.keys()),
                "role": data.get("role"),
            })

        return {
            "collection": "users",
            "count_returned": len(users),
            "users": users,
        }

    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Could not read user documents from Firestore."
        )


# ==========================================
# 9. GROQ AI CHAT
# ==========================================

@app.post("/chat")
def chat(request: ChatRequest):
    if client is None:
        raise HTTPException(
            status_code=500,
            detail="GROQ_API_KEY is not configured."
        )

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are ServiceHub AI, a helpful local services "
                        "assistant. Ask questions to understand the user's "
                        "service needs. Never invent staff, availability, "
                        "prices, distances, or booking confirmations. "
                        "Only the backend can verify staff and bookings."
                    ),
                },
                {
                    "role": "user",
                    "content": request.message,
                },
            ],
            max_completion_tokens=500,
        )

        reply = response.choices[0].message.content

        return {
            "reply": reply or "Please try asking another question."
        }

    except Exception as error:
        # Keep technical details in the local server log only.
        print(f"Groq request failed: {type(error).__name__}")

        raise HTTPException(
            status_code=502,
            detail="The AI service is temporarily unavailable."
        )


# ==========================================
# 10. SEARCH NEARBY ONLINE STAFF
# ==========================================


@app.get("/staff/search")
def search_staff(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    service_name: str = Query(..., min_length=2, max_length=100),
    radius_km: float = Query(default=10, gt=0, le=100),
):
    try:
        staff_docs = db.collection("users").where(
            "role", "==", "staff"
        ).stream()

        results = []

        for staff_doc in staff_docs:
            staff = staff_doc.to_dict() or {}

            # Only search online staff.
            if staff.get("isOnline") is not True:
                continue

            staff_lat = staff.get("latitude")
            staff_lon = staff.get("longitude")

            if staff_lat is None or staff_lon is None:
                continue

            try:
                staff_lat = float(staff_lat)
                staff_lon = float(staff_lon)
            except (TypeError, ValueError):
                continue

            if not (
                math.isfinite(staff_lat)
                and math.isfinite(staff_lon)
                and -90 <= staff_lat <= 90
                and -180 <= staff_lon <= 180
            ):
                continue

            # Search this staff member's actual services.
            service_docs = (
                db.collection("users")
                .document(staff_doc.id)
                .collection("services")
                .stream()
            )

            matching_services = []

            for service_doc in service_docs:
                service = service_doc.to_dict() or {}
                actual_name = service.get("name", "")

                if (
                    isinstance(actual_name, str)
                    and service_name.strip().casefold()
                    in actual_name.casefold()
                ):
                    matching_services.append({
                        "service_id": service.get(
                            "id", service_doc.id
                        ),
                        "name": actual_name,
                        "description": service.get("description", ""),
                    })

            # Skip staff who don't provide the requested service.
            if not matching_services:
                continue

            # Calculate distance using the Haversine formula.
            lat1 = math.radians(latitude)
            lat2 = math.radians(staff_lat)
            delta_lat = math.radians(staff_lat - latitude)
            delta_lon = math.radians(staff_lon - longitude)

            a = (
                math.sin(delta_lat / 2) ** 2
                + math.cos(lat1) * math.cos(lat2)
                * math.sin(delta_lon / 2) ** 2
            )

            distance_km = 6371 * 2 * math.asin(
                math.sqrt(min(1.0, max(0.0, a)))
            )

            if distance_km <= radius_km:
                results.append({
                    "staff_id": staff_doc.id,
                    "name": staff.get("name", "Staff"),
                    "location_name": staff.get("locationName"),
                    "profile_image": staff.get("profileImage"),
                    "latitude": staff_lat,
                    "longitude": staff_lon,
                    "distance_km": round(distance_km, 2),
                    "services": matching_services,
                })

        results.sort(key=lambda item: item["distance_km"])

        return {
            "count": len(results),
            "service_name": service_name,
            "radius_km": radius_km,
            "staff": results,
        }

    except Exception as error:
        print(f"Staff search failed: {type(error).__name__}")

        raise HTTPException(
            status_code=500,
            detail="Unable to search for staff."
        )


# ==========================================
# AI SERVICE IDENTIFICATION
# ==========================================

@app.post("/identify-service")
def identify_service(request: IdentifyServiceRequest):
    if client is None:
        raise HTTPException(
            status_code=500,
            detail="GROQ_API_KEY is not configured."
        )

    try:
        # Step 1: Get actual service names from Firebase.
        staff_docs = (
            db.collection("users")
            .where("role", "==", "staff")
            .stream()
        )

        available_services = set()

        for staff_doc in staff_docs:
            service_docs = (
                db.collection("users")
                .document(staff_doc.id)
                .collection("services")
                .stream()
            )

            for service_doc in service_docs:
                service = service_doc.to_dict() or {}
                name = service.get("name")

                if isinstance(name, str) and name.strip():
                    available_services.add(name.strip())

        service_names = sorted(available_services)

        if not service_names:
            return {
                "reply": "No services are currently registered.",
                "service_name": None,
                "requires_confirmation": False,
            }

        # Step 2: Ask Groq to choose from real Firebase services.
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are ServiceHub AI. Identify the service "
                        "the user may need using their message. "
                        "Choose only an exact service name from the "
                        "provided available services list. Never invent "
                        "a service name. If the user's need is unclear "
                        "or no service fits, use null. "
                        "Return valid JSON only, with exactly these keys: "
                        "reply (a short helpful question or suggestion), "
                        "service_name (an exact listed name or null). "
                        "Do not claim that staff are available or that "
                        "a booking has been made."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Available services: "
                        f"{json.dumps(service_names)}\n"
                        f"User message: {request.message}"
                    ),
                },
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=300,
        )

        content = response.choices[0].message.content

        if not content:
            raise ValueError("Empty AI response")

        result = json.loads(content)

        suggested_name = result.get("service_name")

        # Step 3: Validate the AI suggestion against Firebase data.
        matched_name = next(
            (
                name for name in service_names
                if isinstance(suggested_name, str)
                and name.casefold() == suggested_name.strip().casefold()
            ),
            None,
        )

        if matched_name is None:
            return {
                "reply": result.get(
                    "reply",
                    "Could you describe the service you need?"
                ),
                "service_name": None,
                "requires_confirmation": False,
            }

        return {
            "reply": result.get(
                "reply",
                f"It sounds like you may need {matched_name}."
            ),
            "service_name": matched_name,
            "requires_confirmation": True,
        }

    except Exception as error:
        print(
            f"Service identification failed: "
            f"{type(error).__name__}"
        )

        raise HTTPException(
            status_code=502,
            detail="Unable to identify the service right now."
        )
