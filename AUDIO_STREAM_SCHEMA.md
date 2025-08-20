# 🎤 Audio Stream WebSocket Schema

## Endpoint: `ws://localhost:8000/asr-multicam`

---

## 📋 **Protocol Overview**

The new audio streaming protocol uses structured JSON messages for session management and metadata, followed by binary audio data.

### **Message Flow:**
```
1. audio_stream_start (JSON) → Initialize session
2. audio_stream_ready (JSON) ← Server confirmation
3. audio_chunk_meta (JSON) → Chunk metadata
4. Binary audio data → Actual audio chunk
5. Repeat steps 3-4 for each audio chunk
6. audio_stream_stop (JSON) → End session
7. audio_stream_stopped (JSON) ← Server confirmation
```

---

## 📤 **Client → Server Messages**

### **1. audio_stream_start**
Initialize audio stream with session parameters.

```json
{
  "type": "audio_stream_start",
  "data": {
    "session_uuid": "store_session_001",         // Required: shared session for multiple customers
    "customer_id": "customer_nguyen_van_a",      // Required: unique customer identifier
    "stream_id": "mic_table_01",                 // Required: unique stream identifier
    "codec": "audio/webm;codecs=opus",           // Required: audio codec
    "channel_count": 1,                          // Required: audio channels
    "sample_rate": 48000,                        // Required: sample rate in Hz
    "timeslice_ms": 250,                         // Required: chunk duration in ms
    "client_ts": 1723960000000,                  // Required: client timestamp (ms)
    "metadata": {                                // Optional: additional metadata
      "customer_name": "Nguyễn Văn A",
      "table_number": "01",
      "location": "Main Hall"
    }
  }
}
```

### **2. audio_chunk_meta**
Metadata sent before each audio chunk.

```json
{
  "type": "audio_chunk_meta",
  "data": {
    "session_uuid": "store_session_001",        // Required: session identifier
    "customer_id": "customer_nguyen_van_a",     // Required: customer identifier
    "stream_id": "mic_table_01",                // Required: stream identifier
    "seq": 1234,                                // Required: sequence number (starts from 1)
    "ts": 1723960000250,                        // Required: client timestamp (ms)
    "codec": "audio/webm;codecs=opus",          // Required: audio codec
    "duration_ms_hint": 250                     // Required: expected chunk duration
  }
}
```

**Immediately after `audio_chunk_meta`, send binary audio data:**
- Format: Raw audio blob/bytes
- Size: Variable based on timeslice_ms and codec
- Encoding: As specified in codec field

### **3. audio_stream_stop**
End the audio stream session.

```json
{
  "type": "audio_stream_stop",
  "data": {
    "session_uuid": "store_session_001",        // Required: session identifier
    "customer_id": "customer_nguyen_van_a",     // Required: customer identifier
    "stream_id": "mic_table_01",                // Required: stream identifier
    "reason": "customer_left"                   // Optional: stop reason
  }
}
```

---

## 📥 **Server → Client Messages**

### **1. audio_stream_ready**
Confirmation that stream is initialized and ready.

```json
{
  "type": "audio_stream_ready",
  "data": {
    "session_uuid": "store_session_001",
    "customer_id": "customer_nguyen_van_a",
    "stream_id": "mic_table_01",
    "message": "Audio stream initialized successfully"
  }
}
```

### **2. Transcription Updates**
Real-time transcription results with session metadata.

```json
{
  "lines": [
    {
      "speaker": 1,
      "text": "xin chào, tôi là khách hàng",
      "beg": 0.5,
      "end": 2.8
    }
  ],
  "buffer_transcription": "đang xử lý...",
  "buffer_diarization": "nhận diện người nói...",
  "remaining_time_transcription": 0.3,
  "remaining_time_diarization": 0.8,
  "status": "active_transcription",
  "session_uuid": "store_session_001",
  "customer_id": "customer_nguyen_van_a",
  "stream_id": "mic_table_01",
  "timestamp": 1642781234.567
}
```

### **3. ready_to_stop**
Final processing complete signal.

```json
{
  "type": "ready_to_stop",
  "data": {
    "session_uuid": "store_session_001",
    "customer_id": "customer_nguyen_van_a",
    "stream_id": "mic_table_01"
  }
}
```

