import os
import re
import json
import math
import traceback

import firebase_admin
from firebase_admin import credentials, firestore, auth as firebase_auth, messaging
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Header
from pydantic import BaseModel, Field, ConfigDict
from groq import Groq


# =====================================================
# 1. ENVIRONMENT AND INITIALIZATION
# =====================================================

load_dotenv()

app = FastAPI(title="ServiceHub AI Backend")

SERVICE_ACCOUNT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "serviceAccountKey.json",
)

if not firebase_admin._apps:
    firebase_cred = credentials.Certificate(SERVICE_ACCOUNT_FILE)
    firebase_admin.initialize_app(firebase_cred)

db = firestore.client()

api_key = os.getenv("GROQ_API_KEY")
model_name = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
client = Groq(api_key=api_key) if api_key else None


# =====================================================
# 2. REQUEST MODELS
# =====================================================

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class IdentifyServiceRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ServiceRequestCreate(BaseModel):
    requested_service: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=1000)


class ServiceSuggestionRequest(BaseModel):
    service_text: str = Field(min_length=1, max_length=150)


class BookingCreateRequest(BaseModel):
    """Booking fields accepted from the Flutter customer app.

    The authenticated Firebase UID is used as customerId; a client-supplied
    customerId/customerName is deliberately not trusted.
    """
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    booking_id: str = Field(alias="id", min_length=1, max_length=150)
    staff_id: str = Field(alias="staffId", min_length=1, max_length=150)
    service_id: str = Field(alias="serviceId", min_length=1, max_length=150)
    scheduled_date: str | None = Field(default=None, alias="scheduledDate")
    staff_latitude: float | None = Field(default=None, alias="staffLatitude")
    staff_longitude: float | None = Field(default=None, alias="staffLongitude")


# =====================================================
# 3. TEXT HELPERS
# =====================================================

def normalize_text(value: str) -> str:
    value = value.casefold().strip()
    value = re.sub(r"[^\w\s]", " ", value)
    return re.sub(r"\s+", " ", value)


def get_service_by_exact_name(
    suggested_name: str,
    service_names: list[str],
) -> str | None:
    if not isinstance(suggested_name, str):
        return None

    normalized = normalize_text(suggested_name)

    for name in service_names:
        if normalize_text(name) == normalized:
            return name

    return None


# =====================================================
# 4. SERVICE SUGGESTIONS FOR STAFF
# =====================================================

# These are suggestions, NOT automatically registered services.
# Staff must select the services they actually provide.

AC_SERVICE_SUGGESTIONS = [
    "AC Mechanic",
    "AC Cleaning",
    "AC Washing",
    "AC Installation",
    "AC Gas Refilling",
    "AC Repair",
    "AC Maintenance",
    "AC Uninstallation",
    "AC Not Cooling Diagnosis",
    "AC Water Leakage Repair",
]


def get_fallback_suggestions(service_text: str) -> list[str]:
    normalized = normalize_text(service_text)

    if any(
        word in normalized.split()
        for word in ["ac", "air", "conditioner", "conditioning"]
    ):
        return AC_SERVICE_SUGGESTIONS.copy()

    # Generic fallback: suggest the entered service and common
    # related tasks without claiming that they are registered.
    cleaned = service_text.strip()
    return [
        cleaned,
        f"{cleaned} Repair",
        f"{cleaned} Cleaning",
        f"{cleaned} Maintenance",
    ]


@app.post("/staff/service-suggestions")
def suggest_staff_services(request: ServiceSuggestionRequest):
    """
    Suggest possible services while staff are adding their services.

    Suggestions are not saved to Firestore. The Flutter app must
    let staff select the services they actually provide and save
    each selected service to users/{staffId}/services/{serviceId}.
    """
    service_text = request.service_text.strip()

    if not service_text:
        raise HTTPException(
            status_code=422,
            detail="Please enter a service category.",
        )

    # Use the reliable local AC suggestions even if Groq is down.
    if any(
        word in normalize_text(service_text).split()
        for word in ["ac", "air", "conditioner", "conditioning"]
    ):
        return {
            "query": service_text,
            "suggestions": AC_SERVICE_SUGGESTIONS,
            "source": "catalog",
        }

    if client is None:
        return {
            "query": service_text,
            "suggestions": get_fallback_suggestions(service_text),
            "source": "fallback",
        }

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": """
You help service providers list the services they offer.

Generate up to 8 concise, distinct service names related to
the category entered by the staff member.

