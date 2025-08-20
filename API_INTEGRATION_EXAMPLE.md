# 🔌 API Integration Example

## Overview
This document shows how the WhisperLiveKit server integrates with the experience-event API at `http://192.168.10.213:4000/api/v1/experience-event`.

---

## 🎯 **Workflow Example**

### **Scenario: Restaurant Customer Interaction**

```
Customer: "customer_nguyen_van_a"
Session: "restaurant_table_05_evening"
Stream: "mic_table_05_seat_01"
```

### **Step-by-Step Flow:**

#### **1. Customer starts speaking**
```
FE → Server: audio_stream_start
Server logs: 🚀 Audio stream started - Session: restaurant_table_05_evening, Customer: customer_nguyen_van_a
```

#### **2. Customer says "xin chào"**
```
Server logs: 🗣️ TRANSCRIPT [restaurant_table_05_evening][customer_nguyen_van_a][mic_table_05_seat_01] Speaker 1: xin chào các bạn
Server logs: 🎉 KEYWORD DETECTED: SAY_HELLO - Session: restaurant_table_05_evening, Customer: customer_nguyen_van_a
Server logs: 🚀 API REQUEST: Calling http://192.168.10.213:4000/api/v1/experience-event with payload: {"UUID": "customer_nguyen_van_a", "EVENT": "SAY_HELLO"}
Server logs: ✅ API SUCCESS: SAY_HELLO for customer customer_nguyen_van_a - Response: {"status": "success"}
```

**API Call #1:**
```json
POST http://192.168.10.213:4000/api/v1/experience-event
{
  "UUID": "customer_nguyen_van_a",
  "EVENT": "SAY_HELLO"
}
```

#### **3. Customer continues conversation**
```
Server logs: 🗣️ TRANSCRIPT [restaurant_table_05_evening][customer_nguyen_van_a][mic_table_05_seat_01] Speaker 1: tôi muốn gọi món
Server logs: 🗣️ TRANSCRIPT [restaurant_table_05_evening][customer_nguyen_van_a][mic_table_05_seat_01] Speaker 1: cho tôi một ly cà phê
```

#### **4. Customer says "xin lỗi"**
```
Server logs: 🗣️ TRANSCRIPT [restaurant_table_05_evening][customer_nguyen_van_a][mic_table_05_seat_01] Speaker 1: xin lỗi tôi muốn đổi món
Server logs: 😔 KEYWORD DETECTED: SAY_SORRY - Session: restaurant_table_05_evening, Customer: customer_nguyen_van_a
Server logs: 🚀 API REQUEST: Calling http://192.168.10.213:4000/api/v1/experience-event with payload: {"UUID": "customer_nguyen_van_a", "EVENT": "SAY_SORRY"}
Server logs: ✅ API SUCCESS: SAY_SORRY for customer customer_nguyen_van_a - Response: {"status": "success"}
```

**API Call #2:**
```json
POST http://192.168.10.213:4000/api/v1/experience-event
{
  "UUID": "customer_nguyen_van_a",
  "EVENT": "SAY_SORRY"
}
```

#### **5. Customer says "xin chào" again (Duplicate Detection)**
```
Server logs: 🗣️ TRANSCRIPT [restaurant_table_05_evening][customer_nguyen_van_a][mic_table_05_seat_01] Speaker 1: xin chào lần nữa
Server logs: (No keyword detection - already detected SAY_HELLO for this customer)
```
**No API call** - Duplicate prevention working!

#### **6. Customer disconnects**
```
FE → Server: audio_stream_stop
Server logs: 🛑 Audio stream stop - Session: restaurant_table_05_evening, Customer: customer_nguyen_van_a
Server logs: 🏁 SESSION END: Calling API for customer customer_nguyen_van_a
Server logs: 📝 FULL TRANSCRIPT [customer_nguyen_van_a]: xin chào các bạn tôi muốn gọi món cho tôi một ly cà phê xin lỗi tôi muốn đổi món xin chào lần nữa
Server logs: 🚀 API REQUEST: Calling http://192.168.10.213:4000/api/v1/experience-event with payload: {"UUID": "customer_nguyen_van_a", "EVENT": "SESSION_END"}
Server logs: ✅ API SUCCESS: SESSION_END for customer customer_nguyen_van_a - Response: {"status": "success"}
Server logs: 🗑️ Cleaned up customer data for customer_nguyen_van_a
```