### **4. audio_stream_stopped**
Confirmation that stream has been stopped.

```json
{
  "type": "audio_stream_stopped",
  "data": {
    "session_uuid": "store_session_001",
    "customer_id": "customer_nguyen_van_a",
    "stream_id": "mic_table_01",
    "message": "Audio stream stopped successfully"
  }
}
```

### **5. Error Messages**
Error responses for invalid requests.

```json
{
  "type": "error",
  "message": "customer_id is required in audio_stream_start"
}
```

---

## 🔍 **Server-Side Features**

### **Transcript Logging**
Server logs all transcriptions to terminal with emojis:
```
🗣️ TRANSCRIPT [store_session_001][customer_nguyen_van_a][mic_table_01] Speaker 1: xin chào các bạn
🎉 KEYWORD DETECTED: SAY_HELLO - Session: store_session_001, Customer: customer_nguyen_van_a
😔 KEYWORD DETECTED: SAY_SORRY - Session: store_session_001, Customer: customer_nguyen_van_a
📝 BUFFER [store_session_001][customer_nguyen_van_a]: đang xử lý âm thanh...
🏁 Session store_session_001 fully closed - all customers disconnected
```

### **Keyword Detection**
Automatic detection of Vietnamese keywords:
- **"xin chào"** → Triggers `SAY_HELLO` event
- **"xin lỗi"** → Triggers `SAY_SORRY` event

### **Multi-Customer Session Management**
- **1 session_uuid** can handle **multiple customers** simultaneously
- Each customer has unique `customer_id` and `stream_id`
- Session closes only when **all customers** disconnect
- Individual customer tracking within shared sessions

### **Sequence Tracking**
Server validates sequence numbers and warns about missing chunks:
```
⚠️ Sequence mismatch - Expected: 1235, Got: 1237
```

---

## 💻 **JavaScript Implementation Example**

```javascript
const websocket = new WebSocket("ws://localhost:8000/asr-multicam");

// Step 1: Initialize stream
websocket.onopen = () => {
  const startMessage = {
    type: "audio_stream_start",
    data: {
      session_uuid: "restaurant_table_session",
      customer_id: "customer_nguyen_van_a",
      stream_id: "mic_table_05",
      codec: "audio/webm;codecs=opus",
      channel_count: 1,
      sample_rate: 48000,
      timeslice_ms: 250,
      client_ts: Date.now(),
      metadata: {
        customer_name: "Nguyễn Văn A",
        table_number: "05",
        location: "Main Hall"
      }
    }
  };
  websocket.send(JSON.stringify(startMessage));
};

// Step 2: Handle responses
websocket.onmessage = (event) => {
  const data = JSON.parse(event.data);

  switch(data.type) {
    case "audio_stream_ready":
      console.log("✅ Stream ready, starting audio capture");
      startAudioCapture();
      break;

    case "ready_to_stop":
      console.log("🏁 Processing complete");
      websocket.close();
      break;

    case "error":
      console.error("❌ Error:", data.message);
      break;

    default:
      // Regular transcription update
      console.log("📝 Transcript:", data.lines);
      displayTranscription(data);
  }
};

// Step 3: Send audio chunks
let sequenceNumber = 1;

function sendAudioChunk(audioBlob) {
  // Send metadata first
  const metaMessage = {
    type: "audio_chunk_meta",
    data: {
      session_uuid: "restaurant_table_session",
      customer_id: "customer_nguyen_van_a",
      stream_id: "mic_table_05",
      seq: sequenceNumber++,
      ts: Date.now(),
      codec: "audio/webm;codecs=opus",
      duration_ms_hint: 250
    }
  };

  websocket.send(JSON.stringify(metaMessage));

  // Then send binary audio data
  websocket.send(audioBlob);
}

// Step 4: Stop stream
function stopStream() {
  const stopMessage = {
    type: "audio_stream_stop",
    data: {
      session_uuid: "restaurant_table_session",
      customer_id: "customer_nguyen_van_a",
      stream_id: "mic_table_05",
      reason: "customer_left"
    }
  };
  websocket.send(JSON.stringify(stopMessage));
}
```

---

## 🐍 **Python Client Example**