Rules:
- Return JSON with one key: suggestions.
- suggestions must be an array of strings.
- Do not include explanations.
- Do not include prices, availability, or marketing text.
- Do not claim that a suggestion has been registered.
- Do not suggest unrelated services.
- Include the entered service category when appropriate.
""",
                },
                {
                    "role": "user",
                    "content": service_text,
                },
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=300,
        )

        content = response.choices[0].message.content
        data = json.loads(content or "{}")
        raw_suggestions = data.get("suggestions", [])

        if not isinstance(raw_suggestions, list):
            raise ValueError("Invalid suggestions format")

        suggestions = []
        seen = set()

        for item in raw_suggestions:
            if not isinstance(item, str):
                continue

            item = item.strip()

            if not item or len(item) > 100:
                continue

            normalized = normalize_text(item)

            if normalized not in seen:
                suggestions.append(item)
                seen.add(normalized)

            if len(suggestions) == 8:
                break

        if not suggestions:
            suggestions = get_fallback_suggestions(service_text)

        return {
            "query": service_text,
            "suggestions": suggestions,
            "source": "ai",
        }

    except Exception:
        traceback.print_exc()

        return {
            "query": service_text,
            "suggestions": get_fallback_suggestions(service_text),
            "source": "fallback",
        }


# =====================================================
# 5. HOME AND HEALTH
# =====================================================

@app.get("/")
def home():
    return {"message": "ServiceHub AI Backend is running!"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}


# =====================================================
# 5A. CUSTOMER BOOKING CREATION + STAFF PUSH NOTIFICATION
# =====================================================


def get_authenticated_firebase_user(authorization: str | None) -> dict:
    """Verify the Firebase ID token supplied by the Flutter app."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Firebase Bearer token.")

    id_token = authorization.split(" ", 1)[1].strip()
    if not id_token:
        raise HTTPException(status_code=401, detail="Missing Firebase ID token.")

    try:
        return firebase_auth.verify_id_token(id_token, check_revoked=True)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired Firebase ID token.")


@app.post("/notifications/test")
def send_test_notification(
    authorization: str | None = Header(
        default=None,
        alias="Authorization",
        description="Enter: Bearer followed by your Firebase ID token",
    ),
):
    """Send a test push notification to the authenticated staff device."""

    # 1. Verify Firebase ID token
    decoded_token = get_authenticated_firebase_user(authorization)

    staff_id = decoded_token.get("uid")
    if not staff_id:
        raise HTTPException(
            status_code=401,
            detail="Firebase token has no user ID.",
        )

    # 2. Find the staff profile
    staff_ref = db.collection("users").document(staff_id)
    staff_snapshot = staff_ref.get()

    if not staff_snapshot.exists:
        raise HTTPException(
            status_code=404,
            detail="Staff profile was not found.",
        )

    staff = staff_snapshot.to_dict() or {}

    # 3. Confirm the account is a staff account
    if staff.get("role") != "staff":
        raise HTTPException(
            status_code=403,
            detail="Only staff accounts can send a test notification.",
        )

    # 4. Get the registered FCM device token
    fcm_token = staff.get("fcmToken")

    if not isinstance(fcm_token, str) or not fcm_token.strip():
        raise HTTPException(
            status_code=409,
            detail=(
                "No FCM token is saved for this staff account. " 
                "Sign in on the staff app and register its FCM token first."
            ),
        )

    # 5. Send the test notification
    try:
        message = messaging.Message(
            token=fcm_token,
            notification=messaging.Notification(
                title="ServiceHub test notification",
                body="FCM is reaching your staff device.",
            ),
            data={
                "type": "test_notification",
                "staffId": staff_id,
            },
            android=messaging.AndroidConfig(
                priority="high",
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound="default"),
                ),
            ),
        )

        message_id = messaging.send(message)

        print(
            f"Test FCM sent to staff {staff_id}; "
            f"message_id={message_id}",
            flush=True,
        )

        return {
            "success": True,
            "messageId": message_id,
            "message": (
                "Firebase accepted the test notification for delivery."
            ),
        }

    except Exception as error:
        print(
            f"Test FCM failed for staff {staff_id}: "
            f"{type(error).__name__}: {error}",
            flush=True,
        )

        raise HTTPException(
            status_code=502,
            detail=(
                "Firebase could not send the test notification. "
                "Check the backend terminal for the FCM error."
            ),
        ) from error


