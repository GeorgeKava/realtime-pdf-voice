+-------------------+         +---------------------+         +-------------------+
|    User Browser   | <-----> |    Frontend (JS)    | <-----> |    Backend (Py)   |
| (Web UI, Chat UI) |         |  static/app.js      |         |  backend.py       |
+-------------------+         +---------------------+         +-------------------+
        |                              |                                 |
        | 1. Loads index.html          |                                 |
        |----------------------------->|                                 |
        |                              |                                 |
        | 2. Fetches /get-session-configuration                         |
        |----------------------------->|                                 |
        |                              | 3. Serves config from config.py |
        |                              |<--------------------------------|
        |                              |                                 |
        | 4. User speaks/types         |                                 |
        |----------------------------->|                                 |
        |                              |                                 |
        | 5. Sends /start-session      |                                 |
        |----------------------------->|                                 |
        |                              | 6. Calls Azure OpenAI Sessions  |
        |                              |<--------------------------------|
        |                              |                                 |
        | 7. Establishes WebRTC        |                                 |
        |----------------------------->|                                 |
        |                              |                                 |
        | 8. Sends /webrtc-sdp         |                                 |
        |----------------------------->|                                 |
        |                              | 9. Forwards to Azure RTC        |
        |                              |<--------------------------------|
        |                              |                                 |
        | 10. User asks question       |                                 |
        |----------------------------->|                                 |
        |                              |                                 |
        | 11. If PDF query:            |                                 |
        |    /get-pdf-content or       |                                 |
        |    /handle-amazon-query      |                                 |
        |----------------------------->|                                 |
        |                              | 12. Extracts/processes PDF      |
        |                              |     or runs vector search       |
        |                              |<--------------------------------|
        |                              |                                 |
        | 13. Returns answer           |                                 |
        |<-----------------------------|                                 |
        |                              |                                 |
        | 14. Displays bot/user msgs   |                                 |
        |<-----------------------------|                                 |
        |                              |                                 |
        | 15. Bot speaks (TTS)         |                                 |
        |<-----------------------------|                                 |
        |                              |                                 |

Legend:
- Frontend: Handles UI, WebRTC, and API calls.
- Backend: Handles PDF processing, Azure Search, OpenAI, and session management.
- config.py: Central config for bot instructions, tools, and models.