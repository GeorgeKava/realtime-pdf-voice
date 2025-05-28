\
SESSION_CONFIGURATION = {
    "instructions": """
            You are Gary, a friendly and helpful assistant bot.
            Your primary goal is to answer user questions.
            User input will be provided via transcribed speech. The client will send a 'request.create' event with the transcribed text if needed, or the bot service handles transcription directly.
            When you call a function (like fetch_pdf_document or handle_amazon_query_tool), the system will process it and then send you a 'response.create' event containing instructions and the information retrieved. 
            You MUST use the information within the 'instructions' of that 'response.create' event to formulate a concise answer to the user's original question. 
            Then, you MUST immediately initiate a new message to the user, using both text (for transcript) and audio (for voice) modalities, to deliver this answer. 
            Do not wait for further input from the user after your function call has been processed and you have received the subsequent 'response.create' event; your job is to respond to the user with the information found.
        """,
    "turn_detection": {
        "type": "server_vad",
        "threshold": 0.5,
        "prefix_padding_ms": 300,
        "silence_duration_ms": 350,
        "create_response": True  # Python boolean
    },
    "tools": [
        {
            "type": "function",
            "name": "fetch_pdf_document",
            "description": "Provides information about Apple's financials by searching the vector store based on the query from the user.",
            "parameters": {
                "type": "object",
                "properties": {}, 
                "required": []
            }
        },
        {
            "type": "function",
            "name": "handle_amazon_query_tool",
            "description": "Provides information about Amazon's earnings by searching the vector store based on the query from the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "search_query": {
                        "type": "string",
                        "description": "User query string."
                    }
                },
                "required": ["search_query"]
            }
        }
    ],
    "tool_choice": "auto",
    "transcription_model": "whisper-1" # Added TRANSCRIPTION_MODEL
}

# You can also move other configurations here, like TRANSCRIPTION_MODEL
# For example:
# TRANSCRIPTION_MODEL = "whisper-1" 
# And then import it in backend.py if needed for other parts of the session setup.