**API Call #3:**
```json
POST http://192.168.10.213:4000/api/v1/experience-event
{
  "UUID": "customer_nguyen_van_a",
  "EVENT": "SESSION_END"
}
```

---

## 📊 **Summary for this customer session:**

| API Call | Trigger | UUID | EVENT | Timing |
|----------|---------|------|-------|--------|
| #1 | Detected "xin chào" | customer_nguyen_van_a | SAY_HELLO | Immediate |
| #2 | Detected "xin lỗi" | customer_nguyen_van_a | SAY_SORRY | Immediate |
| #3 | Customer disconnect | customer_nguyen_van_a | SESSION_END | On disconnect |

**Total API calls: 3**

---

## 🔄 **Multi-Customer Example**

### **Same session, multiple customers:**

```
Session: "restaurant_table_05_evening"
├── Customer A: "customer_nguyen_van_a" → 3 API calls
├── Customer B: "customer_tran_thi_b" → 2 API calls (only SAY_HELLO + SESSION_END)
└── Customer C: "customer_le_van_c" → 1 API call (only SESSION_END)
```

**Each customer tracked independently!**

---

## ⚠️ **Error Handling Examples**

### **API Timeout:**
```
Server logs: ⏰ API TIMEOUT: SAY_HELLO for customer customer_nguyen_van_a - Request took longer than 10 seconds
```

### **API Server Down:**
```
Server logs: 🌐 API CONNECTION ERROR: SAY_HELLO for customer customer_nguyen_van_a - Error: Cannot connect to host 192.168.10.213:4000
```

### **API Error Response:**
```
Server logs: ⚠️ API ERROR: HTTP 500 for SAY_HELLO - customer customer_nguyen_van_a - Response: {"error": "Internal server error"}
```

---

## 🧪 **Testing Commands**

### **Start Server:**
```bash
cd WhisperLiveKit
uv run whisperlivekit-server --host 0.0.0.0 --port 8000 --model tiny --diarization --diarization-backend sortformer
```

### **Check Logs:**
Server will output detailed logs for every API call and transcript:
```
🗣️ TRANSCRIPT [session][customer][stream] Speaker X: transcript text
🎉 KEYWORD DETECTED: EVENT_TYPE - Session: session, Customer: customer
🚀 API REQUEST: Calling http://192.168.10.213:4000/api/v1/experience-event
✅ API SUCCESS: EVENT_TYPE for customer customer_id
```

### **WebSocket Connection:**
```
ws://localhost:8000/asr-multicam
```

Send messages according to the schema in `AUDIO_STREAM_SCHEMA.md`

---

## 🎯 **Production Considerations**

1. **API Reliability**: Current implementation has 10-second timeout
2. **Duplicate Prevention**: Keywords only trigger once per customer session
3. **Async Processing**: API calls don't block audio processing
4. **Error Logging**: All API failures are logged for monitoring
5. **Customer Isolation**: Each customer tracked independently
6. **Memory Cleanup**: Customer data cleaned up on disconnect

---

## 🔧 **Configuration**

To change API endpoint, modify this line in `basic_server.py`:
```python
api_url = "http://192.168.10.213:4000/api/v1/experience-event"
```

To add more keywords, extend the detection logic:
```python
if "keyword" in transcript_lower and "NEW_EVENT" not in customer_info["detected_keywords"]:
    customer_info["detected_keywords"].add("NEW_EVENT")
    asyncio.create_task(call_experience_event_api(customer_id, "NEW_EVENT"))
```

This integration provides real-time event tracking for customer interactions with comprehensive logging and error handling.