@app.post("/bookings", status_code=201)
def create_booking(
    request: BookingCreateRequest,
    authorization: str | None = Header(default=None),
):
    """Create one booking and notify the selected staff member via FCM.

    The client booking ID is an idempotency key: retries won't create a
    second booking. A notification failure does not undo a saved booking.
    """
    decoded_token = get_authenticated_firebase_user(authorization)
    customer_id = decoded_token.get("uid")
    if not customer_id:
        raise HTTPException(status_code=401, detail="Firebase token has no user ID.")

    try:
        customer_ref = db.collection("users").document(customer_id)
        staff_ref = db.collection("users").document(request.staff_id)
        customer_snapshot = customer_ref.get()
        staff_snapshot = staff_ref.get()

        if not customer_snapshot.exists:
            raise HTTPException(status_code=404, detail="Customer profile was not found.")
        if not staff_snapshot.exists:
            raise HTTPException(status_code=404, detail="Selected staff member was not found.")

        customer = customer_snapshot.to_dict() or {}
        staff = staff_snapshot.to_dict() or {}
        if staff.get("role") != "staff":
            raise HTTPException(status_code=400, detail="Selected account is not a staff member.")
        if customer.get("role") == "staff":
            raise HTTPException(status_code=403, detail="Staff accounts cannot create customer bookings.")

        service_ref = staff_ref.collection("services").document(request.service_id)
        service_snapshot = service_ref.get()
        if not service_snapshot.exists:
            # Some service records store a custom id field, so allow a lookup
            # by the saved id if the document ID itself differs.
            matching_service = None
            for service_doc in staff_ref.collection("services").stream():
                service_data = service_doc.to_dict() or {}
                if str(service_data.get("id", "")) == request.service_id:
                    matching_service = (service_doc, service_data)
                    break
            if matching_service is None:
                raise HTTPException(status_code=404, detail="Selected service was not found for this staff member.")
            service_doc, service = matching_service
            service_id = service_doc.id
        else:
            service = service_snapshot.to_dict() or {}
            service_id = service_snapshot.id

        service_name = service.get("name")
        if not isinstance(service_name, str) or not service_name.strip():
            raise HTTPException(status_code=400, detail="Selected service has no valid name.")

        scheduled_date = None
        if request.scheduled_date:
            from datetime import datetime
            try:
                scheduled_date = datetime.fromisoformat(
                    request.scheduled_date.replace("Z", "+00:00")
                )
            except ValueError:
                raise HTTPException(status_code=422, detail="scheduledDate must be a valid ISO date/time.")

        booking_ref = db.collection("bookings").document(request.booking_id)
        existing = booking_ref.get()
        if existing.exists:
            existing_data = existing.to_dict() or {}
            if existing_data.get("customerId") != customer_id or existing_data.get("staffId") != request.staff_id:
                raise HTTPException(status_code=409, detail="Booking ID already belongs to another booking.")
            return {
                "success": True,
                "bookingId": request.booking_id,
                "notificationSent": bool(existing_data.get("notificationSent", False)),
                "alreadyCreated": True,
                "message": "This booking was already created.",
            }

        customer_name = customer.get("name") or customer.get("displayName") or "Customer"
        booking_data = {
            "id": request.booking_id,
            "customerId": customer_id,
            "staffId": request.staff_id,
            "serviceId": service_id,
            "serviceName": service_name.strip(),
            "customerName": str(customer_name),
            "staffName": str(staff.get("name") or staff.get("displayName") or "Staff"),
            "status": "pending",
            "scheduledDate": scheduled_date,
            "customerLatitude": customer.get("latitude"),
            "customerLongitude": customer.get("longitude"),
            "staffLatitude": staff.get("latitude", request.staff_latitude),
            "staffLongitude": staff.get("longitude", request.staff_longitude),
            "createdAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
            "notificationSent": False,
        }

        # create() is atomic and fails if this booking ID already exists.
        try:
            booking_ref.create(booking_data)
        except Exception:
            # Handle a simultaneous/retried request without creating a duplicate.
            latest = booking_ref.get()
            if latest.exists:
                latest_data = latest.to_dict() or {}
                if latest_data.get("customerId") == customer_id and latest_data.get("staffId") == request.staff_id:
                    return {
                        "success": True,
                        "bookingId": request.booking_id,
                        "notificationSent": bool(latest_data.get("notificationSent", False)),
                        "alreadyCreated": True,
                        "message": "This booking was already created.",
                    }
            raise

        notification_sent = False
        fcm_token = staff.get("fcmToken")
        if isinstance(fcm_token, str) and fcm_token.strip():
            try:
                messaging.send(messaging.Message(
                    token=fcm_token,
                    notification=messaging.Notification(
                        title="New booking request",
                        body=f"{customer_name} requested {service_name.strip()}.",
                    ),
                    data={
                        "type": "booking_created",
                        "bookingId": request.booking_id,
                        "staffId": request.staff_id,
                    },
                    android=messaging.AndroidConfig(priority="high"),
                    apns=messaging.APNSConfig(
                        payload=messaging.APNSPayload(aps=messaging.Aps(sound="default"))
                    ),
                ))
                notification_sent = True
                booking_ref.update({"notificationSent": True})
            except Exception as notification_error:
                # Booking is already persisted. Do not report it as failed or
                # let the client create a duplicate just because FCM failed.
                print(
                    f"FCM notification failed for booking {request.booking_id}: "
                    f"{type(notification_error).__name__}: {notification_error}",
                    flush=True,
                )
        else:
            print(f"No FCM token registered for staff {request.staff_id}.", flush=True)

        return {
            "success": True,
            "bookingId": request.booking_id,
            "notificationSent": notification_sent,
            "alreadyCreated": False,
            "message": "Booking created successfully.",
        }

    except HTTPException:
        raise
    except Exception as error:
        print(
            f"Booking creation failed: {type(error).__name__}: {error}",
            flush=True,
        )
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Unable to create booking right now.")