```python
import asyncio
import websockets
import json
import time

async def audio_stream_client():
    uri = "ws://localhost:8000/asr-multicam"
    session_uuid = "python-test-session"
    customer_id = "customer_python_test"
    stream_id = "mic_python_test"

    async with websockets.connect(uri) as websocket:
        # Step 1: Initialize stream
        start_message = {
            "type": "audio_stream_start",
            "data": {
                "session_uuid": session_uuid,
                "customer_id": customer_id,
                "stream_id": stream_id,
                "codec": "audio/webm;codecs=opus",
                "channel_count": 1,
                "sample_rate": 48000,
                "timeslice_ms": 250,
                "client_ts": int(time.time() * 1000),
                "metadata": {
                    "customer_name": "Python Test Customer",
                    "location": "Development Lab"
                }
            }
        }

        await websocket.send(json.dumps(start_message))

        # Step 2: Wait for ready confirmation
        response = await websocket.recv()
        ready_data = json.loads(response)

        if ready_data["type"] == "audio_stream_ready":
            print(f"✅ Stream ready: {ready_data['data']['session_uuid']}")

            # Step 3: Send audio chunks
            with open("test_audio.webm", "rb") as audio_file:
                seq = 1
                chunk_size = 4096  # Adjust based on timeslice_ms

                while True:
                    audio_chunk = audio_file.read(chunk_size)
                    if not audio_chunk:
                        break

                    # Send metadata
                    meta_message = {
                        "type": "audio_chunk_meta",
                        "data": {
                            "session_uuid": session_uuid,
                            "customer_id": customer_id,
                            "stream_id": stream_id,
                            "seq": seq,
                            "ts": int(time.time() * 1000),
                            "codec": "audio/webm;codecs=opus",
                            "duration_ms_hint": 250
                        }
                    }

                    await websocket.send(json.dumps(meta_message))
                    await websocket.send(audio_chunk)

                    seq += 1

                    # Check for transcription responses
                    try:
                        response = await asyncio.wait_for(
                            websocket.recv(), timeout=0.1
                        )
                        data = json.loads(response)
                        if "lines" in data:
                            for line in data["lines"]:
                                print(f"🗣️ Speaker {line['speaker']}: {line['text']}")
                    except asyncio.TimeoutError:
                        continue

            # Step 4: Stop stream
            stop_message = {
                "type": "audio_stream_stop",
                "data": {
                    "session_uuid": session_uuid,
                    "customer_id": customer_id,
                    "stream_id": stream_id,
                    "reason": "file_complete"
                }
            }

            await websocket.send(json.dumps(stop_message))

            # Wait for final confirmation
            final_response = await websocket.recv()
            final_data = json.loads(final_response)
            print(f"🏁 Final: {final_data}")

# Run client
asyncio.run(audio_stream_client())
```

---

## ⚠️ **Important Notes**

1. **Message Order**: Must send `audio_stream_start` before any audio data
2. **Sequence Numbers**: Start from 1, increment for each chunk
3. **Binary Data**: Send immediately after `audio_chunk_meta`
4. **Multi-Customer Sessions**: One session_uuid can handle multiple customers
5. **Customer Identification**: Each customer needs unique `customer_id` and `stream_id`
6. **Error Handling**: Server validates all required fields
7. **Keyword Detection**: Automatic detection triggers logging (API integration pending)
8. **Session Lifecycle**: Session closes when ALL customers disconnect

---

## 🎯 **Use Cases**

- **Restaurant/Café**: Multiple customers per table session
- **Conference rooms**: Multiple participants in one meeting session
- **Retail stores**: Multiple customers in same shopping session
- **Contact centers**: Multiple agents handling same case session
- **Event venues**: Multiple attendees in same event session

### 🏪 **Restaurant Example**
```
Session: "restaurant_table_05_evening"
├── Customer A: "customer_nguyen_van_a" → stream "mic_seat_01"
├── Customer B: "customer_tran_thi_b" → stream "mic_seat_02"
├── Customer C: "customer_le_van_c" → stream "mic_seat_03"
└── Waiter: "staff_001" → stream "mic_waiter_headset"
```

This schema provides production-ready audio streaming with comprehensive session management and monitoring capabilities.