# =====================================================
# 6. FIREBASE TEST
# =====================================================

@app.get("/firebase-test")
def firebase_test():
    try:
        collections = list(db.collections())

        return {
            "firebase_connected": True,
            "project_id": "service-hub-26d86",
            "collections": [collection.id for collection in collections],
        }

    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Firebase connection failed. Check Firestore setup.",
        )


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
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Could not read user documents from Firestore.",
        )


# =====================================================
# 7. GENERAL AI CHAT
# =====================================================

@app.post("/chat")
def chat(request: ChatRequest):
    if client is None:
        raise HTTPException(
            status_code=500,
            detail="GROQ_API_KEY is not configured.",
        )

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are ServiceHub AI, a helpful local services "
                        "assistant. Never invent staff, availability, "
                        "prices, distances, or booking confirmations. "
                        "Only the backend can verify staff and bookings."
                    ),
                },
                {"role": "user", "content": request.message},
            ],
            max_completion_tokens=500,
        )

        return {
            "reply": (
                response.choices[0].message.content
                or "Please try asking another question."
            )
        }

    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=502,
            detail="The AI service is temporarily unavailable.",
        )


# =====================================================
# 8. REGISTERED STAFF SERVICES
# =====================================================

def get_registered_services() -> list[str]:
    """
    Read service names from:
    users/{staffId}/services/{serviceId}

    Only names actually saved by staff are returned.
    """
    available_services = set()

    staff_docs = (
        db.collection("users")
        .where("role", "==", "staff")
        .stream()
    )

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

    return sorted(available_services)


# =====================================================
# 9. SEARCH NEARBY ONLINE STAFF
# =====================================================

@app.get("/staff/search")
def search_staff(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    service_name: str = Query(..., min_length=2, max_length=100),
    radius_km: float = Query(default=10, gt=0, le=100),
):
    try:
        staff_docs = (
            db.collection("users")
            .where("role", "==", "staff")
            .stream()
        )

        results = []
        requested_name = normalize_text(service_name)

        for staff_doc in staff_docs:
            staff = staff_doc.to_dict() or {}

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

                # Match the selected service by its full normalized
                # name, rather than matching arbitrary substrings.
                if (
                    isinstance(actual_name, str)
                    and normalize_text(actual_name) == requested_name
                ):
                    matching_services.append({
                        "service_id": service.get("id", service_doc.id),
                        "name": actual_name,
                        "description": service.get("description", ""),
                    })

            if not matching_services:
                continue

            lat1 = math.radians(latitude)
            lat2 = math.radians(staff_lat)
            delta_lat = math.radians(staff_lat - latitude)
            delta_lon = math.radians(staff_lon - longitude)

            a = (
                math.sin(delta_lat / 2) ** 2
                + math.cos(lat1)
                * math.cos(lat2)
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

    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Unable to search for staff.",
        )


# =====================================================
# 10. AI SERVICE IDENTIFICATION
# =====================================================

@app.post("/identify-service")
def identify_service(request: IdentifyServiceRequest):
    if client is None:
        raise HTTPException(
            status_code=500,
            detail="GROQ_API_KEY is not configured.",
        )

    user_message = request.message.strip()

    if not user_message:
        raise HTTPException(
            status_code=422,
            detail="Please describe the service you need.",
        )

    try:
        service_names = get_registered_services()

        if not service_names:
            return {
                "intent": "unavailable",
                "reply": (
                    "Sorry, there are currently no services registered "
                    "on ServiceHub. Please tell us which service you need."
                ),
                "service_name": None,
                "requested_service": user_message,
                "requires_confirmation": False,
                "can_request_service": True,
            }

        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": """
You are ServiceHub AI. Match a customer's request to a service
registered by staff.

Return JSON with exactly:
intent, reply, service_name

Allowed intent values:
matched, unavailable, unclear

Rules:
1. Use only the provided registered services.
2. Understand synonyms and natural language.
3. "My AC is not cooling" may match AC Mechanic or AC Repair,
   if one of those services is registered.
4. "AC cleaning" should match AC Cleaning if registered.
5. "AC washing" should match AC Washing if registered.
6. Do not treat every AC-related task as the same service.
7. If two or more services are plausible and the distinction
   matters, return unclear and ask one short question.
8. For a vague message like "I need help", return unclear.
9. If the user clearly asks for a service that is not registered,
   return unavailable.
10. When matched, service_name must exactly equal one name in
    the registered list.
11. Never invent registered services, staff, prices, or availability.
12. Never promise that an unavailable service will be added.

Examples:
- "I need help" -> unclear
- "I need AC cleaning" -> matched only if AC Cleaning is registered
- "Clean my house" -> unavailable if no relevant service is registered

Keep the reply short and helpful.
""",
                },
                {
                    "role": "user",
                    "content": (
                        "Registered services:\n"
                        + json.dumps(service_names, ensure_ascii=False)
                        + "\n\nCustomer message:\n"
                        + user_message
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
        intent = result.get("intent")
        matched_name = get_service_by_exact_name(
            result.get("service_name"),
            service_names,
        )

        if intent == "matched" and matched_name:
            return {
                "intent": "matched",
                "reply": (
                    f"I found our registered service: {matched_name}. "
                    "Would you like me to search for nearby staff?"
                ),
                "service_name": matched_name,
                "requested_service": user_message,
                "requires_confirmation": True,
                "can_request_service": False,
            }

        if intent == "unavailable":
            return {
                "intent": "unavailable",
                "reply": (
                    f"Sorry, we don't currently offer a service matching "
                    f"'{user_message}'. Would you like to submit a request? "
                    "We'll record it for future review, and we may consider "
                    "adding this service later."
                ),
                "service_name": None,
                "requested_service": user_message,
                "requires_confirmation": False,
                "can_request_service": True,
            }

        # An invalid match or unclear response must not be trusted.
        if intent == "unclear" or not matched_name:
            return {
                "intent": "unclear",
                "reply": (
                    result.get("reply")
                    if isinstance(result.get("reply"), str)
                    and result.get("reply").strip()
                    else (
                        "I'm not completely sure which service you need. "
                        "Could you describe what you need help with?"
                    )
                ),
                "service_name": None,
                "requested_service": user_message,
                "requires_confirmation": False,
                "can_request_service": False,
            }

        return {
            "intent": "unclear",
            "reply": "Could you describe the service you need?",
            "service_name": None,
            "requested_service": user_message,
            "requires_confirmation": False,
            "can_request_service": False,
        }

    except HTTPException:
        raise

    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=502,
            detail="Unable to identify the service right now.",
        )


# =====================================================
# 11. SUBMIT A REQUEST FOR AN UNREGISTERED SERVICE
# =====================================================


@app.post("/service-requests", status_code=201)
def create_service_request(request: ServiceRequestCreate):
    requested_service = request.requested_service.strip()
    description = request.description.strip()

    # Validate the requested service
    if len(requested_service) < 2:
        raise HTTPException(
            status_code=422,
            detail="Please provide a valid service name.",
        )

    try:
        # Prepare data for Firestore
        request_data = {
            "requested_service": requested_service,
            "description": description,
            "status": "pending",
            "created_at": firestore.SERVER_TIMESTAMP,
        }

        # Save the request
        doc_ref = db.collection("service_requests").document()
        doc_ref.set(request_data)

        print(
            f"Service request created successfully: "
            f"request_id={doc_ref.id}, "
            f"requested_service={requested_service}",
            flush=True,
        )

        return {
            "success": True,
            "request_id": doc_ref.id,
            "requested_service": requested_service,
            "status": "pending",
            "message": (
                "Thank you for your suggestion! We've recorded your "
                "request for future review. We may consider adding "
                "this service later."
            ),
        }

    except HTTPException:
        raise

    except Exception as error:
        # Log the actual error in the FastAPI terminal
        print(
            f"Service request submission failed: "
            f"{type(error).__name__}: {error}",
            flush=True,
        )
        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail="Unable to submit your service request right now.",
        )
